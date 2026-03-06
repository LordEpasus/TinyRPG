import math
import os
import random
import hashlib

import pygame

from settings import (
    COMPAT_SPRITES,
    FPS,
    HUD_FULL_SHOW_MS,
    HUD_IDLE_HIDE_MS,
    MAP_COLS,
    MAP_ROWS,
    SPAWN_SAFE_RADIUS,
    TILE_DIRT,
    TILE_GRASS,
    TILE_WATER,
    TILE_SIZE,
    TINY_SWORDS,
    TITLE,
    GREEN,
    WHITE,
    YELLOW,
)
from src.engine.camera import Camera
from src.engine.pathfinder import Pathfinder
from src.engine.tilemap import TileMap
from src.ai.opponent import AIController
from src.entities.building import Building
from src.entities.civilization import Civilization
from src.entities.ship import Ship
from src.entities.unit import Unit
from src.systems.resources import ResourceManager
from src.systems.tech_tree import AGE_ORDER, TechTree
from src.systems.tutorial import TutorialManager
from src.systems.campaign import CampaignTracker
from src.systems.replay import ReplayManager
from src.ui.display import ensure_display_surface, toggle_fullscreen
from src.ui.hud import GameHUD
from src.ui.icons import load_icon
from src.ui.sound import SoundManager
from src.network import protocol
from src.network.client import NetworkClient


_TREE_H = TILE_SIZE * 2


class Game:
    def __init__(
        self,
        *,
        player_civilization: str = "Blue",
        map_seed: int | None = None,
        net: "NetworkClient | None" = None,
        player_id: int = 0,
        online_opponent_civ: str | None = None,
        scenario: str = "skirmish",
        campaign_mission: int = 0,
        replay_mode: str = ReplayManager.MODE_RECORD,
        replay_path: str | None = None,
    ):
        pygame.init()
        self.screen = ensure_display_surface()

        # ── Multiplayer network ────────────────────────────────────────────────
        self.net: NetworkClient | None = net
        self.player_id: int = player_id  # 0=host, 1=guest
        self._network_enabled = net is not None
        self.online_opponent_civ: str | None = online_opponent_civ
        self._net_disconnect_notified = False
        self._disconnect_sent = False
        self._sync_tick = 0
        self._sync_tick_send_timer_s = 0.0
        self._remote_sync_tick = 0
        self._state_hash_timer_s = 0.0
        self._desync_alert_s = 0.0
        self._desync_count = 0

        # Reset unit UID counter so both machines produce identical UIDs.
        Unit._uid_seq = 0
        Ship._sid_seq = 0

        all_civs = ("Blue", "Red", "Yellow", "Purple", "Black")
        self.player_civilization = player_civilization if player_civilization in all_civs else "Blue"
        self.scenario = str(scenario or "skirmish")
        self.campaign_mission = int(campaign_mission)

        if net is not None and online_opponent_civ:
            remaining = [c for c in all_civs if c not in (self.player_civilization, online_opponent_civ)]
            self.ai_civilizations = remaining[:2]
            self.enemy_civilizations = [online_opponent_civ, *self.ai_civilizations]
        else:
            enemy_choices = [c for c in all_civs if c != self.player_civilization]
            self.ai_civilizations = enemy_choices[:3]
            self.enemy_civilizations = enemy_choices[:3]

        if self.scenario == "tutorial":
            self.ai_civilizations = self.enemy_civilizations[:1]
            self.enemy_civilizations = self.enemy_civilizations[:1]
        elif self.scenario == "campaign":
            if self.campaign_mission == 1:
                self.ai_civilizations = self.enemy_civilizations[:1]
                self.enemy_civilizations = self.enemy_civilizations[:1]
            else:
                self.ai_civilizations = self.enemy_civilizations[:2]
                self.enemy_civilizations = self.enemy_civilizations[:2]

        self.enemy_civilization = self.enemy_civilizations[0] if self.enemy_civilizations else "Red"
        self.map_seed = int(map_seed) if map_seed is not None else random.SystemRandom().randint(1, 2_147_483_647)
        Unit.PLAYER_CIVILIZATION = self.player_civilization
        mode_tag = "LAN" if net is not None else "SP"
        pygame.display.set_caption(f"{TITLE} - {self.player_civilization} [{mode_tag}] - Seed {self.map_seed}")
        self.clock = pygame.time.Clock()
        self.running = True
        self.game_result: str | None = None
        self._game_elapsed_s = 0.0

        self.show_grid = False
        self._building_blocked_tiles: set[tuple[int, int]] = set()
        self._building_resource_reserved_tiles: set[tuple[int, int]] = set()
        self._tree_skip_tiles: set[tuple[int, int]] = set()
        self._spawn_tiles = self._default_spawn_tiles()
        spawn_centers = [self._tile_to_world(col, row) for col, row in self._spawn_tiles.values()]
        self._spawn_world = spawn_centers[0]
        self._enemy_spawn_world = spawn_centers[-1]

        self.camera = Camera()
        self.tilemap = TileMap(
            seed=self.map_seed,
            spawn_centers=spawn_centers,
            spawn_safe_radius=SPAWN_SAFE_RADIUS,
        )
        self.pathfinder = Pathfinder(self.tilemap)
        self.tree_sets = self._load_tree_sets()
        self._spawn_worlds = self._resolve_spawn_worlds(spawn_centers)
        self._civ_spawn_worlds = self._assign_civ_spawn_worlds()
        self._spawn_civ_order = self._compute_spawn_civ_order()
        self._spawn_world = self._civ_spawn_worlds[self.player_civilization]
        self._enemy_spawn_world = self._civ_spawn_worlds.get(self.enemy_civilization, self._spawn_worlds["SE"])

        self.buildings: list[Building] = []
        self.ships: list[Ship] = []
        self._ship_by_sid: dict[int, Ship] = {}
        self.units: list[Unit] = []
        self._unit_by_uid: dict[int, Unit] = {}
        self._selected: list[Unit] = []
        self._selected_ships: list[Ship] = []
        self._selected_enemy_unit: Unit | None = None
        self._selected_node = None
        self._selected_building: Building | None = None
        self._building_ui_buttons: list[tuple[pygame.Rect, dict[str, str | float | int]]] = []
        self._build_palette_buttons: list[tuple[pygame.Rect, str]] = []
        self._build_palette_toggle_rect = pygame.Rect(0, 0, 0, 0)
        self._build_palette_collapsed = False
        self._build_mode_type: str | None = None
        self._build_hover_anchor: tuple[int, int] | None = None
        self._box_start: tuple[int, int] | None = None
        self._rng = random.Random(self.map_seed + 7701)
        self._worker_haul: dict[int, dict[str, object]] = {}
        self._chaos_state_timer_s = 0.0
        self._civ_sync_timer_s = 0.0
        self._chaos_factions = {"OrcRed", "OrcYellow", "SlimeBlue", "SlimePink"}
        self._formation_modes = ("box", "line", "wedge")
        self._formation_mode_idx = 0
        self.civilizations: dict[str, Civilization] = {}

        self.resource_manager: ResourceManager | None = None
        self._spawn_start_buildings()
        self._refresh_building_masks()
        forbidden_nodes = self._building_blocked_tiles | self._spawn_buffer_tiles(SPAWN_SAFE_RADIUS + 2)
        self.resource_manager = ResourceManager(
            self.tilemap,
            seed=self.map_seed,
            forbidden_tiles=forbidden_nodes,
            starting_resources={"gold": 1000, "wood": 1000, "stone": 1000, "food": 0, "meat": 0},
        )
        if self.scenario == "tutorial":
            self.resource_manager.resources.update({"gold": 1200, "wood": 1200, "stone": 1200, "food": 90, "meat": 80})
        elif self.scenario == "campaign" and self.campaign_mission == 1:
            self.resource_manager.resources.update({"gold": 1300, "wood": 1250, "stone": 1100, "food": 120, "meat": 60})
        elif self.scenario == "campaign":
            self.resource_manager.resources.update({"gold": 1500, "wood": 1300, "stone": 1300, "food": 150, "meat": 80})
        self._refresh_tree_skip_tiles()

        self._base_storage = {
            "gold": 1200,
            "wood": 1200,
            "stone": 1200,
            "food": 900,
            "meat": 500,
        }

        self._tool_unlocked: dict[str, bool] = {
            "tool_01": False,
            "tool_02": False,
            "tool_03": False,
            "tool_04": False,
        }
        self._soldier_hunger_drain_mult = 1.0

        self._spawn_start_units()
        self.ai_controllers: list[AIController] = []
        self._ai_by_civ: dict[str, AIController] = {}
        ai_civs = self.ai_civilizations if self._network_enabled else self.enemy_civilizations
        for i, civ in enumerate(ai_civs):
            ctrl = AIController(
                self,
                civilization=civ,
                enemy_civilization=self.player_civilization,
                seed=self.map_seed + (i + 1) * 101,
                base_world=self._civ_spawn_worlds.get(civ),
            )
            ctrl.bootstrap()
            self.ai_controllers.append(ctrl)
            self._ai_by_civ[civ] = ctrl
        self.ai_controller = self.ai_controllers[0] if self.ai_controllers else None
        if not self._network_enabled and self.scenario not in ("tutorial", "campaign"):
            self._spawn_chaos_units()
        self._refresh_building_masks()
        self._reindex_units()
        self._reindex_ships()
        self._update_storage_capacity()
        self._sync_civilizations()

        all_known_civs = {self.player_civilization, *self.enemy_civilizations, *self.ai_civilizations}
        self.tech_tree = TechTree(sorted(all_known_civs))
        self._ai_age_timer_s = 0.0
        for unit in self.units:
            self._apply_unit_age_bonus(unit)

        house_count = sum(
            1
            for b in self.buildings
            if (
                b.civilization == self.player_civilization
                and b.building_type in (Building.TYPE_HOUSE1, Building.TYPE_HOUSE2, Building.TYPE_HOUSE3)
            )
        )
        self.tutorial = TutorialManager(enabled=self.scenario == "tutorial", initial_house_count=house_count)
        self.campaign = CampaignTracker(
            enabled=self.scenario == "campaign",
            mission_id=self.campaign_mission if self.campaign_mission > 0 else 1,
            player_civilization=self.player_civilization,
        )

        replay_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "replays")
        if replay_mode == ReplayManager.MODE_PLAYBACK:
            self.replay = ReplayManager(
                mode=ReplayManager.MODE_PLAYBACK,
                replay_path=replay_path,
                base_dir=replay_base,
            )
        else:
            mode = ReplayManager.MODE_RECORD if replay_mode == ReplayManager.MODE_RECORD else ReplayManager.MODE_OFF
            if self._network_enabled and mode == ReplayManager.MODE_RECORD:
                mode = ReplayManager.MODE_OFF
            self.replay = ReplayManager(
                mode=mode,
                replay_path=replay_path,
                base_dir=replay_base,
                meta={
                    "seed": int(self.map_seed),
                    "player_civilization": self.player_civilization,
                    "scenario": self.scenario,
                    "campaign_mission": int(self.campaign_mission),
                },
            )
        self._replay_summary = self.replay.summary() if self.replay.is_playback else {}

        now = pygame.time.get_ticks()
        self._hud_pinned = False
        self._hud_last_activity_ms = now
        self._hud_full_until_ms = now + HUD_FULL_SHOW_MS
        self._edge_scroll_lock_s = 0.8

        self.font_md = pygame.font.SysFont("monospace", 15, bold=True)
        self.font_sm = pygame.font.SysFont("monospace", 13)
        self.font_xs = pygame.font.SysFont("monospace", 11)
        self._ui_unit_icons = self._load_unit_ui_icons()
        self._ui_tool_icons = self._load_tool_icons()
        self._ui_build_icons = self._load_build_icons()
        self._ui_skin = self._load_ui_skin()
        self.hud_ui = GameHUD(self.tilemap)
        self.sound = SoundManager()

    # ── Assets ────────────────────────────────────────────────────────────────
    def _load_tree_sets(self) -> list[list[pygame.Surface]]:
        results: list[list[pygame.Surface]] = []
        tree_dir = os.path.join(TINY_SWORDS, "Terrain", "Resources", "Wood", "Trees")

        for i in range(1, 5):
            path = os.path.join(tree_dir, f"Tree{i}.png")
            if not os.path.exists(path):
                continue
            sheet = pygame.image.load(path).convert_alpha()
            h = sheet.get_height()
            frame_w = h
            if frame_w > sheet.get_width():
                frame_w = sheet.get_width()
            frame_count = max(1, sheet.get_width() // frame_w)

            best_raw = None
            best_score = -1
            for fi in range(frame_count):
                raw = sheet.subsurface((fi * frame_w, 0, frame_w, h))
                bbox = raw.get_bounding_rect(min_alpha=1)
                area = bbox.width * bbox.height
                score = bbox.width * 10000 + area
                if score > best_score:
                    best_score = score
                    best_raw = raw
            if best_raw is None:
                continue

            scale = _TREE_H / h
            new_w = max(1, int(frame_w * scale))
            new_h = max(1, int(h * scale))
            results.append([pygame.transform.scale(best_raw, (new_w, new_h))])

        if not results:
            fb = pygame.Surface((TILE_SIZE, _TREE_H), pygame.SRCALPHA)
            fb.fill((30, 90, 30, 200))
            results.append([fb])

        return results

    def _extract_best_icon(self, path: str, *, size: int = 20) -> pygame.Surface | None:
        if not os.path.exists(path):
            return None
        sheet = pygame.image.load(path).convert_alpha()
        w, h = sheet.get_size()
        frame_w = h if h > 0 else w
        if frame_w > w:
            frame_w = w
        if frame_w <= 0:
            return None
        frame_count = max(1, w // frame_w)

        best = None
        best_score = -1
        for i in range(frame_count):
            raw = sheet.subsurface((i * frame_w, 0, frame_w, h)).copy()
            bbox = raw.get_bounding_rect(min_alpha=1)
            score = bbox.width * 10000 + bbox.width * bbox.height
            if score > best_score:
                best_score = score
                best = raw
        if best is None:
            return None
        return pygame.transform.scale(best, (size, size))

    def _load_unit_ui_icons(self) -> dict[str, pygame.Surface]:
        base = os.path.join(TINY_SWORDS, "Units", f"{self.player_civilization} Units")
        compat_base = os.path.join(COMPAT_SPRITES, "units", "kenney_units")
        mapping = {
            Unit.ROLE_WORKER: (
                os.path.join(compat_base, "medievalUnit_01.png"),
                os.path.join(base, "Pawn", "Pawn_Idle.png"),
            ),
            Unit.ROLE_WARRIOR: (
                os.path.join(compat_base, "medievalUnit_12.png"),
                os.path.join(base, "Warrior", "Warrior_Idle.png"),
            ),
            Unit.ROLE_ARCHER: (
                os.path.join(compat_base, "medievalUnit_08.png"),
                os.path.join(base, "Archer", "Archer_Idle.png"),
            ),
            Unit.ROLE_LANCER: (
                os.path.join(compat_base, "medievalUnit_21.png"),
                os.path.join(base, "Lancer", "Lancer_Idle.png"),
            ),
            Unit.ROLE_MONK: (
                os.path.join(compat_base, "medievalUnit_23.png"),
                os.path.join(base, "Monk", "Idle.png"),
            ),
            Unit.ROLE_HERO: (
                os.path.join(compat_base, "medievalUnit_18.png"),
                os.path.join(base, "Warrior", "Warrior_Idle.png"),
            ),
        }
        icons: dict[str, pygame.Surface] = {}
        for unit_class, paths in mapping.items():
            for path in paths:
                icon = self._extract_best_icon(path, size=20)
                if icon is not None:
                    icons[unit_class] = icon
                    break
        return icons

    def _load_tool_icons(self) -> dict[str, pygame.Surface]:
        base = os.path.join(TINY_SWORDS, "Terrain", "Resources", "Tools")
        mapping = {
            "tool_01": os.path.join(base, "Tool_01.png"),
            "tool_02": os.path.join(base, "Tool_02.png"),
            "tool_03": os.path.join(base, "Tool_03.png"),
            "tool_04": os.path.join(base, "Tool_04.png"),
        }
        icons: dict[str, pygame.Surface] = {}
        for key, path in mapping.items():
            icon = self._extract_best_icon(path, size=18)
            if icon is not None:
                icons[key] = icon
        return icons

    def _load_build_icons(self) -> dict[str, pygame.Surface]:
        out: dict[str, pygame.Surface] = {}
        compat_base = os.path.join(COMPAT_SPRITES, "castles", "kenney_structures")
        compat_map = {
            Building.TYPE_HOUSE1: "medievalStructure_01.png",
            Building.TYPE_HOUSE2: "medievalStructure_02.png",
            Building.TYPE_HOUSE3: "medievalStructure_03.png",
            Building.TYPE_BARRACKS: "medievalStructure_14.png",
            Building.TYPE_ARCHERY: "medievalStructure_11.png",
            Building.TYPE_SMITHY: "medievalStructure_10.png",
            Building.TYPE_TOWER: "medievalStructure_22.png",
            Building.TYPE_CASTLE: "medievalStructure_21.png",
        }
        for btype, file_name in compat_map.items():
            path = os.path.join(compat_base, file_name)
            icon = self._extract_best_icon(path, size=24)
            if icon is not None:
                out[btype] = icon

        icon_map = {
            Building.TYPE_HOUSE1: "village",
            Building.TYPE_HOUSE2: "village",
            Building.TYPE_HOUSE3: "village",
            Building.TYPE_BARRACKS: "crossed-swords",
            Building.TYPE_ARCHERY: "bow-arrow",
            Building.TYPE_SMITHY: "anvil",
            Building.TYPE_TOWER: "watchtower",
            Building.TYPE_CASTLE: "castle",
        }
        for btype, icon_name in icon_map.items():
            if btype in out:
                continue
            icon = load_icon(icon_name, size=24)
            if icon is not None:
                out[btype] = icon
        # Fallback to building sprites if custom icon pack is missing.
        if len(out) < len(icon_map):
            base = os.path.join(TINY_SWORDS, "Buildings", f"{self.player_civilization} Buildings")
            files = {
                Building.TYPE_HOUSE1: "House1.png",
                Building.TYPE_HOUSE2: "House2.png",
                Building.TYPE_HOUSE3: "House3.png",
                Building.TYPE_BARRACKS: "Barracks.png",
                Building.TYPE_ARCHERY: "Archery.png",
                Building.TYPE_SMITHY: "Monastery.png",
                Building.TYPE_TOWER: "Tower.png",
                Building.TYPE_CASTLE: "Castle.png",
            }
            for btype, file_name in files.items():
                if btype in out:
                    continue
                path = os.path.join(base, file_name)
                icon = self._extract_best_icon(path, size=24)
                if icon is not None:
                    out[btype] = icon
        return out

    def _load_ui_skin(self) -> dict[str, pygame.Surface]:
        ui_dir = os.path.join(TINY_SWORDS, "UI Elements", "UI Elements")
        skin: dict[str, pygame.Surface] = {}

        def load(name: str, path_parts: tuple[str, ...]) -> None:
            path = os.path.join(ui_dir, *path_parts)
            if os.path.exists(path):
                skin[name] = pygame.image.load(path).convert_alpha()

        load("wood_table", ("Wood Table", "WoodTable.png"))
        load("wood_table_slots", ("Wood Table", "WoodTable_Slots.png"))
        load("paper_regular", ("Papers", "RegularPaper.png"))
        load("button_blue", ("Buttons", "BigBlueButton_Regular.png"))
        load("button_red", ("Buttons", "BigRedButton_Regular.png"))
        return skin

    # ── Startup ───────────────────────────────────────────────────────────────
    @staticmethod
    def _tile_to_world(col: int, row: int) -> tuple[float, float]:
        return (
            col * TILE_SIZE + TILE_SIZE // 2,
            row * TILE_SIZE + TILE_SIZE // 2,
        )

    def _default_spawn_tiles(self) -> dict[str, tuple[int, int]]:
        margin_col = max(14, MAP_COLS // 6)
        margin_row = max(12, MAP_ROWS // 6)
        return {
            "NW": (margin_col, margin_row),
            "NE": (MAP_COLS - margin_col - 1, margin_row),
            "SW": (margin_col, MAP_ROWS - margin_row - 1),
            "SE": (MAP_COLS - margin_col - 1, MAP_ROWS - margin_row - 1),
        }

    def _resolve_spawn_worlds(self, spawn_centers: list[tuple[float, float]]) -> dict[str, tuple[float, float]]:
        keys = ("NW", "NE", "SW", "SE")
        out: dict[str, tuple[float, float]] = {}
        for i, key in enumerate(keys):
            wx, wy = spawn_centers[i]
            out[key] = self._find_spawn_world_near(wx, wy)
        return out

    def _assign_civ_spawn_worlds(self) -> dict[str, tuple[float, float]]:
        # Multiplayer (LAN): host side (player_id=0) is NW, guest side is NE.
        if self._network_enabled and self.online_opponent_civ:
            host_civ = self.player_civilization if self.player_id == 0 else self.online_opponent_civ
            guest_civ = self.online_opponent_civ if self.player_id == 0 else self.player_civilization
            mapping: dict[str, tuple[float, float]] = {
                host_civ: self._spawn_worlds["NW"],
                guest_civ: self._spawn_worlds["NE"],
            }
            if self.ai_civilizations:
                mapping[self.ai_civilizations[0]] = self._spawn_worlds["SW"]
            if len(self.ai_civilizations) > 1:
                mapping[self.ai_civilizations[1]] = self._spawn_worlds["SE"]
            return mapping

        # Single-player: player starts NW; AI kingdoms occupy remaining corners.
        corners = ("NW", "NE", "SW", "SE")
        mapping: dict[str, tuple[float, float]] = {
            self.player_civilization: self._spawn_worlds[corners[0]],
        }
        for i, civ in enumerate(self.enemy_civilizations):
            corner = corners[min(i + 1, len(corners) - 1)]
            mapping[civ] = self._spawn_worlds[corner]
        return mapping

    def _spawn_buffer_tiles(self, radius: int) -> set[tuple[int, int]]:
        tiles: set[tuple[int, int]] = set()
        rr = max(0, int(radius))
        for wx, wy in self._spawn_worlds.values():
            c0, r0 = self.tilemap.world_to_tile(wx, wy)
            for row in range(r0 - rr, r0 + rr + 1):
                if not (0 <= row < self.tilemap.rows):
                    continue
                for col in range(c0 - rr, c0 + rr + 1):
                    if not (0 <= col < self.tilemap.cols):
                        continue
                    dx = col - c0
                    dy = row - r0
                    if dx * dx + dy * dy <= rr * rr:
                        tiles.add((col, row))
        return tiles

    def _compute_spawn_civ_order(self) -> list[str]:
        order: list[str] = []
        for corner in ("NW", "NE", "SW", "SE"):
            corner_world = self._spawn_worlds[corner]
            civ = next((name for name, world in self._civ_spawn_worlds.items() if world == corner_world), None)
            if civ is not None and civ not in order:
                order.append(civ)
        for civ in sorted(self._civ_spawn_worlds):
            if civ not in order:
                order.append(civ)
        return order

    def _find_anchor_near(
        self,
        seed_tile: tuple[int, int],
        building_type: str,
        *,
        max_radius: int = 18,
    ) -> tuple[int, int] | None:
        sc, sr = seed_tile
        for radius in range(0, max_radius + 1):
            ring: list[tuple[int, int]] = []
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if abs(dc) != radius and abs(dr) != radius:
                        continue
                    c = sc + dc
                    r = sr + dr
                    if not (0 <= c < self.tilemap.cols and 0 <= r < self.tilemap.rows):
                        continue
                    ring.append((c, r))
            for anchor in ring:
                footprint = self._candidate_footprint(anchor, building_type)
                if self._is_placement_valid(footprint):
                    return anchor
        return None

    def _building_touches_water(self, footprint: set[tuple[int, int]]) -> bool:
        if not footprint:
            return False
        for col, row in footprint:
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nc = col + dc
                nr = row + dr
                if 0 <= nc < self.tilemap.cols and 0 <= nr < self.tilemap.rows:
                    if self.tilemap.get_tile(nc, nr) == TILE_WATER:
                        return True
        return False

    def _create_start_building(
        self,
        anchor_tile: tuple[int, int],
        building_type: str,
        *,
        civilization: str,
    ) -> Building:
        wx, wy = self.tilemap.tile_center(anchor_tile[0], anchor_tile[1])
        b = Building(
            wx,
            wy,
            building_type=building_type,
            civilization=civilization,
            max_hp=self._max_hp_for_building(building_type),
            start_progress=1.0,
        )
        if b.building_type == Building.TYPE_TOWER:
            b.is_dock = self._building_touches_water(b.footprint_tiles(self.tilemap))
        self.buildings.append(b)
        return b

    def _spawn_start_buildings(self) -> None:
        plans: list[tuple[str, tuple[float, float]]] = []
        if self._network_enabled:
            for civ in self._spawn_civ_order:
                if civ in self._civ_spawn_worlds:
                    plans.append((civ, self._civ_spawn_worlds[civ]))
        else:
            plans.append((self.player_civilization, self._civ_spawn_worlds[self.player_civilization]))
            for civ in self.enemy_civilizations:
                if civ in self._civ_spawn_worlds:
                    plans.append((civ, self._civ_spawn_worlds[civ]))
        house_offsets = [(-5, 2), (5, 2)]

        for civilization, (swx, swy) in plans:
            sc, sr = self.tilemap.world_to_tile(swx, swy)
            castle_anchor = self._find_anchor_near((sc, sr), Building.TYPE_CASTLE, max_radius=20)
            if castle_anchor is None:
                continue
            self._create_start_building(castle_anchor, Building.TYPE_CASTLE, civilization=civilization)

            for dc, dr in house_offsets:
                seed = (castle_anchor[0] + dc, castle_anchor[1] + dr)
                house_anchor = self._find_anchor_near(seed, Building.TYPE_HOUSE1, max_radius=10)
                if house_anchor is None:
                    continue
                self._create_start_building(house_anchor, Building.TYPE_HOUSE1, civilization=civilization)

    def _spawn_civ_start_units(self, civilization: str, center: tuple[float, float]) -> None:
        cx, cy = center
        hx, hy = self._find_spawn_world_near(cx, cy - 16)
        self.units.append(Unit(hx, hy, civilization=civilization, unit_class=Unit.ROLE_HERO))
        mx, my = self._find_spawn_world_near(cx + 36, cy + 66)
        self.units.append(Unit(mx, my, civilization=civilization, unit_class=Unit.ROLE_MONK))

        formation = [
            (90, 0),
            (-90, 0),
            (0, 90),
            (0, -90),
            (72, 72),
        ]
        for dx, dy in formation:
            wx, wy = self._find_spawn_world_near(cx + dx, cy + dy + 24)
            self.units.append(
                Unit(
                    wx,
                    wy,
                    civilization=civilization,
                    unit_class=Unit.ROLE_WORKER,
                )
            )

    def _spawn_start_units(self) -> None:
        if self._network_enabled and self.online_opponent_civ:
            # In LAN both human kingdoms get deterministic symmetric starts.
            human_order: list[str] = []
            host_civ = self.player_civilization if self.player_id == 0 else self.online_opponent_civ
            guest_civ = self.online_opponent_civ if self.player_id == 0 else self.player_civilization
            for civ in (host_civ, guest_civ):
                if civ not in human_order:
                    human_order.append(civ)
            for civ in human_order:
                spawn_center = self._civ_spawn_worlds.get(civ)
                if spawn_center is None:
                    continue
                self._spawn_civ_start_units(civ, spawn_center)
        else:
            self._spawn_civ_start_units(self.player_civilization, self._spawn_world)

        cx, cy = self._spawn_world
        self.camera.center_on_world(cx, cy)

    @staticmethod
    def _is_chaos_civ(civilization: str) -> bool:
        return civilization.startswith("Orc") or civilization.startswith("Slime")

    def _spawn_chaos_units(self) -> None:
        anchors = [
            self._spawn_worlds["NE"],
            self._spawn_worlds["SW"],
            self._tile_to_world(MAP_COLS // 2, max(2, MAP_ROWS // 2 - MAP_ROWS // 6)),
            self._tile_to_world(MAP_COLS // 2, min(MAP_ROWS - 3, MAP_ROWS // 2 + MAP_ROWS // 6)),
        ]
        plans = [
            ("OrcRed", anchors[0], Unit.ROLE_WARRIOR, 2),
            ("OrcYellow", anchors[1], Unit.ROLE_WARRIOR, 2),
            ("SlimeBlue", anchors[2], Unit.ROLE_WARRIOR, 2),
            ("SlimePink", anchors[3], Unit.ROLE_WARRIOR, 2),
        ]
        for civilization, (ax, ay), unit_class, count in plans:
            for i in range(count):
                off_x = ((i % 2) - 0.5) * TILE_SIZE * 1.2
                off_y = (i // 2) * TILE_SIZE * 0.9
                wx, wy = self._find_spawn_world_near(ax + off_x, ay + off_y)
                self.units.append(Unit(wx, wy, civilization=civilization, unit_class=unit_class))

    def _get_or_create_civilization(self, color: str) -> Civilization:
        civ = self.civilizations.get(color)
        if civ is not None:
            return civ
        civ = Civilization(color=color)
        self.civilizations[color] = civ
        return civ

    def _sync_civilizations(self) -> None:
        fixed = ("Blue", "Red", "Yellow", "Purple", "Black")
        for key in fixed:
            self._get_or_create_civilization(key)
        for civ in self.civilizations.values():
            civ.units.clear()
            civ.buildings.clear()

        for unit in self.units:
            civ = self._get_or_create_civilization(unit.civilization)
            civ.add_unit(unit)
        for building in self.buildings:
            if building.is_dead:
                continue
            civ = self._get_or_create_civilization(building.civilization)
            civ.add_building(building)

        player = self._get_or_create_civilization(self.player_civilization)
        player.resources = {
            "gold": self.resource_manager.resources.get("gold", 0),
            "wood": self.resource_manager.resources.get("wood", 0),
            "stone": self.resource_manager.resources.get("stone", 0),
        }
        for civ in self.enemy_civilizations:
            enemy = self._get_or_create_civilization(civ)
            ctrl = self._ai_by_civ.get(civ)
            if ctrl is None:
                continue
            enemy.resources = {
                "gold": ctrl.resources.get("gold", 0),
                "wood": ctrl.resources.get("wood", 0),
                "stone": ctrl.resources.get("stone", 0),
            }

    def _spawn_enemy_units(self) -> None:
        # Backward-compatible hook for all AI factions.
        for ai in self.ai_controllers:
            ai.bootstrap()

    # ── Network helpers ───────────────────────────────────────────────────────
    def _reindex_units(self) -> None:
        self._unit_by_uid = {int(unit.uid): unit for unit in self.units if not unit.is_dead}

    def _reindex_ships(self) -> None:
        self._ship_by_sid = {int(ship.sid): ship for ship in self.ships}

    def _unit_from_uid(self, uid: int) -> Unit | None:
        unit = self._unit_by_uid.get(int(uid))
        if unit is not None and unit in self.units and not unit.is_dead:
            return unit
        for cand in self.units:
            if int(cand.uid) == int(uid) and not cand.is_dead:
                self._unit_by_uid[int(uid)] = cand
                return cand
        self._unit_by_uid.pop(int(uid), None)
        return None

    def _ship_from_sid(self, sid: int) -> Ship | None:
        ship = self._ship_by_sid.get(int(sid))
        if ship is not None and ship in self.ships:
            return ship
        for cand in self.ships:
            if int(cand.sid) == int(sid):
                self._ship_by_sid[int(sid)] = cand
                return cand
        self._ship_by_sid.pop(int(sid), None)
        return None

    def _net_send(self, msg: dict[str, object]) -> None:
        payload = dict(msg)
        payload.setdefault("protocol", protocol.PROTOCOL_VERSION)
        replay_types = {
            protocol.MSG_UNIT_MOVE,
            protocol.MSG_UNIT_GATHER,
            protocol.MSG_UNIT_ATTACK,
            protocol.MSG_BUILD,
            protocol.MSG_SHIP_MOVE,
            protocol.MSG_UNIT_STANCE,
            protocol.MSG_TECH_START,
            protocol.MSG_TECH_AGE,
        }
        if self.replay.is_recording and str(payload.get("type", "")) in replay_types:
            self.replay.record_message(self._sync_tick, payload)
        if not self._network_enabled or self.net is None or not self.net.connected:
            return
        self.net.send(payload)

    def _notify_network_exit(self) -> None:
        if not self._network_enabled or self.net is None:
            return
        if self._disconnect_sent:
            return
        self._disconnect_sent = True
        self._net_send(
            {
                "type": protocol.MSG_DISCONNECT,
                "civ": self.player_civilization,
                "player_id": int(self.player_id),
            }
        )

    def _net_send_unit_move(self, unit: Unit, wx: float, wy: float) -> None:
        tx, ty = self.tilemap.world_to_tile(wx, wy)
        self._net_send(
            {
                "type": protocol.MSG_UNIT_MOVE,
                "civ": unit.civilization,
                "unit_id": int(unit.uid),
                "tx": int(tx),
                "ty": int(ty),
            }
        )

    def _net_send_unit_gather(self, unit: Unit, node) -> None:
        self._net_send(
            {
                "type": protocol.MSG_UNIT_GATHER,
                "civ": unit.civilization,
                "unit_id": int(unit.uid),
                "resource": str(getattr(node, "resource_type", "")),
                "tx": int(getattr(node, "col", 0)),
                "ty": int(getattr(node, "row", 0)),
            }
        )

    def _net_send_unit_attack(self, attacker: Unit, target) -> None:
        msg: dict[str, object] = {
            "type": protocol.MSG_UNIT_ATTACK,
            "civ": attacker.civilization,
            "attacker": int(attacker.uid),
            "target_kind": "unit",
            "target_id": -1,
        }
        if isinstance(target, Unit):
            msg["target_kind"] = "unit"
            msg["target_id"] = int(target.uid)
        elif isinstance(target, Building):
            tx, ty = self.tilemap.world_to_tile(target.world_pos.x, target.world_pos.y)
            msg["target_kind"] = "building"
            msg["target_id"] = -1
            msg["tx"] = int(tx)
            msg["ty"] = int(ty)
        self._net_send(msg)

    def _net_send_unit_stance(self, units: list[Unit], stance: str) -> None:
        ids = [int(u.uid) for u in units if (not u.is_dead and u.civilization == self.player_civilization)]
        if not ids:
            return
        self._net_send(
            {
                "type": protocol.MSG_UNIT_STANCE,
                "civ": self.player_civilization,
                "stance": stance,
                "unit_ids": ids,
            }
        )

    def _net_send_tech_age(self, age: str) -> None:
        self._net_send(
            {
                "type": protocol.MSG_TECH_AGE,
                "civ": self.player_civilization,
                "age": age,
            }
        )

    def _net_send_build(self, building_type: str, anchor: tuple[int, int], civilization: str) -> None:
        self._net_send(
            {
                "type": protocol.MSG_BUILD,
                "civ": civilization,
                "building": building_type,
                "tx": int(anchor[0]),
                "ty": int(anchor[1]),
            }
        )

    def _net_send_spawn_unit(self, unit: Unit) -> None:
        tx, ty = self.tilemap.world_to_tile(unit.world_pos.x, unit.world_pos.y)
        self._net_send(
            {
                "type": protocol.MSG_SPAWN_UNIT,
                "civ": unit.civilization,
                "unit_type": unit.unit_class.title(),
                "unit_id": int(unit.uid),
                "tx": int(tx),
                "ty": int(ty),
            }
        )

    def _net_send_spawn_ship(self, ship: Ship) -> None:
        tx, ty = self.tilemap.world_to_tile(ship.world_pos.x, ship.world_pos.y)
        self._net_send(
            {
                "type": protocol.MSG_SPAWN_UNIT,
                "civ": ship.civilization,
                "unit_type": "Ship",
                "ship_id": int(ship.sid),
                "tx": int(tx),
                "ty": int(ty),
            }
        )

    def _net_send_ship_move(
        self,
        ship: Ship,
        wx: float,
        wy: float,
        *,
        unload_world: tuple[float, float] | None,
    ) -> None:
        tx, ty = self.tilemap.world_to_tile(wx, wy)
        msg: dict[str, object] = {
            "type": protocol.MSG_SHIP_MOVE,
            "civ": ship.civilization,
            "ship_id": int(ship.sid),
            "tx": int(tx),
            "ty": int(ty),
        }
        if unload_world is not None:
            utx, uty = self.tilemap.world_to_tile(unload_world[0], unload_world[1])
            msg["unload_tx"] = int(utx)
            msg["unload_ty"] = int(uty)
        self._net_send(msg)

    def _resource_node_at_tile(self, col: int, row: int, resource_type: str = ""):
        for node in self.resource_manager.nodes:
            if node.is_depleted:
                continue
            if node.col != col or node.row != row:
                continue
            if resource_type and node.resource_type != resource_type:
                continue
            return node
        return None

    def _building_at_tile(self, col: int, row: int, *, enemy_of: str | None = None) -> Building | None:
        for building in reversed(self.buildings):
            if building.is_dead:
                continue
            if enemy_of is not None and building.civilization == enemy_of:
                continue
            if (col, row) in building.footprint_tiles(self.tilemap):
                return building
        return None

    def _apply_remote_spawn_unit(self, msg: dict[str, object], *, allow_local_civ: bool = False) -> None:
        civ = str(msg.get("civ", ""))
        if not civ:
            return
        if not allow_local_civ and civ == self.player_civilization:
            return
        unit_type = str(msg.get("unit_type", "Worker")).lower()
        tx = int(msg.get("tx", 0))
        ty = int(msg.get("ty", 0))
        wx, wy = self.tilemap.tile_center(tx, ty)

        if unit_type == "ship":
            sid = int(msg.get("ship_id", 0))
            if sid > 0 and self._ship_from_sid(sid) is not None:
                return
            ship = Ship(wx, wy, civilization=civ)
            if sid > 0:
                ship.sid = sid
                Ship._sid_seq = max(int(Ship._sid_seq), sid)
            self.ships.append(ship)
            self._ship_by_sid[int(ship.sid)] = ship
            return

        uid = int(msg.get("unit_id", 0))
        if uid > 0 and self._unit_from_uid(uid) is not None:
            return
        unit = Unit(wx, wy, civilization=civ, unit_class=unit_type)
        if uid > 0:
            unit.uid = uid
            Unit._uid_seq = max(int(Unit._uid_seq), uid)
        self.units.append(unit)
        self._unit_by_uid[int(unit.uid)] = unit

    def _apply_command_message(self, msg: dict[str, object], *, allow_local_civ: bool = False) -> None:
        msg_type = str(msg.get("type", ""))
        civ = str(msg.get("civ", ""))
        if not msg_type or not civ:
            return
        if not allow_local_civ and civ == self.player_civilization:
            return

        if msg_type == protocol.MSG_UNIT_MOVE:
            unit = self._unit_from_uid(int(msg.get("unit_id", -1)))
            if unit is None or unit.civilization != civ:
                return
            tx = int(msg.get("tx", 0))
            ty = int(msg.get("ty", 0))
            wx, wy = self.tilemap.tile_center(tx, ty)
            self._worker_haul.pop(id(unit), None)
            unit.move_to(
                wx,
                wy,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            return

        if msg_type == protocol.MSG_UNIT_GATHER:
            unit = self._unit_from_uid(int(msg.get("unit_id", -1)))
            if unit is None or unit.civilization != civ:
                return
            tx = int(msg.get("tx", -1))
            ty = int(msg.get("ty", -1))
            resource = str(msg.get("resource", ""))
            node = self._resource_node_at_tile(tx, ty, resource)
            if node is None:
                return
            unit.gather(
                node,
                approach_pos=self.tilemap.tile_center(node.col, node.row),
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            return

        if msg_type == protocol.MSG_UNIT_ATTACK:
            attacker = self._unit_from_uid(int(msg.get("attacker", -1)))
            if attacker is None or attacker.civilization != civ:
                return
            target_kind = str(msg.get("target_kind", "unit"))
            target = None
            if target_kind == "building":
                tx = int(msg.get("tx", -1))
                ty = int(msg.get("ty", -1))
                target = self._building_at_tile(tx, ty, enemy_of=attacker.civilization)
            else:
                target = self._unit_from_uid(int(msg.get("target_id", -1)))
            if target is None:
                return
            attacker.attack_command(
                target,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            return

        if msg_type == protocol.MSG_UNIT_STANCE:
            stance = str(msg.get("stance", Unit.STANCE_AGGRESSIVE))
            raw_ids = msg.get("unit_ids", [])
            if not isinstance(raw_ids, list):
                return
            for raw_uid in raw_ids:
                unit = self._unit_from_uid(int(raw_uid))
                if unit is None or unit.civilization != civ:
                    continue
                unit.set_stance(stance)
            return

        if msg_type == protocol.MSG_TECH_START:
            if self.tech_tree.can_start_age_up(civ):
                self.tech_tree.start_age_up(civ)
            return

        if msg_type == protocol.MSG_TECH_AGE:
            age = str(msg.get("age", ""))
            if age:
                self._set_civilization_age(civ, age)
            return

        if msg_type == "produce":
            tx = int(msg.get("tx", -1))
            ty = int(msg.get("ty", -1))
            slot = int(msg.get("slot", -1))
            if slot < 0:
                return
            building = self._building_at_tile(tx, ty)
            if building is None or building.civilization != civ:
                return
            options = building.production_options()
            if 0 <= slot < len(options):
                if self.replay.is_playback and allow_local_civ:
                    building.enqueue_option(options[slot])
                    return
                self._queue_building_option(building, options[slot])
            return

        if msg_type == protocol.MSG_BUILD:
            tx = int(msg.get("tx", -1))
            ty = int(msg.get("ty", -1))
            building_type = str(msg.get("building", Building.TYPE_HOUSE1))
            self._place_building_at_anchor(
                (tx, ty),
                building_type,
                civilization=civ,
                spend_cost=False,
                selected_workers=[],
                auto_remote_builders=True,
                net_broadcast=False,
                select_new=False,
            )
            return

        if msg_type == protocol.MSG_SHIP_MOVE:
            ship = self._ship_from_sid(int(msg.get("ship_id", -1)))
            if ship is None or ship.civilization != civ:
                return
            tx = int(msg.get("tx", -1))
            ty = int(msg.get("ty", -1))
            wx, wy = self.tilemap.tile_center(tx, ty)
            ship.move_to(
                wx,
                wy,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            if "unload_tx" in msg and "unload_ty" in msg:
                uwx, uwy = self.tilemap.tile_center(int(msg.get("unload_tx", tx)), int(msg.get("unload_ty", ty)))
                ship.request_unload(uwx, uwy)
            return

        if msg_type == protocol.MSG_SPAWN_UNIT:
            self._apply_remote_spawn_unit(msg, allow_local_civ=allow_local_civ)

    def _process_network_messages(self) -> None:
        if not self._network_enabled or self.net is None:
            return
        if not self.net.connected:
            if not self._net_disconnect_notified:
                self._net_disconnect_notified = True
            if self.player_id == 1:
                self.running = False
            return

        for msg in self.net.poll():
            msg_type = str(msg.get("type", ""))
            if not msg_type:
                continue

            if msg_type == protocol.MSG_DISCONNECT:
                if self.player_id == 1:
                    self.running = False
                continue

            if msg_type == protocol.MSG_SYNC_TICK:
                try:
                    self._remote_sync_tick = max(self._remote_sync_tick, int(msg.get("tick", 0)))
                except Exception:
                    pass
                continue

            if msg_type == protocol.MSG_STATE_HASH:
                remote_hash = str(msg.get("hash", ""))
                if self.player_id == 0 and remote_hash:
                    local_hash = self._compute_state_hash()
                    if remote_hash != local_hash:
                        self._desync_alert_s = 4.0
                        self._desync_count += 1
                        self._net_send(
                            {
                                "type": protocol.MSG_STATE_SYNC,
                                "tick": int(self._sync_tick),
                                "state": self._serialize_sync_state(),
                            }
                        )
                continue

            if msg_type == protocol.MSG_STATE_SYNC:
                state = msg.get("state")
                if isinstance(state, dict):
                    self._apply_sync_state(state)
                    self._desync_alert_s = 3.2
                continue

            self._apply_command_message(msg, allow_local_civ=False)

    def _compute_state_hash(self) -> str:
        unit_blob = [
            (
                int(u.uid),
                u.civilization,
                u.unit_class,
                round(float(u.world_pos.x), 1),
                round(float(u.world_pos.y), 1),
                int(round(float(u.hp))),
                int(u.max_hp),
                1 if u.is_dead else 0,
            )
            for u in self.units
        ]
        unit_blob.sort(key=lambda x: x[0])

        build_blob = [
            (
                b.civilization,
                b.building_type,
                int(self.tilemap.world_to_tile(b.world_pos.x, b.world_pos.y)[0]),
                int(self.tilemap.world_to_tile(b.world_pos.x, b.world_pos.y)[1]),
                int(round(float(b.hp))),
                int(b.max_hp),
                round(float(b.build_progress), 3),
                1 if b.is_dead else 0,
            )
            for b in self.buildings
        ]
        build_blob.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

        ship_blob = [
            (
                int(s.sid),
                s.civilization,
                round(float(s.world_pos.x), 1),
                round(float(s.world_pos.y), 1),
                int(round(float(s.hp))),
                int(s.passenger_count),
            )
            for s in self.ships
        ]
        ship_blob.sort(key=lambda x: x[0])

        payload = f"{unit_blob}|{build_blob}|{ship_blob}|{self.tech_tree.serialize()}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def _serialize_sync_state(self) -> dict[str, object]:
        return {
            "units": [
                {
                    "uid": int(u.uid),
                    "civ": u.civilization,
                    "cls": u.unit_class,
                    "x": float(u.world_pos.x),
                    "y": float(u.world_pos.y),
                    "hp": float(u.hp),
                    "max_hp": int(u.max_hp),
                    "dead": bool(u.is_dead),
                    "stance": str(getattr(u, "stance", Unit.STANCE_AGGRESSIVE)),
                }
                for u in self.units
            ],
            "buildings": [
                {
                    "civ": b.civilization,
                    "type": b.building_type,
                    "x": float(b.world_pos.x),
                    "y": float(b.world_pos.y),
                    "hp": float(b.hp),
                    "max_hp": int(b.max_hp),
                    "progress": float(b.build_progress),
                    "dead": bool(b.is_dead),
                    "dock": bool(b.is_dock),
                    "garrison": int(b.garrisoned_archers),
                }
                for b in self.buildings
            ],
            "ships": [
                {
                    "sid": int(s.sid),
                    "civ": s.civilization,
                    "x": float(s.world_pos.x),
                    "y": float(s.world_pos.y),
                    "hp": float(s.hp),
                    "cargo": dict(s.cargo),
                }
                for s in self.ships
            ],
            "tech": self.tech_tree.serialize(),
        }

    def _apply_sync_state(self, payload: dict[str, object]) -> None:
        raw_units = payload.get("units", [])
        raw_buildings = payload.get("buildings", [])
        raw_ships = payload.get("ships", [])
        raw_tech = payload.get("tech", {})

        if isinstance(raw_tech, dict):
            self.tech_tree.apply_serialized(raw_tech)

        if isinstance(raw_units, list):
            keep_uids: set[int] = set()
            by_uid = {int(u.uid): u for u in self.units}
            for item in raw_units:
                if not isinstance(item, dict):
                    continue
                uid = int(item.get("uid", 0))
                if uid <= 0:
                    continue
                keep_uids.add(uid)
                civ = str(item.get("civ", "Blue"))
                cls = str(item.get("cls", Unit.ROLE_WORKER))
                x = float(item.get("x", 0.0))
                y = float(item.get("y", 0.0))
                hp = float(item.get("hp", 1.0))
                max_hp = max(1, int(item.get("max_hp", 1)))
                dead = bool(item.get("dead", False))
                stance = str(item.get("stance", Unit.STANCE_AGGRESSIVE))

                unit = by_uid.get(uid)
                if unit is None:
                    unit = Unit(x, y, civilization=civ, unit_class=cls)
                    unit.uid = uid
                    Unit._uid_seq = max(Unit._uid_seq, uid)
                    self.units.append(unit)
                    by_uid[uid] = unit
                unit.civilization = civ
                unit.unit_class = cls
                unit.world_pos.update(x, y)
                unit.max_hp = max_hp
                unit.hp = max(0.0, min(float(max_hp), hp))
                unit.is_dead = dead
                unit.set_stance(stance)
            self.units = [u for u in self.units if int(u.uid) in keep_uids]

        if isinstance(raw_buildings, list):
            def bkey(civ: str, btype: str, x: float, y: float) -> tuple[str, str, int, int]:
                tc, tr = self.tilemap.world_to_tile(x, y)
                return civ, btype, int(tc), int(tr)

            existing: dict[tuple[str, str, int, int], Building] = {}
            for b in self.buildings:
                key = bkey(b.civilization, b.building_type, b.world_pos.x, b.world_pos.y)
                existing[key] = b
            keep_keys: set[tuple[str, str, int, int]] = set()

            for item in raw_buildings:
                if not isinstance(item, dict):
                    continue
                civ = str(item.get("civ", "Blue"))
                btype = str(item.get("type", Building.TYPE_HOUSE1))
                x = float(item.get("x", 0.0))
                y = float(item.get("y", 0.0))
                key = bkey(civ, btype, x, y)
                keep_keys.add(key)
                b = existing.get(key)
                if b is None:
                    b = Building(
                        x,
                        y,
                        building_type=btype,
                        civilization=civ,
                        max_hp=max(1, int(item.get("max_hp", 1000))),
                        start_progress=float(item.get("progress", 1.0)),
                    )
                    self.buildings.append(b)
                    existing[key] = b
                b.world_pos.update(x, y)
                b.max_hp = max(1, int(item.get("max_hp", b.max_hp)))
                b.hp = max(0.0, min(float(b.max_hp), float(item.get("hp", b.hp))))
                b.build_progress = max(0.0, min(1.0, float(item.get("progress", b.build_progress))))
                b.is_dead = bool(item.get("dead", False))
                b.is_dock = bool(item.get("dock", b.is_dock))
                b.garrisoned_archers = max(0, int(item.get("garrison", b.garrisoned_archers)))
            self.buildings = [
                b
                for b in self.buildings
                if bkey(b.civilization, b.building_type, b.world_pos.x, b.world_pos.y) in keep_keys
            ]

        if isinstance(raw_ships, list):
            keep_sids: set[int] = set()
            existing = {int(s.sid): s for s in self.ships}
            for item in raw_ships:
                if not isinstance(item, dict):
                    continue
                sid = int(item.get("sid", 0))
                if sid <= 0:
                    continue
                keep_sids.add(sid)
                civ = str(item.get("civ", "Blue"))
                x = float(item.get("x", 0.0))
                y = float(item.get("y", 0.0))
                ship = existing.get(sid)
                if ship is None:
                    ship = Ship(x, y, civilization=civ)
                    ship.sid = sid
                    Ship._sid_seq = max(Ship._sid_seq, sid)
                    self.ships.append(ship)
                    existing[sid] = ship
                ship.civilization = civ
                ship.world_pos.update(x, y)
                ship.hp = max(1.0, float(item.get("hp", ship.hp)))
                cargo = item.get("cargo", {})
                if isinstance(cargo, dict):
                    ship.cargo = {k: int(v) for k, v in cargo.items() if k in ("gold", "wood", "stone")}
            self.ships = [s for s in self.ships if int(s.sid) in keep_sids]

        self._deselect_all()
        self._selected_enemy_unit = None
        self._selected_node = None
        self._clear_building_selection()
        self._refresh_building_masks()
        self._reindex_units()
        self._reindex_ships()
        self._update_storage_capacity()
        self._sync_civilizations()

    def _set_civilization_age(self, civ: str, age: str) -> None:
        if age not in AGE_ORDER:
            return
        st = self.tech_tree.state(civ)
        st.age_index = AGE_ORDER.index(age)
        st.researching_target = None
        st.researching_remaining_s = 0.0
        st.researching_total_s = 0.0
        for unit in self.units:
            if unit.civilization == civ:
                self._apply_unit_age_bonus(unit)

    def _apply_unit_age_bonus(self, unit: Unit) -> None:
        scale = self.tech_tree.age_multiplier(unit.civilization)
        unit.apply_combat_scale(scale)

    def _try_age_up_player(self) -> bool:
        if not self.tech_tree.can_start_age_up(self.player_civilization):
            return False
        costs = self.tech_tree.next_age_cost(self.player_civilization)
        if not costs or not self.resource_manager.can_afford(costs):
            return False
        self.resource_manager.spend(costs)
        ok = self.tech_tree.start_age_up(self.player_civilization)
        if ok:
            self._net_send(
                {
                    "type": protocol.MSG_TECH_START,
                    "civ": self.player_civilization,
                }
            )
        return ok

    def _update_ai_age_up(self, dt: float) -> None:
        if not self.ai_controllers:
            return
        self._ai_age_timer_s -= dt
        if self._ai_age_timer_s > 0.0:
            return
        self._ai_age_timer_s = 1.2
        for civ, ctrl in self._ai_by_civ.items():
            if not self.tech_tree.can_start_age_up(civ):
                continue
            costs = self.tech_tree.next_age_cost(civ)
            if not costs:
                continue
            can = True
            for key, val in costs.items():
                if ctrl.resources.get(key, 0) < int(val):
                    can = False
                    break
            if not can:
                continue
            for key, val in costs.items():
                ctrl.resources[key] = max(0, ctrl.resources.get(key, 0) - int(val))
            self.tech_tree.start_age_up(civ)

    def _network_tick_update(self, dt: float) -> None:
        self._sync_tick += 1
        if not self._network_enabled:
            return

        self._state_hash_timer_s -= dt
        if self._state_hash_timer_s <= 0.0:
            self._state_hash_timer_s = 0.9
            self._net_send(
                {
                    "type": protocol.MSG_STATE_HASH,
                    "tick": int(self._sync_tick),
                    "hash": self._compute_state_hash(),
                    "civ": self.player_civilization,
                }
            )

        if self.player_id != 0:
            return
        self._sync_tick_send_timer_s -= dt
        if self._sync_tick_send_timer_s <= 0.0:
            self._sync_tick_send_timer_s = 0.45
            self._net_send({"type": protocol.MSG_SYNC_TICK, "tick": int(self._sync_tick)})

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self) -> None:
        try:
            while self.running:
                dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
                keys = pygame.key.get_pressed()
                self._handle_events(keys)
                self._update(dt, keys)
                self._draw()
        finally:
            self._notify_network_exit()
            self.replay.close()

    # ── Events ────────────────────────────────────────────────────────────────
    def _handle_events(self, keys) -> None:
        for event in pygame.event.get():
            if event.type in (
                pygame.KEYDOWN,
                pygame.MOUSEBUTTONDOWN,
                pygame.MOUSEBUTTONUP,
                pygame.MOUSEWHEEL,
            ):
                self._mark_activity()

            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F11 or (
                    event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
                    and (event.mod & pygame.KMOD_ALT)
                ):
                    self.screen = toggle_fullscreen()
                    continue
                if self.game_result is not None:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    continue
                if self.replay.is_playback:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    continue
                if event.key == pygame.K_ESCAPE:
                    if self._build_mode_type is not None:
                        self._build_mode_type = None
                    else:
                        self.running = False
                elif event.key == pygame.K_g:
                    self.show_grid = not self.show_grid
                elif event.key == pygame.K_b:
                    self._build_mode_type = None if self._build_mode_type else Building.TYPE_HOUSE1
                elif event.key == pygame.K_TAB:
                    self._build_palette_collapsed = not self._build_palette_collapsed
                    if self._build_palette_collapsed:
                        self._build_mode_type = None
                elif event.key == pygame.K_a and (event.mod & pygame.KMOD_CTRL):
                    self._select_all()
                elif event.key == pygame.K_SPACE:
                    self._focus_army()
                elif event.key == pygame.K_F1:
                    self._hud_pinned = not self._hud_pinned
                    self._mark_activity()
                elif event.key == pygame.K_F2:
                    self._set_selected_stance(Unit.STANCE_AGGRESSIVE)
                elif event.key == pygame.K_F3:
                    self._set_selected_stance(Unit.STANCE_DEFENSIVE)
                elif event.key == pygame.K_F4:
                    self._set_selected_stance(Unit.STANCE_HOLD)
                elif event.key == pygame.K_F5:
                    self._formation_mode_idx = (self._formation_mode_idx + 1) % len(self._formation_modes)
                    self._mark_activity()
                elif event.key == pygame.K_h:
                    self._try_age_up_player()
                elif event.key in (pygame.K_1, pygame.K_KP1):
                    self._command_gather_type("gold")
                elif event.key in (pygame.K_2, pygame.K_KP2):
                    self._command_gather_type("stone")
                elif event.key in (pygame.K_3, pygame.K_KP3):
                    self._command_gather_type("wood")
                elif event.key in (pygame.K_4, pygame.K_KP4):
                    self._command_gather_type("meat")
                elif event.key in (pygame.K_5, pygame.K_KP5):
                    self._command_gather_type("food")
                elif event.key == pygame.K_q:
                    self._queue_selected_building_slot(0)
                elif event.key == pygame.K_w:
                    self._queue_selected_building_slot(1)
                elif event.key == pygame.K_e:
                    self._queue_selected_building_slot(2)
                elif event.key == pygame.K_r:
                    self._queue_selected_building_slot(3)
                elif event.key == pygame.K_u:
                    self._ungarrison_selected_tower()

            self.camera.handle_event(event)

            if event.type == pygame.MOUSEBUTTONDOWN:
                if self.replay.is_playback:
                    continue
                if event.button == 1:
                    self._on_left_down(event.pos, keys)
                elif event.button == 3:
                    self._on_right_click(event.pos)

            elif event.type == pygame.MOUSEBUTTONUP:
                if self.replay.is_playback:
                    continue
                if event.button == 1:
                    self._on_left_up(event.pos)

    def _on_left_down(self, pos, keys) -> None:
        if self.game_result is not None:
            return
        if self._handle_build_palette_click(pos):
            return
        if self._handle_building_ui_click(pos):
            return

        if self._build_mode_type is not None:
            self._attempt_place_building(pos)
            return

        wx, wy = self.camera.screen_to_world(pos)
        shift = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]

        hit_building = next((b for b in reversed(self.buildings) if b.contains_point(wx, wy)), None)
        if hit_building is not None:
            if hit_building.civilization != self.player_civilization:
                self._selected_enemy_unit = None
                self._selected_node = None
                self._clear_building_selection()
                return
            self._deselect_ships()
            self._selected_enemy_unit = None
            self._select_building(hit_building)
            self.sound.play("select")
            return

        hit_ship = next((s for s in reversed(self.ships) if s.contains_point(wx, wy)), None)
        if hit_ship is not None:
            if hit_ship.civilization != self.player_civilization:
                return
            if not shift:
                self._deselect_all()
            else:
                self._deselect_units_only()
            self._select_ship(hit_ship)
            self._selected_enemy_unit = None
            self._clear_building_selection()
            self._selected_node = None
            self.sound.play("select")
            return

        hit_unit = next((u for u in self.units if u.contains_point(wx, wy)), None)
        if hit_unit is not None:
            if hit_unit.is_dead:
                return
            if hit_unit.civilization != self.player_civilization:
                self._selected_enemy_unit = hit_unit
                self._selected_node = None
                self._clear_building_selection()
                return
            if not shift:
                self._deselect_all()
            self._select(hit_unit)
            self._deselect_ships()
            self._selected_enemy_unit = None
            self._clear_building_selection()
            self._selected_node = None
            self.sound.play("select")
            return

        hit_node = self.resource_manager.node_at_world(wx, wy)
        if hit_node is not None:
            self._deselect_ships()
            self._clear_building_selection()
            self._selected_node = hit_node
            self._selected_enemy_unit = None
            return

        self._selected_node = None
        self._selected_enemy_unit = None
        self._clear_building_selection()
        if not shift:
            self._deselect_all()
        self._box_start = pos

    def _on_left_up(self, pos) -> None:
        if self.game_result is not None:
            return
        if self._box_start is None or self._build_mode_type is not None:
            return
        x0, y0 = self._box_start
        x1, y1 = pos
        rect = pygame.Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        if rect.width > 4 and rect.height > 4:
            for unit in self.units:
                sx, sy = self.camera.world_to_screen(unit.world_pos)
                if rect.collidepoint(sx, sy):
                    self._select(unit)
        self._box_start = None

    def _on_right_click(self, pos) -> None:
        if self.game_result is not None:
            return
        if self._build_mode_type is not None:
            self._build_mode_type = None
            return

        wx, wy = self.camera.screen_to_world(pos)

        if self._selected_ships:
            self._issue_ship_command(wx, wy)
            return

        if not self._selected:
            return

        ship_target = next(
            (
                ship
                for ship in reversed(self.ships)
                if ship.civilization == self.player_civilization and ship.contains_point(wx, wy)
            ),
            None,
        )
        if ship_target is not None and self._try_board_selected_units(ship_target):
            return

        enemy_target = self._enemy_unit_at_world(wx, wy)
        if enemy_target is not None:
            self._issue_attack(enemy_target)
            return

        enemy_building = self._enemy_building_at_world(wx, wy)
        if enemy_building is not None:
            self._issue_attack(enemy_building)
            return
        self._selected_enemy_unit = None

        build_site = next(
            (
                b
                for b in reversed(self.buildings)
                if b.under_construction and b.civilization == self.player_civilization and b.contains_point(wx, wy)
            ),
            None,
        )
        if build_site is not None:
            workers = [u for u in self._selected if u.can_construct]
            if workers:
                self._issue_construction(build_site, workers)
                return

        tower = next(
            (
                b
                for b in reversed(self.buildings)
                if b.can_garrison_archers and b.contains_point(wx, wy)
            ),
            None,
        )
        if tower is not None and self._try_garrison_archers(tower):
            return

        resource_node = self.resource_manager.node_at_world(wx, wy)
        if resource_node is not None:
            self._issue_gather(resource_node)
            return

        self._selected_node = None
        n = len(self._selected)
        if n == 1:
            self._worker_haul.pop(id(self._selected[0]), None)
            self._selected[0].move_to(
                wx,
                wy,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            self._net_send_unit_move(self._selected[0], wx, wy)
            self.sound.play("move")
            return

        spacing = max(56, Unit.DISPLAY_SIZE * 0.86)
        offsets = self._formation_offsets(n, spacing)
        for i, unit in enumerate(self._selected):
            self._worker_haul.pop(id(unit), None)
            off_x, off_y = offsets[i]
            unit.move_to(
                wx + off_x,
                wy + off_y,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            self._net_send_unit_move(unit, wx + off_x, wy + off_y)
        self.sound.play("move")

    def _issue_ship_command(self, wx: float, wy: float) -> None:
        if not self._selected_ships:
            return
        tc, tr = self.tilemap.world_to_tile(wx, wy)
        on_water = self.tilemap.get_tile(tc, tr) == TILE_WATER
        ships = [ship for ship in self._selected_ships if ship.civilization == self.player_civilization]
        if not ships:
            return

        cols = max(1, round(len(ships) ** 0.5))
        spacing = TILE_SIZE * 1.45
        anchor = (wx, wy)
        if not on_water:
            water_anchor = self._nearest_water_world(wx, wy, max_radius=18)
            if water_anchor is not None:
                anchor = water_anchor

        for i, ship in enumerate(ships):
            col = i % cols
            row = i // cols
            off_x = (col - (cols - 1) / 2) * spacing
            off_y = row * spacing * 0.72
            dest_wx = anchor[0] + off_x
            dest_wy = anchor[1] + off_y
            ship.move_to(
                dest_wx,
                dest_wy,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            unload_target: tuple[float, float] | None = None
            if not on_water:
                ship.request_unload(wx, wy)
                unload_target = (wx, wy)
            self._net_send_ship_move(ship, dest_wx, dest_wy, unload_world=unload_target)
        self.sound.play("move")

    def _nearest_water_world(
        self,
        wx: float,
        wy: float,
        *,
        max_radius: int = 12,
    ) -> tuple[float, float] | None:
        tc, tr = self.tilemap.world_to_tile(wx, wy)
        if self.tilemap.get_tile(tc, tr) == TILE_WATER:
            return self.tilemap.tile_center(tc, tr)

        for radius in range(1, max_radius + 1):
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if abs(dc) != radius and abs(dr) != radius:
                        continue
                    c = tc + dc
                    r = tr + dr
                    if not (0 <= c < self.tilemap.cols and 0 <= r < self.tilemap.rows):
                        continue
                    if self.tilemap.get_tile(c, r) == TILE_WATER:
                        return self.tilemap.tile_center(c, r)
        return None

    def _try_board_selected_units(self, ship: Ship) -> bool:
        if not self._selected:
            return False
        boarded_any = False
        for unit in self._selected:
            if unit.is_dead or unit.civilization != self.player_civilization:
                continue
            if ship.request_board(
                unit,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            ):
                boarded_any = True
        return boarded_any

    # ── Build placement ───────────────────────────────────────────────────────
    def _has_selected_worker(self) -> bool:
        return any(
            unit.can_construct and unit.civilization == self.player_civilization and not unit.is_dead
            for unit in self._selected
        )

    def _handle_build_palette_click(self, pos) -> bool:
        if self._build_palette_toggle_rect.collidepoint(pos):
            self._build_palette_collapsed = not self._build_palette_collapsed
            if self._build_palette_collapsed:
                self._build_mode_type = None
            self._mark_activity()
            return True
        if self._build_palette_collapsed:
            return False
        if not self._build_palette_buttons:
            return False
        for rect, btype in self._build_palette_buttons:
            if rect.collidepoint(pos):
                if not self._has_selected_worker():
                    self.sound.play("error")
                    return True
                self._build_mode_type = btype
                self._mark_activity()
                return True
        return False

    def _attempt_place_building(self, screen_pos) -> bool:
        if self._build_mode_type is None:
            return False
        if not self._has_selected_worker():
            self.sound.play("error")
            return False

        wx, wy = self.camera.screen_to_world(screen_pos)
        anchor = self.tilemap.world_to_tile(wx, wy)
        workers = [u for u in self._selected if u.can_construct]
        placed = self._place_building_at_anchor(
            anchor,
            self._build_mode_type,
            civilization=self.player_civilization,
            spend_cost=True,
            selected_workers=workers,
            auto_remote_builders=False,
            net_broadcast=True,
            select_new=True,
        )
        if placed is None:
            self.sound.play("error")
            return False
        self.sound.play("build")
        return True

    def _place_building_at_anchor(
        self,
        anchor: tuple[int, int],
        building_type: str,
        *,
        civilization: str,
        spend_cost: bool,
        selected_workers: list[Unit] | None,
        auto_remote_builders: bool,
        net_broadcast: bool,
        select_new: bool,
    ) -> Building | None:
        footprint = self._candidate_footprint(anchor, building_type)
        if not self._is_placement_valid(footprint):
            return None
        if spend_cost:
            costs = Building.build_cost(building_type)
            if not self.resource_manager.spend(costs):
                return None

        bx, by = self.tilemap.tile_center(anchor[0], anchor[1])
        b = Building(
            bx,
            by,
            building_type=building_type,
            civilization=civilization,
            max_hp=self._max_hp_for_building(building_type),
            start_progress=0.05,
        )
        if b.building_type == Building.TYPE_TOWER:
            b.is_dock = self._building_touches_water(footprint)
        self.buildings.append(b)
        self._refresh_building_masks()
        self._update_storage_capacity()

        workers = list(selected_workers or [])
        if auto_remote_builders and not workers:
            workers = sorted(
                [
                    u
                    for u in self.units
                    if (
                        u.civilization == civilization
                        and u.can_construct
                        and not u.is_dead
                    )
                ],
                key=lambda u: (u.world_pos.x - b.world_pos.x) ** 2 + (u.world_pos.y - b.world_pos.y) ** 2,
            )[:3]
        if workers:
            self._issue_construction(b, workers)

        if civilization == self.player_civilization:
            self._selected_node = None
            self._selected_enemy_unit = None
            if select_new:
                self._select_building(b)
        if net_broadcast:
            self._net_send_build(building_type, anchor, civilization)
        return b

    def _max_hp_for_building(self, building_type: str) -> int:
        mapping = {
            Building.TYPE_CASTLE: 2600,
            Building.TYPE_BARRACKS: 1900,
            Building.TYPE_ARCHERY: 1800,
            Building.TYPE_SMITHY: 1750,
            Building.TYPE_HOUSE1: 1200,
            Building.TYPE_HOUSE2: 1200,
            Building.TYPE_HOUSE3: 1200,
            Building.TYPE_TOWER: 1650,
        }
        return mapping.get(building_type, 1400)

    def _candidate_footprint(
        self,
        anchor_tile: tuple[int, int],
        building_type: str,
    ) -> set[tuple[int, int]]:
        fw, fh = Building.footprint_size(building_type)
        ac, ar = anchor_tile
        start_col = ac - fw // 2
        start_row = ar - fh + 1
        out: set[tuple[int, int]] = set()
        for row in range(start_row, start_row + fh):
            for col in range(start_col, start_col + fw):
                out.add((col, row))
        return out

    def _is_placement_valid(self, footprint: set[tuple[int, int]]) -> bool:
        if not footprint:
            return False
        if footprint & self._building_blocked_tiles:
            return False
        if self.resource_manager is not None:
            if footprint & self.resource_manager.occupied_tiles(include_depleted=False):
                return False

        for col, row in footprint:
            if not (0 <= col < self.tilemap.cols and 0 <= row < self.tilemap.rows):
                return False
            if not self.tilemap.is_walkable(col, row):
                return False
            tile = self.tilemap.get_tile(col, row)
            if tile not in (TILE_GRASS, TILE_DIRT):
                return False
        return True

    # ── Resource / command helpers ────────────────────────────────────────────
    def _enemy_unit_at_world(self, wx: float, wy: float) -> Unit | None:
        friend = next((u for u in self._selected if not u.is_dead), None)
        if friend is None:
            return None
        best = None
        best_d2 = 10e12
        for unit in self.units:
            if unit.is_dead:
                continue
            if not friend.is_hostile_to(unit):
                continue
            if not unit.contains_point(wx, wy):
                continue
            dx = wx - unit.world_pos.x
            dy = wy - unit.world_pos.y
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best = unit
                best_d2 = d2
        return best

    def _enemy_building_at_world(self, wx: float, wy: float) -> Building | None:
        friend = next((u for u in self._selected if not u.is_dead), None)
        if friend is None:
            return None
        for building in reversed(self.buildings):
            if building.is_dead or building.civilization == friend.civilization:
                continue
            if building.contains_point(wx, wy):
                return building
        return None

    def _issue_attack(self, target) -> None:
        attackers = [
            u
            for u in self._selected
            if (not u.is_dead and u.can_attack and u.civilization == self.player_civilization)
        ]
        if not attackers:
            return
        self._selected_enemy_unit = target if isinstance(target, Unit) else None
        self._selected_node = None

        for unit in attackers:
            unit.attack_command(
                target,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            self._net_send_unit_attack(unit, target)
        self.sound.play("attack")

    def _set_selected_stance(self, stance: str) -> None:
        units = [
            u
            for u in self._selected
            if (not u.is_dead and u.civilization == self.player_civilization and u.can_attack)
        ]
        if not units:
            return
        for unit in units:
            unit.set_stance(stance)
        self._net_send_unit_stance(units, stance)

    def _formation_mode(self) -> str:
        if not self._formation_modes:
            return "box"
        idx = max(0, min(len(self._formation_modes) - 1, int(self._formation_mode_idx)))
        return self._formation_modes[idx]

    def _formation_offsets(self, count: int, spacing: float) -> list[tuple[float, float]]:
        n = max(1, int(count))
        sp = max(26.0, float(spacing))
        mode = self._formation_mode()
        out: list[tuple[float, float]] = []

        if mode == "line":
            for i in range(n):
                off_x = (i - (n - 1) / 2) * sp
                out.append((off_x, 0.0))
            return out

        if mode == "wedge":
            row = 0
            placed = 0
            while placed < n:
                width = 1 + row * 2
                for i in range(width):
                    if placed >= n:
                        break
                    off_x = (i - (width - 1) / 2) * sp * 0.85
                    off_y = row * sp * 0.78
                    out.append((off_x, off_y))
                    placed += 1
                row += 1
            center_y = sum(v[1] for v in out) / len(out)
            return [(ox, oy - center_y) for ox, oy in out]

        cols = max(1, round(n ** 0.5))
        rows = max(1, (n + cols - 1) // cols)
        for i in range(n):
            col = i % cols
            row = i // cols
            off_x = (col - (cols - 1) / 2) * sp
            off_y = (row - (rows - 1) / 2) * sp
            out.append((off_x, off_y))
        return out

    def _construction_positions(self, building: Building) -> list[tuple[float, float]]:
        footprint = building.footprint_tiles(self.tilemap)
        if not footprint:
            return [building.spawn_anchor()]

        candidates: set[tuple[int, int]] = set()
        dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
        for c, r in footprint:
            for dc, dr in dirs:
                nc, nr = c + dc, r + dr
                if (nc, nr) in footprint:
                    continue
                if not (0 <= nc < self.tilemap.cols and 0 <= nr < self.tilemap.rows):
                    continue
                if (nc, nr) in self._building_blocked_tiles:
                    continue
                if not self.tilemap.is_walkable(nc, nr):
                    continue
                candidates.add((nc, nr))

        if not candidates:
            return [building.spawn_anchor()]
        ordered = sorted(candidates)
        return [self.tilemap.tile_center(c, r) for c, r in ordered]

    def _issue_construction(self, building: Building, workers: list[Unit]) -> None:
        if building.is_complete:
            return
        workers = [
            w
            for w in workers
            if (w.can_construct and not w.is_dead and w.civilization == building.civilization)
        ]
        if not workers:
            return
        points = self._construction_positions(building)
        for i, worker in enumerate(workers):
            self._worker_haul.pop(id(worker), None)
            px, py = points[i % len(points)]
            worker.construct(
                building,
                approach_pos=(px, py),
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )

    def _issue_gather(self, resource_node) -> None:
        workers = [
            unit
            for unit in self._selected
            if unit.can_gather and unit.civilization == self.player_civilization and not unit.is_dead
        ]
        n = len(workers)
        if n <= 0:
            return
        self._selected_node = resource_node
        cx, cy = self.tilemap.tile_center(resource_node.col, resource_node.row)
        node_orbit = TILE_SIZE * (0.42 if resource_node.resource_type == "wood" else 0.72)

        if n == 1:
            self._worker_haul.pop(id(workers[0]), None)
            workers[0].gather(
                resource_node,
                approach_pos=(cx, cy),
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            self._net_send_unit_gather(workers[0], resource_node)
            self.sound.play("move")
            return

        orbit = max(10.0, min(Unit.GATHER_RANGE - 8.0, node_orbit))
        for i, unit in enumerate(workers):
            self._worker_haul.pop(id(unit), None)
            angle = (i / n) * math.tau
            ax = cx + math.cos(angle) * orbit
            ay = cy + math.sin(angle) * (orbit * 0.7)
            unit.gather(
                resource_node,
                approach_pos=(ax, ay),
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )
            self._net_send_unit_gather(unit, resource_node)
        self.sound.play("move")

    def _command_gather_type(self, resource_type: str) -> None:
        workers = [
            unit
            for unit in self._selected
            if unit.can_gather and unit.civilization == self.player_civilization and not unit.is_dead
        ]
        if not workers:
            self.sound.play("error")
            return

        target = None
        if (
            self._selected_node is not None
            and not self._selected_node.is_depleted
            and self._selected_node.resource_type == resource_type
        ):
            target = self._selected_node
        else:
            cx = sum(unit.world_pos.x for unit in workers) / len(workers)
            cy = sum(unit.world_pos.y for unit in workers) / len(workers)
            target = self.resource_manager.nearest_node(resource_type, cx, cy)
        if target is None:
            self.sound.play("error")
            return
        self._issue_gather(target)

    def _nearest_friendly_castle(self, civilization: str, wx: float, wy: float) -> Building | None:
        castles = [
            b
            for b in self.buildings
            if (
                b.civilization == civilization
                and b.building_type == Building.TYPE_CASTLE
                and not b.is_dead
                and b.is_complete
            )
        ]
        if not castles:
            return None
        return min(
            castles,
            key=lambda b: (b.world_pos.x - wx) ** 2 + (b.world_pos.y - wy) ** 2,
        )

    def _choose_deposit_target(self, unit: Unit, resource_type: str) -> tuple[str, object, float, float] | None:
        castle = self._nearest_friendly_castle(unit.civilization, unit.world_pos.x, unit.world_pos.y)
        if castle is not None:
            anchor = castle.spawn_anchor()
            path = self.pathfinder.find_path_world(
                (unit.world_pos.x, unit.world_pos.y),
                anchor,
                blocked=self._building_blocked_tiles,
            )
            if path:
                return ("castle", castle, anchor[0], anchor[1])

        if resource_type in ("gold", "wood", "stone"):
            ships = [
                s
                for s in self.ships
                if s.civilization == unit.civilization and s.has_cargo_space()
            ]
            if ships:
                ship = min(
                    ships,
                    key=lambda s: (s.world_pos.x - unit.world_pos.x) ** 2 + (s.world_pos.y - unit.world_pos.y) ** 2,
                )
                return ("ship", ship, ship.world_pos.x, ship.world_pos.y)
        return None

    def _handle_worker_gather_event(self, unit: Unit, node, amount: int) -> None:
        taken = self.resource_manager.drain_node(node, amount)
        if taken <= 0:
            return
        target = self._choose_deposit_target(unit, node.resource_type)
        if target is None:
            gained = self.resource_manager.gain(node.resource_type, taken)
            if unit.civilization == self.player_civilization and gained > 0:
                self.tutorial.add_collected(gained)
                if node.resource_type == "gold":
                    self.sound.play("gold")
            return

        kind, depot, wx, wy = target
        unit.stop_gathering()
        unit.move_to(
            wx,
            wy,
            pathfinder=self.pathfinder,
            blocked_tiles=self._building_blocked_tiles,
        )
        self._worker_haul[id(unit)] = {
            "unit": unit,
            "resource_type": node.resource_type,
            "amount": int(taken),
            "node": node,
            "depot_kind": kind,
            "depot": depot,
        }

    def _update_worker_haul(self) -> None:
        if not self._worker_haul:
            return
        done_ids: list[int] = []
        for uid, payload in self._worker_haul.items():
            unit = payload.get("unit")
            if not isinstance(unit, Unit) or unit.is_dead or unit not in self.units:
                done_ids.append(uid)
                continue
            depot = payload.get("depot")
            depot_kind = str(payload.get("depot_kind", "castle"))
            amount = int(payload.get("amount", 0))
            resource_type = str(payload.get("resource_type", "wood"))
            if amount <= 0:
                done_ids.append(uid)
                continue

            if depot_kind == "castle":
                if not isinstance(depot, Building) or depot.is_dead:
                    self.resource_manager.gain(resource_type, amount)
                    done_ids.append(uid)
                    continue
                tx, ty = depot.spawn_anchor()
            else:
                if not isinstance(depot, Ship):
                    self.resource_manager.gain(resource_type, amount)
                    done_ids.append(uid)
                    continue
                tx, ty = depot.world_pos.x, depot.world_pos.y

            dx = tx - unit.world_pos.x
            dy = ty - unit.world_pos.y
            if dx * dx + dy * dy > (TILE_SIZE * 0.92) ** 2:
                continue

            gained = 0
            if depot_kind == "ship" and isinstance(depot, Ship):
                stored = depot.store_resource(resource_type, amount)
                gained = self.resource_manager.gain(resource_type, stored)
            else:
                gained = self.resource_manager.gain(resource_type, amount)
            if unit.civilization == self.player_civilization and gained > 0:
                self.tutorial.add_collected(gained)
                if resource_type == "gold":
                    self.sound.play("gold")

            node = payload.get("node")
            if node is not None and not node.is_depleted and unit.can_gather:
                cx, cy = self.tilemap.tile_center(node.col, node.row)
                unit.gather(
                    node,
                    approach_pos=(cx, cy),
                    pathfinder=self.pathfinder,
                    blocked_tiles=self._building_blocked_tiles,
                )
            else:
                unit.stop_gathering()
            if gained >= 0:
                done_ids.append(uid)

        for uid in done_ids:
            self._worker_haul.pop(uid, None)

    # ── Building production / tools ───────────────────────────────────────────
    def _handle_building_ui_click(self, pos) -> bool:
        if not self._building_ui_buttons:
            return False
        if self._selected_building is None or not self._selected_building.can_produce:
            return False
        for rect, option in self._building_ui_buttons:
            if rect.collidepoint(pos):
                self._queue_building_option(self._selected_building, option)
                return True
        return False

    def _queue_selected_building_slot(self, index: int) -> None:
        building = self._selected_building
        if building is None or not building.can_produce:
            return
        options = building.production_options()
        if not (0 <= index < len(options)):
            return
        self._queue_building_option(building, options[index])

    @staticmethod
    def _option_slot_index(building: Building, option: dict[str, str | float | int]) -> int:
        options = building.production_options()
        key = (
            str(option.get("kind", "")),
            str(option.get("unit_class", "")),
            str(option.get("tool_id", "")),
            str(option.get("label", "")),
        )
        for i, cand in enumerate(options):
            ckey = (
                str(cand.get("kind", "")),
                str(cand.get("unit_class", "")),
                str(cand.get("tool_id", "")),
                str(cand.get("label", "")),
            )
            if ckey == key:
                return i
        return -1

    def _queue_building_option(
        self,
        building: Building,
        option: dict[str, str | float | int],
    ) -> bool:
        required_age = str(option.get("required_age", "dark"))
        if required_age in AGE_ORDER:
            civ_age = self.tech_tree.age(building.civilization)
            if AGE_ORDER.index(civ_age) < AGE_ORDER.index(required_age):
                if building.civilization == self.player_civilization:
                    self.sound.play("error")
                return False

        kind = str(option.get("kind", "unit"))
        if kind == "tool":
            tool_id = str(option.get("tool_id", ""))
            if self._tool_unlocked.get(tool_id, False):
                if building.civilization == self.player_civilization:
                    self.sound.play("error")
                return False
            if any(str(item.get("tool_id", "")) == tool_id for item in building.queue):
                if building.civilization == self.player_civilization:
                    self.sound.play("error")
                return False

        costs = {
            "gold": int(option.get("gold_cost", 0)),
            "wood": int(option.get("wood_cost", 0)),
            "stone": int(option.get("stone_cost", 0)),
        }
        if not self.resource_manager.can_afford(costs):
            if building.civilization == self.player_civilization:
                self.sound.play("error")
            return False
        ok = building.enqueue_option(option)
        if not ok:
            if building.civilization == self.player_civilization:
                self.sound.play("error")
            return False
        self.resource_manager.spend(costs)
        if self.replay.is_recording and building.civilization == self.player_civilization:
            tx, ty = self.tilemap.world_to_tile(building.world_pos.x, building.world_pos.y)
            slot = self._option_slot_index(building, option)
            if slot >= 0:
                self.replay.record_message(
                    self._sync_tick,
                    {
                        "type": "produce",
                        "civ": building.civilization,
                        "tx": int(tx),
                        "ty": int(ty),
                        "slot": int(slot),
                    },
                )
        return True

    def _update_buildings(self, dt: float) -> None:
        for building in self.buildings:
            if building.is_dead:
                continue
            if self._network_enabled and building.civilization != self.player_civilization:
                continue
            done = building.update(dt)
            for event in done:
                kind = str(event.get("kind", "unit"))
                if kind == "tool":
                    if building.civilization == self.player_civilization:
                        self._apply_tool_upgrade(str(event.get("tool_id", "")))
                elif kind == "unit":
                    self._spawn_unit_from_building(building, str(event.get("unit_class", "worker")))
                elif kind == "ship":
                    self._spawn_ship_from_building(building)

    def _apply_tool_upgrade(self, tool_id: str) -> None:
        if not tool_id or self._tool_unlocked.get(tool_id, False):
            return
        self._tool_unlocked[tool_id] = True

        if tool_id == "tool_01":
            self.resource_manager.set_gather_bonus("wood", 1.28)
        elif tool_id == "tool_02":
            self.resource_manager.set_gather_bonus("stone", 1.24)
        elif tool_id == "tool_03":
            self._soldier_hunger_drain_mult = 0.78
        elif tool_id == "tool_04":
            self.resource_manager.set_gather_bonus("gold", 1.30)

    def _spawn_unit_from_building(self, building: Building, unit_class: str) -> None:
        ax, ay = building.spawn_anchor()
        spawn_wx, spawn_wy = self._find_spawn_world_near(ax, ay)
        unit = Unit(
            spawn_wx,
            spawn_wy,
            civilization=building.civilization,
            unit_class=unit_class,
        )
        self._apply_unit_age_bonus(unit)
        self.units.append(unit)
        self._unit_by_uid[int(unit.uid)] = unit
        if building.civilization == self.player_civilization:
            self.sound.play("train")
        if self._network_enabled and building.civilization == self.player_civilization:
            self._net_send_spawn_unit(unit)

    def _spawn_ship_from_building(self, building: Building) -> None:
        if not building.is_dock:
            return
        water = self._nearest_water_world(building.world_pos.x, building.world_pos.y, max_radius=7)
        if water is None:
            return
        ship = Ship(water[0], water[1], civilization=building.civilization)
        self.ships.append(ship)
        self._ship_by_sid[int(ship.sid)] = ship
        if building.civilization == self.player_civilization:
            self.sound.play("train")
        if self._network_enabled and building.civilization == self.player_civilization:
            self._net_send_spawn_ship(ship)

    def _find_spawn_world_near(
        self,
        wx: float,
        wy: float,
        *,
        walkable_fn=None,
    ) -> tuple[float, float]:
        tc, tr = self.tilemap.world_to_tile(wx, wy)
        max_radius = 8
        for radius in range(0, max_radius + 1):
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if abs(dc) != radius and abs(dr) != radius:
                        continue
                    c = tc + dc
                    r = tr + dr
                    if not (0 <= c < self.tilemap.cols and 0 <= r < self.tilemap.rows):
                        continue
                    if (c, r) in self._building_blocked_tiles:
                        continue
                    if walkable_fn is not None:
                        if not walkable_fn(c, r):
                            continue
                    elif not self.tilemap.is_walkable(c, r):
                        continue
                    return self.tilemap.tile_center(c, r)
        return self.tilemap.tile_center(tc, tr)

    # ── Garrison / storage ────────────────────────────────────────────────────
    def _try_garrison_archers(self, tower: Building) -> bool:
        archers = [u for u in self._selected if u.unit_class == Unit.ROLE_ARCHER]
        if not archers:
            return False

        placed = 0
        for archer in archers:
            if not tower.has_garrison_space:
                break
            if not tower.garrison_archer():
                break
            if archer in self.units:
                self.units.remove(archer)
                self._unit_by_uid.pop(int(archer.uid), None)
            placed += 1

        if placed <= 0:
            return False

        self._selected = [u for u in self._selected if u in self.units]
        for unit in self.units:
            unit.selected = unit in self._selected
        return True

    def _ungarrison_selected_tower(self) -> None:
        b = self._selected_building
        if b is None or not b.can_garrison_archers or b.garrisoned_archers <= 0:
            return

        while b.garrisoned_archers > 0:
            if not b.pop_garrison_archer():
                break
            ax, ay = b.spawn_anchor()
            wx, wy = self._find_spawn_world_near(ax, ay)
            unit = Unit(wx, wy, civilization=b.civilization, unit_class=Unit.ROLE_ARCHER)
            self.units.append(unit)
            self._unit_by_uid[int(unit.uid)] = unit
            if self._network_enabled and b.civilization == self.player_civilization:
                self._net_send_spawn_unit(unit)

    def _update_storage_capacity(self) -> None:
        caps = dict(self._base_storage)
        for b in self.buildings:
            if b.is_dead:
                continue
            if b.civilization != self.player_civilization:
                continue
            bonus = b.storage_bonus
            if bonus <= 0:
                continue
            for key in caps:
                caps[key] += bonus
        self.resource_manager.set_capacities(caps)

    # ── Selection helpers ─────────────────────────────────────────────────────
    def _select(self, unit: Unit) -> None:
        if unit.is_dead or unit.civilization != self.player_civilization:
            return
        if unit not in self._selected:
            unit.selected = True
            self._selected.append(unit)

    def _select_ship(self, ship: Ship) -> None:
        if ship.civilization != self.player_civilization:
            return
        if ship not in self._selected_ships:
            ship.selected = True
            self._selected_ships.append(ship)

    def _deselect_units_only(self) -> None:
        for unit in self._selected:
            unit.selected = False
        self._selected.clear()

    def _deselect_ships(self) -> None:
        for ship in self._selected_ships:
            ship.selected = False
        self._selected_ships.clear()

    def _deselect_all(self) -> None:
        self._deselect_units_only()
        self._deselect_ships()

    def _select_all(self) -> None:
        self._clear_building_selection()
        self._selected_node = None
        self._deselect_ships()
        for u in self.units:
            if u.civilization == self.player_civilization and not u.is_dead:
                self._select(u)

    def _select_building(self, building: Building) -> None:
        self._deselect_all()
        self._selected_node = None
        self._selected_enemy_unit = None
        self._clear_building_selection()
        building.selected = True
        self._selected_building = building

    def _clear_building_selection(self) -> None:
        for b in self.buildings:
            b.selected = False
        self._selected_building = None

    def _refresh_building_masks(self) -> None:
        self._building_blocked_tiles = self._collect_blocked_tiles()
        self._building_resource_reserved_tiles = self._collect_building_reserved_tiles(margin=2)
        self._refresh_tree_skip_tiles()

    def _refresh_tree_skip_tiles(self) -> None:
        skip = set(self._building_resource_reserved_tiles)
        skip.update(self._building_blocked_tiles)
        if self.resource_manager is not None:
            skip.update(self.resource_manager.wood_node_tiles)
        self._tree_skip_tiles = skip

    def _collect_blocked_tiles(self) -> set[tuple[int, int]]:
        blocked: set[tuple[int, int]] = set()
        for building in self.buildings:
            if building.is_dead:
                continue
            blocked.update(building.footprint_tiles(self.tilemap))
        return blocked

    def _collect_building_reserved_tiles(self, margin: int = 2) -> set[tuple[int, int]]:
        reserved: set[tuple[int, int]] = set()
        for building in self.buildings:
            if building.is_dead:
                continue
            ft = building.footprint_tiles(self.tilemap)
            reserved.update(self._expand_tiles(ft, margin=margin))
        return reserved

    @staticmethod
    def _expand_tiles(
        tiles: set[tuple[int, int]],
        *,
        margin: int,
    ) -> set[tuple[int, int]]:
        if margin <= 0:
            return set(tiles)
        out: set[tuple[int, int]] = set()
        for col, row in tiles:
            for dr in range(-margin, margin + 1):
                for dc in range(-margin, margin + 1):
                    out.add((col + dc, row + dr))
        return out

    def _process_ship_events(self, events: list[dict[str, object]]) -> None:
        for event in events:
            kind = str(event.get("kind", ""))
            unit = event.get("unit")
            if not isinstance(unit, Unit):
                continue

            if kind == "board":
                if unit in self.units:
                    self.units.remove(unit)
                    self._unit_by_uid.pop(int(unit.uid), None)
                if unit in self._selected:
                    self._selected.remove(unit)
                    unit.selected = False
                self._worker_haul.pop(id(unit), None)
            elif kind == "unload":
                wx = float(event.get("wx", unit.world_pos.x))
                wy = float(event.get("wy", unit.world_pos.y))
                unit.world_pos.update(wx, wy)
                unit.stop_attack()
                unit.stop_constructing()
                unit.stop_gathering()
                unit.target_pos = None
                if unit not in self.units:
                    self.units.append(unit)
                    self._unit_by_uid[int(unit.uid)] = unit

    # ── Update ────────────────────────────────────────────────────────────────
    def _update(self, dt: float, keys) -> None:
        if self.game_result is not None:
            return
        if self._network_enabled:
            self._process_network_messages()
        self._game_elapsed_s += dt
        self._network_tick_update(dt)
        if self.replay.is_playback:
            for msg in self.replay.poll(self._sync_tick):
                if isinstance(msg, dict):
                    self._apply_command_message(msg, allow_local_civ=True)
        if self._desync_alert_s > 0.0:
            self._desync_alert_s = max(0.0, self._desync_alert_s - dt)
        if self._edge_scroll_lock_s > 0.0:
            self._edge_scroll_lock_s = max(0.0, self._edge_scroll_lock_s - dt)
        allow_edge_scroll = self._edge_scroll_lock_s <= 0.0 and self._is_edge_scroll_allowed()
        self.camera.update(dt, keys, allow_edge_scroll=allow_edge_scroll)

        player_unit_hp_before = {
            int(u.uid): float(u.hp)
            for u in self.units
            if (not u.is_dead and u.civilization == self.player_civilization)
        }
        player_build_hp_before = {
            id(b): float(b.hp)
            for b in self.buildings
            if (not b.is_dead and b.civilization == self.player_civilization)
        }

        self.resource_manager.update(dt, self.tilemap, blocked_tiles=self._building_blocked_tiles)
        if not self.replay.is_playback:
            self._update_ai_age_up(dt)
            for ai in self.ai_controllers:
                ai.update(dt)
            self._update_chaos_factions(dt)
        self._update_buildings(dt)
        for ship in list(self.ships):
            ship_events = ship.update(dt, tilemap=self.tilemap)
            if ship_events:
                self._process_ship_events(ship_events)

        to_remove: list[Unit] = []
        for unit in list(self.units):
            event = unit.update(dt)
            if event is not None:
                kind = str(event.get("kind", ""))
                if kind == "gather":
                    node = event.get("node")
                    amount = int(event.get("amount", 0))
                    if node is not None and amount > 0:
                        if unit.civilization == self.player_civilization and unit.can_gather:
                            self._handle_worker_gather_event(unit, node, amount)
                        elif unit.civilization in self._ai_by_civ:
                            self._ai_by_civ[unit.civilization].handle_gather(node, amount)
                        else:
                            self.resource_manager.drain_node(node, amount)
                elif kind == "build":
                    b = event.get("building")
                    work_seconds = float(event.get("work_seconds", 0.0))
                    if isinstance(b, Building) and work_seconds > 0.0:
                        completed = b.apply_construction_work(work_seconds)
                        if completed:
                            self._update_storage_capacity()

            if unit.civilization == self.player_civilization:
                unit.tick_hunger(dt * self._soldier_hunger_drain_mult)
                if unit.needs_food:
                    if self.resource_manager.consume("food", 1):
                        unit.feed()
                    elif self.resource_manager.consume("meat", 1):
                        unit.feed()

            if unit.death_finished:
                to_remove.append(unit)

        self._update_worker_haul()

        player_under_attack = False
        for unit in self.units:
            prev_hp = player_unit_hp_before.get(int(unit.uid))
            if prev_hp is None:
                continue
            if float(unit.hp) + 0.01 < prev_hp:
                player_under_attack = True
                break
        if not player_under_attack:
            for building in self.buildings:
                prev_hp = player_build_hp_before.get(id(building))
                if prev_hp is None:
                    continue
                if float(building.hp) + 0.01 < prev_hp:
                    player_under_attack = True
                    break
        if player_under_attack:
            self.sound.play("alert")

        for civ, new_age in self.tech_tree.update(dt):
            for unit in self.units:
                if unit.civilization == civ and not unit.is_dead:
                    self._apply_unit_age_bonus(unit)
            if (self._network_enabled or self.replay.is_recording) and civ == self.player_civilization:
                self._net_send_tech_age(new_age)

        if to_remove:
            self.sound.play("death")
            for unit in to_remove:
                if unit in self.units:
                    self.units.remove(unit)
                    self._unit_by_uid.pop(int(unit.uid), None)
                if unit in self._selected:
                    self._selected.remove(unit)
                self._worker_haul.pop(id(unit), None)
            for unit in self._selected:
                unit.selected = True
            if self._selected_enemy_unit in to_remove:
                self._selected_enemy_unit = None

        dead_buildings = [b for b in self.buildings if b.is_dead]
        if dead_buildings:
            self.sound.play("death")
            enemy_destroyed = sum(1 for b in dead_buildings if b.civilization in self.enemy_civilizations)
            if enemy_destroyed > 0:
                self.campaign.on_enemy_building_destroyed(enemy_destroyed)
            for building in dead_buildings:
                if building in self.buildings:
                    self.buildings.remove(building)
                if self._selected_building is building:
                    self._selected_building = None
            self._refresh_building_masks()
            self._update_storage_capacity()
            self._check_victory_defeat()

        houses = sum(
            1
            for b in self.buildings
            if (
                not b.is_dead
                and b.civilization == self.player_civilization
                and b.building_type in (Building.TYPE_HOUSE1, Building.TYPE_HOUSE2, Building.TYPE_HOUSE3)
            )
        )
        worker_selected = any(
            (not u.is_dead and u.civilization == self.player_civilization and u.can_gather)
            for u in self._selected
        )
        self.tutorial.update(worker_selected=worker_selected, current_house_count=houses)
        if self.tutorial.enabled and self.tutorial.done:
            self.game_result = "victory"
        if self.campaign.update(self):
            self.game_result = "victory"

        self._civ_sync_timer_s -= dt
        if self._civ_sync_timer_s <= 0.0:
            self._civ_sync_timer_s = 0.35
            self._sync_civilizations()
        if self._network_enabled:
            self._reindex_units()
            self._reindex_ships()
        self._check_victory_defeat()

    def _update_chaos_factions(self, dt: float) -> None:
        # Delay chaos raids so kingdoms can establish economy first.
        if self._game_elapsed_s < 78.0:
            return
        self._chaos_state_timer_s -= dt
        if self._chaos_state_timer_s > 0.0:
            return
        self._chaos_state_timer_s = 1.65

        chaos_units = [
            u for u in self.units if (not u.is_dead and self._is_chaos_civ(u.civilization) and u.can_attack)
        ]
        if not chaos_units:
            return

        for unit in chaos_units:
            if unit.attack_target is not None and not unit.attack_target.is_dead:
                continue
            enemies = [e for e in self.units if (not e.is_dead and e.civilization != unit.civilization)]
            if enemies:
                target = min(
                    enemies,
                    key=lambda e: (e.world_pos.x - unit.world_pos.x) ** 2 + (e.world_pos.y - unit.world_pos.y) ** 2,
                )
                unit.attack_command(
                    target,
                    pathfinder=self.pathfinder,
                    blocked_tiles=self._building_blocked_tiles,
                )
                continue

            enemy_buildings = [
                b for b in self.buildings if (not b.is_dead and b.civilization != unit.civilization)
            ]
            if not enemy_buildings:
                continue
            target_b = min(
                enemy_buildings,
                key=lambda b: (b.world_pos.x - unit.world_pos.x) ** 2 + (b.world_pos.y - unit.world_pos.y) ** 2,
            )
            unit.attack_command(
                target_b,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )

    def _update_enemy_ai(self) -> None:
        enemies = [u for u in self.units if (u.civilization != self.player_civilization and not u.is_dead)]
        friendlies = [u for u in self.units if (u.civilization == self.player_civilization and not u.is_dead)]
        if not enemies or not friendlies:
            return

        for enemy in enemies:
            if not enemy.can_attack:
                continue
            if enemy.attack_target is not None and not enemy.attack_target.is_dead:
                continue

            best = None
            best_d2 = 10e12
            for f in friendlies:
                dx = f.world_pos.x - enemy.world_pos.x
                dy = f.world_pos.y - enemy.world_pos.y
                d2 = dx * dx + dy * dy
                if d2 < best_d2:
                    best_d2 = d2
                    best = f
            if best is None:
                continue
            if best_d2 > (TILE_SIZE * 8.0) ** 2:
                continue

            enemy.attack_command(
                best,
                pathfinder=self.pathfinder,
                blocked_tiles=self._building_blocked_tiles,
            )

    # ── Draw ──────────────────────────────────────────────────────────────────
    def _draw(self) -> None:
        self.screen.fill((15, 15, 20))
        c0, r0, c1, r1 = self.camera.get_visible_tile_range()
        pad = 3
        vc0 = max(0, c0 - pad)
        vr0 = max(0, r0 - pad)
        vc1 = min(self.tilemap.cols - 1, c1 + pad)
        vr1 = min(self.tilemap.rows - 1, r1 + pad)

        self.tilemap.draw(self.screen, self.camera)
        self.tilemap.draw_trees(
            self.screen,
            self.camera,
            self.tree_sets,
            skip_tiles=self._tree_skip_tiles,
        )

        self.resource_manager.draw_nodes(self.screen, self.camera)

        for building in self.buildings:
            bc, br = self.tilemap.world_to_tile(building.world_pos.x, building.world_pos.y)
            if bc < vc0 or bc > vc1 or br < vr0 or br > vr1:
                continue
            building.draw(self.screen, self.camera)
        for ship in self.ships:
            sc, sr = self.tilemap.world_to_tile(ship.world_pos.x, ship.world_pos.y)
            if sc < vc0 or sc > vc1 or sr < vr0 or sr > vr1:
                continue
            ship.draw(self.screen, self.camera)
        self._draw_selected_node()

        if self.show_grid and self.camera.zoom >= 0.45:
            self.tilemap.draw_grid(self.screen, self.camera)

        for unit in self._selected:
            if unit.target_pos and not unit.is_dead:
                ux, uy = self.camera.world_to_screen(unit.world_pos)
                tx, ty = self.camera.world_to_screen(unit.target_pos)
                pygame.draw.line(self.screen, (255, 230, 110), (int(ux), int(uy)), (int(tx), int(ty)), 1)
            if unit.attack_target is not None and not unit.attack_target.is_dead:
                ux, uy = self.camera.world_to_screen(unit.world_pos)
                tx, ty = self.camera.world_to_screen(unit.attack_target.world_pos)
                pygame.draw.line(self.screen, (232, 110, 110), (int(ux), int(uy)), (int(tx), int(ty)), 1)
        for ship in self._selected_ships:
            if ship.target_pos is None:
                continue
            sx, sy = self.camera.world_to_screen((ship.world_pos.x, ship.world_pos.y))
            tx, ty = self.camera.world_to_screen((ship.target_pos.x, ship.target_pos.y))
            pygame.draw.line(self.screen, (110, 200, 255), (int(sx), int(sy)), (int(tx), int(ty)), 1)

        for unit in self.units:
            uc, ur = self.tilemap.world_to_tile(unit.world_pos.x, unit.world_pos.y)
            if uc < vc0 or uc > vc1 or ur < vr0 or ur > vr1:
                continue
            unit.draw(self.screen, self.camera)

        pulse = 1.0 + 0.20 * math.sin(pygame.time.get_ticks() / 120.0)
        for unit in self._selected:
            if unit.target_pos:
                tx, ty = self.camera.world_to_screen(unit.target_pos)
                cx, cy = int(tx), int(ty)
                outer = max(6, int(11 * self.camera.zoom * pulse))
                inner = max(4, int(7 * self.camera.zoom * pulse))
                pygame.draw.circle(self.screen, (20, 20, 20), (cx, cy), outer + 1, 3)
                pygame.draw.circle(self.screen, YELLOW, (cx, cy), outer, 2)
                pygame.draw.circle(self.screen, GREEN, (cx, cy), inner, 2)
                pygame.draw.line(self.screen, WHITE, (cx - inner, cy), (cx + inner, cy), 1)
                pygame.draw.line(self.screen, WHITE, (cx, cy - inner), (cx, cy + inner), 1)
            if unit.attack_target is not None and not unit.attack_target.is_dead:
                tx, ty = self.camera.world_to_screen(unit.attack_target.world_pos)
                cx, cy = int(tx), int(ty)
                outer = max(7, int(12 * self.camera.zoom * pulse))
                pygame.draw.circle(self.screen, (28, 16, 16), (cx, cy), outer + 2, 3)
                pygame.draw.circle(self.screen, (240, 94, 94), (cx, cy), outer, 2)
                pygame.draw.line(self.screen, (255, 214, 214), (cx - outer + 2, cy), (cx + outer - 2, cy), 1)
                pygame.draw.line(self.screen, (255, 214, 214), (cx, cy - outer + 2), (cx, cy + outer - 2), 1)

        if self._selected_enemy_unit is not None and not self._selected_enemy_unit.is_dead:
            ex, ey = self.camera.world_to_screen(self._selected_enemy_unit.world_pos)
            rr = max(12, int(18 * self.camera.zoom))
            pygame.draw.circle(self.screen, (24, 8, 8), (int(ex), int(ey)), rr + 2, 3)
            pygame.draw.circle(self.screen, (248, 104, 104), (int(ex), int(ey)), rr, 2)

        if self.game_result is None:
            self._draw_build_preview()

            if self._box_start:
                mx, my = pygame.mouse.get_pos()
                x0, y0 = self._box_start
                rect = pygame.Rect(min(x0, mx), min(y0, my), abs(mx - x0), abs(my - y0))
                overlay = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                overlay.fill((80, 200, 80, 35))
                self.screen.blit(overlay, rect.topleft)
                pygame.draw.rect(self.screen, GREEN, rect, 1)

        self._draw_hud()
        if self.tutorial.enabled:
            self.tutorial.draw(self.screen, self.font_md, self.font_sm)
        if self.campaign.enabled:
            self.campaign.draw(self.screen, self.font_sm, self.campaign.lines(self))
        if self.replay.is_playback:
            panel = pygame.Surface((248, 74), pygame.SRCALPHA)
            pygame.draw.rect(panel, (14, 20, 28, 198), panel.get_rect(), border_radius=8)
            pygame.draw.rect(panel, (86, 128, 170, 238), panel.get_rect(), 1, border_radius=8)
            px = self.screen.get_width() - 264
            py = self.screen.get_height() - 208
            self.screen.blit(panel, (px, py))
            txt = self.font_sm.render(f"Replay Tick {self._sync_tick}", True, (216, 228, 242))
            self.screen.blit(txt, (px + 12, py + 10))
            pairs = sorted(self._replay_summary.items(), key=lambda item: item[1], reverse=True)[:2]
            if pairs:
                details = "  ".join(f"{k}:{v}" for k, v in pairs)
                sub = self.font_xs.render(details, True, (184, 206, 228))
                self.screen.blit(sub, (px + 12, py + 34))
        if self.game_result is None:
            self._draw_build_palette()
            self._draw_building_ui()
        self.hud_ui.draw_resources(self.screen, self.resource_manager)
        self.hud_ui.draw_minimap(
            self.screen,
            self.camera,
            self.units,
            self.buildings,
            player_civilization=self.player_civilization,
        )
        if self.game_result is not None:
            self.hud_ui.draw_endgame(self.screen, self.game_result)
        pygame.display.flip()

    def _draw_build_preview(self) -> None:
        if self._build_mode_type is None:
            self._build_hover_anchor = None
            return

        wx, wy = self.camera.screen_to_world(pygame.mouse.get_pos())
        anchor = self.tilemap.world_to_tile(wx, wy)
        self._build_hover_anchor = anchor
        footprint = self._candidate_footprint(anchor, self._build_mode_type)
        valid = self._is_placement_valid(footprint)

        fill = (66, 180, 80, 76) if valid else (180, 70, 70, 76)
        edge = (120, 255, 140) if valid else (255, 120, 120)
        for col, row in footprint:
            if not (0 <= col < self.tilemap.cols and 0 <= row < self.tilemap.rows):
                continue
            sx, sy = self.camera.world_to_screen((col * TILE_SIZE, row * TILE_SIZE))
            tw = max(1, int(TILE_SIZE * self.camera.zoom))
            th = tw
            tile_rect = pygame.Rect(int(round(sx)), int(round(sy)), tw, th)
            ov = pygame.Surface((tile_rect.width, tile_rect.height), pygame.SRCALPHA)
            ov.fill(fill)
            self.screen.blit(ov, tile_rect.topleft)
            pygame.draw.rect(self.screen, edge, tile_rect, 1)

    def _draw_hud(self) -> None:
        def fit_text(font: pygame.font.Font, text: str, max_w: int) -> str:
            if font.size(text)[0] <= max_w:
                return text
            suffix = "..."
            keep = text
            while keep and font.size(keep + suffix)[0] > max_w:
                keep = keep[:-1]
            return (keep + suffix) if keep else suffix

        now = pygame.time.get_ticks()
        idle_ms = now - self._hud_last_activity_ms
        show_full = self._hud_pinned or now <= self._hud_full_until_ms

        fps = self.clock.get_fps()
        friendly_total = sum(
            1 for unit in self.units if unit.civilization == self.player_civilization and not unit.is_dead
        )
        enemy_total = sum(
            1 for unit in self.units if unit.civilization != self.player_civilization and not unit.is_dead
        )
        selected_workers = sum(1 for unit in self._selected if unit.can_gather)
        selected_soldiers = sum(1 for unit in self._selected if unit.hunger_enabled)
        selected_stances = {
            getattr(unit, "stance", Unit.STANCE_AGGRESSIVE)
            for unit in self._selected
            if (not unit.is_dead and unit.can_attack)
        }
        if len(selected_stances) == 1:
            stance_text = next(iter(selected_stances))
        elif selected_stances:
            stance_text = "mix"
        else:
            stance_text = "-"
        starving = sum(1 for unit in self.units if unit.starving)
        col_tx, row_tx = self.camera.screen_to_tile(pygame.mouse.get_pos())
        tile = self.tilemap.get_tile(col_tx, row_tx)
        age_label = self.tech_tree.age_label(self.player_civilization)
        age_progress = self.tech_tree.research_progress(self.player_civilization)
        form_label = self._formation_mode().upper()

        if self.ai_controllers:
            state_counts: dict[str, int] = {}
            for ai in self.ai_controllers:
                state_counts[ai.state] = state_counts.get(ai.state, 0) + 1
            state_text = " ".join(f"{name}:{count}" for name, count in state_counts.items())
            context_line = f"Dusman YZ {state_text}  Birim {enemy_total}"
        else:
            context_line = f"Dusman birimleri {enemy_total}"
        context_color = (194, 206, 220)
        if self._selected_building is not None:
            b = self._selected_building
            if b.under_construction:
                rem = max(0.0, b.build_time_total * (1.0 - b.build_progress))
                context_line = (
                    f"{b.display_name}: Insa {int(b.build_progress*100)}%  "
                    f"Kalan {rem:.1f}s"
                )
            elif b.can_garrison_archers:
                context_line = (
                    f"{b.display_name}: HP {b.hp}/{b.max_hp}  Kuyruk {b.queue_size}  "
                    f"Garnizon {b.garrisoned_archers}/{b.garrison_capacity}"
                )
            else:
                context_line = f"{b.display_name}: HP {b.hp}/{b.max_hp}  Kuyruk {b.queue_size}"
            context_color = (226, 232, 240)
        elif self._selected_node is not None and not self._selected_node.is_depleted:
            node = self._selected_node
            context_line = (
                f"{node.resource_type.upper()} kaynak  HP {node.amount}/{node.max_amount}  "
                f"Toplama {node.gather_duration:.2f}s"
            )
            context_color = (238, 217, 140)
        elif self._selected_enemy_unit is not None and not self._selected_enemy_unit.is_dead:
            enemy = self._selected_enemy_unit
            context_line = (
                f"Dusman {enemy.unit_class.title()} ({enemy.civilization})  "
                f"HP {int(enemy.hp)}/{enemy.max_hp}"
            )
            context_color = (244, 154, 154)
        if self._desync_alert_s > 0.0:
            context_line = f"DESYNC algilandi ({self._desync_count}) - yeniden senkronize edildi."
            context_color = (246, 156, 138)
        if self._network_enabled:
            context_line = f"{context_line}  Senk {self._sync_tick}/{self._remote_sync_tick}"

        tools_active = [tid for tid, active in self._tool_unlocked.items() if active]
        panel_w = 430 if show_full else 320
        panel_h = 176 if show_full else 76
        if idle_ms > HUD_IDLE_HIDE_MS and not self._hud_pinned:
            panel_h = 54

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (8, 13, 21, 188), panel.get_rect(), border_radius=12)
        pygame.draw.rect(panel, (70, 122, 158, 220), panel.get_rect(), 1, border_radius=12)
        self.screen.blit(panel, (10, 8))

        title = "Komut HUD (Sabit)" if self._hud_pinned else "Komut HUD"
        title_surf = self.font_md.render(title, True, (230, 236, 244))
        self.screen.blit(title_surf, (20, 16))

        mode = self.font_xs.render("[F1] Sabitle/Sabiti Kaldir", True, (150, 186, 210))
        self.screen.blit(mode, (20 + title_surf.get_width() + 10, 20))

        def draw_chip(x: int, y: int, text: str, color: tuple[int, int, int]) -> int:
            surf = self.font_xs.render(text, True, color)
            w = surf.get_width() + 14
            h = surf.get_height() + 6
            chip = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(chip, (18, 24, 34, 220), chip.get_rect(), border_radius=8)
            pygame.draw.rect(chip, (64, 88, 114, 240), chip.get_rect(), 1, border_radius=8)
            chip.blit(surf, (7, 3))
            self.screen.blit(chip, (x, y))
            return w + 6

        cx = 20
        cy = 40
        cx += draw_chip(cx, cy, f"FPS {fps:4.0f}", (184, 228, 255))
        cx += draw_chip(cx, cy, f"Zoom {self.camera.zoom:.2f}x", (214, 232, 246))
        cx += draw_chip(cx, cy, f"Sec {len(self._selected)}/{friendly_total}", (226, 240, 204))
        if show_full:
            cx += draw_chip(cx, cy, f"Isci {selected_workers}", (203, 224, 168))
            draw_chip(cx, cy, f"Asker {selected_soldiers}", (215, 204, 174))

        starving_color = (255, 120, 108) if starving > 0 else (152, 210, 160)
        if panel_h > 70:
            draw_chip(20, 66, f"Ac {starving}", starving_color)
            draw_chip(130, 66, f"Karo {col_tx},{row_tx}:{tile}", (174, 184, 195))
            if show_full:
                draw_chip(262, 66, f"Form {form_label}", (198, 216, 236))
        if panel_h > 100:
            draw_chip(20, 84, f"Stance {stance_text}", (208, 202, 236))
            if age_progress > 0.0:
                draw_chip(130, 84, f"Cag {age_label} %{int(age_progress * 100)}", (232, 210, 142))
            else:
                draw_chip(130, 84, f"Cag {age_label}", (232, 210, 142))

        if panel_h > 80:
            ctx_surf = self.font_sm.render(fit_text(self.font_sm, context_line, panel_w - 26), True, context_color)
            self.screen.blit(ctx_surf, (20, 92))

        if show_full and panel_h > 130:
            help_lines = [
                "[TAB] Uretici Paneli  [B] Insa  [SagTik] Git/Topla/Saldir",
                "[1/2/3/4/5] Topla  [Q/W/E/R] Uret  [U] Cikart  [H] Cag Atla",
                "[F2/F3/F4] Stance  [F5] Formasyon  [F11] Tam Ekran",
            ]
            for i, line in enumerate(help_lines):
                help_surf = self.font_xs.render(
                    fit_text(self.font_xs, line, panel_w - 26),
                    True,
                    (190, 212, 232),
                )
                self.screen.blit(help_surf, (20, 110 + i * 12))

        if tools_active:
            tx = 20
            ty = 146 if panel_h > 146 else 66
            for tid in tools_active:
                icon = self._ui_tool_icons.get(tid)
                if icon is None:
                    continue
                slot = pygame.Surface((icon.get_width() + 8, icon.get_height() + 8), pygame.SRCALPHA)
                pygame.draw.rect(slot, (24, 30, 36, 225), slot.get_rect(), border_radius=7)
                pygame.draw.rect(slot, (106, 126, 146, 245), slot.get_rect(), 1, border_radius=7)
                slot.blit(icon, (4, 4))
                self.screen.blit(slot, (tx, ty))
                tx += slot.get_width() + 6

        # Resource HUD moved to src/ui/hud.py

    def _draw_build_palette(self) -> None:
        self._build_palette_buttons.clear()
        row_types = Building.buildable_types()

        if self._build_palette_collapsed:
            tab_w = 28
            tab_h = 120
            x = 10
            y = self.screen.get_height() - tab_h - 18
            tab = pygame.Surface((tab_w, tab_h), pygame.SRCALPHA)
            pygame.draw.rect(tab, (34, 24, 18, 224), tab.get_rect(), border_radius=8)
            pygame.draw.rect(tab, (120, 92, 72, 235), tab.get_rect(), 1, border_radius=8)
            self.screen.blit(tab, (x, y))
            arrow = self.font_md.render(">", True, (236, 220, 198))
            self.screen.blit(arrow, (x + (tab_w - arrow.get_width()) // 2, y + 10))
            hint = self.font_xs.render("Insa", True, (212, 188, 166))
            self.screen.blit(hint, (x + 2, y + 42))
            self._build_palette_toggle_rect = pygame.Rect(x, y, tab_w, tab_h)
            return

        cols = 2
        card_w = 166
        card_h = 44
        gap = 6
        rows = (len(row_types) + cols - 1) // cols
        panel_w = cols * card_w + (cols - 1) * gap + 24
        panel_h = 56 + rows * card_h + (rows - 1) * gap
        x = 16
        y = self.screen.get_height() - panel_h - 16

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (32, 22, 16, 214), panel.get_rect(), border_radius=12)
        pygame.draw.rect(panel, (115, 84, 62, 236), panel.get_rect(), 1, border_radius=12)
        self.screen.blit(panel, (x, y))
        toggle_rect = pygame.Rect(x + panel_w - 30, y + 8, 20, 20)
        pygame.draw.rect(self.screen, (54, 40, 32), toggle_rect, border_radius=6)
        pygame.draw.rect(self.screen, (156, 126, 102), toggle_rect, 1, border_radius=6)
        toggle_txt = self.font_xs.render("<", True, (228, 214, 198))
        self.screen.blit(
            toggle_txt,
            (toggle_rect.x + (toggle_rect.width - toggle_txt.get_width()) // 2, toggle_rect.y + 4),
        )
        self._build_palette_toggle_rect = toggle_rect

        title = "Insa Paneli"
        tcolor = (235, 232, 216) if self._has_selected_worker() else (235, 178, 178)
        ts = self.font_md.render(title, True, tcolor)
        self.screen.blit(ts, (x + 12, y + 8))
        sub = "Isci sec -> kart sec -> haritaya birak"
        sub_surf = self.font_xs.render(sub, True, (198, 184, 168))
        self.screen.blit(sub_surf, (x + 12, y + 27))

        display_names = {
            Building.TYPE_HOUSE1: "House I",
            Building.TYPE_HOUSE2: "House II",
            Building.TYPE_HOUSE3: "House III",
            Building.TYPE_BARRACKS: "Barracks",
            Building.TYPE_ARCHERY: "Archery",
            Building.TYPE_SMITHY: "Smithy",
            Building.TYPE_TOWER: "Tower",
            Building.TYPE_CASTLE: "Castle",
        }

        origin_x = x + 12
        origin_y = y + 44
        for i, btype in enumerate(row_types):
            row_i = i // cols
            col_i = i % cols
            bx = origin_x + col_i * (card_w + gap)
            by = origin_y + row_i * (card_h + gap)
            rect = pygame.Rect(bx, by, card_w, card_h)
            is_mode = self._build_mode_type == btype
            costs = Building.build_cost(btype)
            can_afford = self.resource_manager.can_afford(costs)
            can_build = self._has_selected_worker()
            enabled = can_afford and can_build

            if is_mode:
                fill = (82, 124, 96)
                border = (168, 236, 184)
            elif enabled:
                fill = (67, 84, 69)
                border = (116, 148, 122)
            else:
                fill = (72, 54, 52)
                border = (128, 86, 84)
            pygame.draw.rect(self.screen, fill, rect, border_radius=8)
            pygame.draw.rect(self.screen, border, rect, 1, border_radius=8)

            icon = self._ui_build_icons.get(btype)
            tx = rect.x + 8
            if icon is not None:
                iy = rect.y + (rect.height - icon.get_height()) // 2
                self.screen.blit(icon, (rect.x + 4, iy))
                tx += icon.get_width() + 6

            name = display_names.get(btype, btype.title())
            label = self.font_sm.render(name, True, WHITE if enabled else (220, 170, 170))
            self.screen.blit(label, (tx, rect.y + 3))

            ctime = Building.construction_time(btype)
            ctext = f"G{costs.get('gold', 0)}  W{costs.get('wood', 0)}  S{costs.get('stone', 0)}  {ctime:.0f}s"
            cost_surf = self.font_xs.render(ctext, True, (206, 198, 182) if enabled else (170, 130, 130))
            self.screen.blit(cost_surf, (tx, rect.y + 21))
            self._build_palette_buttons.append((rect, btype))

    def _draw_building_ui(self) -> None:
        self._building_ui_buttons.clear()
        b = self._selected_building
        if b is None:
            return

        panel_w = 334
        if b.can_produce:
            options = b.production_options()
            rows = max(1, len(options))
            row_h = 36
            panel_h = 116 + rows * (row_h + 6)
        else:
            options = []
            row_h = 0
            panel_h = 124

        x = self.screen.get_width() - panel_w - 16
        y = self.screen.get_height() - panel_h - 16

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (16, 22, 30, 225), panel.get_rect(), border_radius=12)
        pygame.draw.rect(panel, (88, 132, 172, 232), panel.get_rect(), 1, border_radius=12)
        self.screen.blit(panel, (x, y))

        title = self.font_md.render(f"{b.display_name}", True, WHITE)
        self.screen.blit(title, (x + 12, y + 10))

        stats = self.font_xs.render(
            f"HP {b.hp}/{b.max_hp}   Kuyruk {b.queue_size}/{b.max_queue}",
            True,
            (196, 210, 224),
        )
        self.screen.blit(stats, (x + 12, y + 32))
        if b.under_construction:
            rem = max(0.0, b.build_time_total * (1.0 - b.build_progress))
            cst = self.font_xs.render(
                f"Insa {int(b.build_progress*100)}%   Kalan {rem:.1f}s",
                True,
                (176, 214, 236),
            )
            self.screen.blit(cst, (x + 12, y + 48))

        if b.storage_bonus > 0 and b.is_complete:
            stor = self.font_xs.render(
                f"Depo bonusu +{b.storage_bonus}",
                True,
                (212, 228, 186),
            )
            self.screen.blit(stor, (x + 12, y + (62 if b.under_construction else 48)))

        if b.can_garrison_archers:
            gtxt = self.font_xs.render(
                f"Garnizon {b.garrisoned_archers}/{b.garrison_capacity}  [U] Cikart",
                True,
                (230, 220, 170),
            )
            self.screen.blit(gtxt, (x + 12, y + (78 if b.under_construction else 64)))
        if b.building_type == Building.TYPE_TOWER and b.is_dock:
            dock_txt = self.font_xs.render(
                "Liman aktif: gemi uretebilir",
                True,
                (178, 220, 244),
            )
            self.screen.blit(dock_txt, (x + 12, y + (92 if b.under_construction else 78)))

        if b.queue_size > 0:
            prog = b.current_queue_progress()
            bw = panel_w - 24
            bh = 7
            bx = x + 12
            by = y + 74
            pygame.draw.rect(self.screen, (22, 28, 36), (bx, by, bw, bh), border_radius=4)
            pygame.draw.rect(
                self.screen,
                (76, 206, 118),
                (bx + 1, by + 1, max(1, int((bw - 2) * prog)), bh - 2),
                border_radius=4,
            )
            prog_txt = self.font_xs.render("Uretim", True, (164, 194, 222))
            self.screen.blit(prog_txt, (bx, by - 14))

        if not b.can_produce:
            if b.under_construction:
                idle = self.font_xs.render(
                    "Uretim icin once isciler bu binayi tamamlamali.",
                    True,
                    (188, 204, 218),
                )
            else:
                idle = self.font_xs.render("Bu bina tipinde uretim yok.", True, (176, 188, 202))
            self.screen.blit(idle, (x + 12, y + panel_h - 20))
            return

        hotkeys = ["Q", "W", "E", "R"]
        btn_w = panel_w - 24
        base_y = y + 88
        for i, option in enumerate(options):
            btn_rect = pygame.Rect(x + 10, base_y + i * (row_h + 6), btn_w, row_h)
            costs = {
                "gold": int(option.get("gold_cost", 0)),
                "wood": int(option.get("wood_cost", 0)),
                "stone": int(option.get("stone_cost", 0)),
            }
            kind = str(option.get("kind", "unit"))
            tool_id = str(option.get("tool_id", ""))
            locked = kind == "tool" and self._tool_unlocked.get(tool_id, False)
            required_age = str(option.get("required_age", "dark"))
            age_locked = False
            if required_age in AGE_ORDER:
                civ_age = self.tech_tree.age(b.civilization)
                age_locked = AGE_ORDER.index(civ_age) < AGE_ORDER.index(required_age)
            queue_full = b.queue_size >= b.max_queue
            can_afford = self.resource_manager.can_afford(costs)
            enabled = (not locked) and (not age_locked) and can_afford and (not queue_full)

            fill = (63, 95, 70) if enabled else (64, 50, 50)
            border = (92, 128, 106) if enabled else (110, 78, 76)
            if locked:
                fill = (66, 66, 48)
                border = (145, 132, 88)
            if age_locked:
                fill = (54, 58, 76)
                border = (110, 132, 186)
            pygame.draw.rect(self.screen, fill, btn_rect, border_radius=8)
            pygame.draw.rect(self.screen, border, btn_rect, 1, border_radius=8)

            hk = hotkeys[i] if i < len(hotkeys) else str(i + 1)
            label = str(option.get("label", "Unit"))
            build_time = float(option.get("build_time", 0.0))
            txt = f"{label}"
            sub_txt = f"{costs['gold']}g {costs['wood']}w {costs['stone']}s  {build_time:.1f}s"
            if locked:
                txt = f"{label}"
                sub_txt = "Unlocked"
            elif age_locked:
                txt = f"{label}"
                sub_txt = f"{required_age.title()} gerekli"
            color = WHITE if enabled else (220, 170, 170)
            if locked:
                color = (235, 220, 120)
            elif age_locked:
                color = (188, 206, 242)

            icon = None
            if kind == "unit":
                icon = self._ui_unit_icons.get(str(option.get("unit_class", "worker")))
            elif kind == "tool":
                icon = self._ui_tool_icons.get(tool_id)

            hk_box = pygame.Rect(btn_rect.x + 6, btn_rect.y + 6, 22, 22)
            pygame.draw.rect(self.screen, (24, 28, 34), hk_box, border_radius=6)
            pygame.draw.rect(self.screen, (96, 118, 142), hk_box, 1, border_radius=6)
            hk_surf = self.font_xs.render(hk, True, (214, 226, 240))
            self.screen.blit(
                hk_surf,
                (hk_box.x + (hk_box.width - hk_surf.get_width()) // 2, hk_box.y + 5),
            )

            text_x = btn_rect.x + 38
            if icon is not None:
                iy = btn_rect.y + (btn_rect.height - icon.get_height()) // 2
                self.screen.blit(icon, (btn_rect.x + 34, iy))
                text_x += icon.get_width() + 6

            surf = self.font_sm.render(txt, True, color)
            self.screen.blit(surf, (text_x, btn_rect.y + 2))
            sub_surf = self.font_xs.render(sub_txt, True, (220, 214, 198) if enabled else (184, 150, 150))
            self.screen.blit(sub_surf, (text_x, btn_rect.y + 18))
            self._building_ui_buttons.append((btn_rect, option))

    def _draw_selected_node(self) -> None:
        if self._selected_node is None:
            return
        node = self._selected_node
        if node.is_depleted:
            self._selected_node = None
            return

        type_colors = {
            "gold": (240, 205, 76),
            "stone": (182, 194, 205),
            "wood": (173, 126, 86),
            "food": (146, 204, 98),
            "meat": (218, 110, 96),
        }
        color = type_colors.get(node.resource_type, WHITE)
        sx, sy = self.camera.world_to_screen((node.wx, node.wy))
        cx, cy = int(sx), int(sy)
        zoom = self.camera.zoom
        pulse = 1.0 + 0.18 * math.sin(pygame.time.get_ticks() / 160.0)
        radius = max(8, int(node.radius * zoom * pulse))
        pygame.draw.circle(self.screen, (0, 0, 0), (cx, cy), radius + 2, 3)
        pygame.draw.circle(self.screen, color, (cx, cy), radius, 2)

        label = (
            f"{node.resource_type.upper()}  HP {node.amount}/{node.max_amount}  "
            f"toplama={node.gather_duration:.2f}s"
        )
        surf = self.font_sm.render(label, True, color)
        bg = pygame.Surface((surf.get_width() + 6, surf.get_height() + 2), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 150))
        tx = cx - bg.get_width() // 2
        ty = cy - radius - bg.get_height() - 8
        self.screen.blit(bg, (tx, ty))
        self.screen.blit(surf, (tx + 3, ty + 1))

    def _check_victory_defeat(self) -> None:
        if self.game_result is not None:
            return
        player_castles = [
            b
            for b in self.buildings
            if (not b.is_dead and b.building_type == Building.TYPE_CASTLE and b.civilization == self.player_civilization)
        ]
        enemy_castles = [
            b
            for b in self.buildings
            if (
                not b.is_dead
                and b.building_type == Building.TYPE_CASTLE
                and b.civilization in self.enemy_civilizations
            )
        ]
        if not enemy_castles:
            self.game_result = "victory"
        elif not player_castles:
            self.game_result = "defeat"

    # ── HUD helpers ───────────────────────────────────────────────────────────
    def _mark_activity(self) -> None:
        now = pygame.time.get_ticks()
        self._hud_last_activity_ms = now
        if not self._hud_pinned:
            self._hud_full_until_ms = now + HUD_FULL_SHOW_MS

    def _focus_army(self) -> None:
        if self._selected_ships:
            x = sum(ship.world_pos.x for ship in self._selected_ships) / len(self._selected_ships)
            y = sum(ship.world_pos.y for ship in self._selected_ships) / len(self._selected_ships)
            self.camera.center_on_world(x, y)
            return

        crowd = self._selected if self._selected else [
            unit for unit in self.units if unit.civilization == self.player_civilization and not unit.is_dead
        ]
        if not crowd:
            if self._selected_building is not None:
                self.camera.center_on_world(
                    self._selected_building.world_pos.x,
                    self._selected_building.world_pos.y,
                )
                return
            self.camera.center_on_world(self._spawn_world[0], self._spawn_world[1])
            return
        x = sum(unit.world_pos.x for unit in crowd) / len(crowd)
        y = sum(unit.world_pos.y for unit in crowd) / len(crowd)
        self.camera.center_on_world(x, y)

    def _is_edge_scroll_allowed(self) -> bool:
        if not pygame.display.get_active():
            return False
        if not pygame.mouse.get_focused():
            return False
        if not pygame.key.get_focused():
            return False
        mx, my = pygame.mouse.get_pos()
        return self.screen.get_rect().collidepoint(mx, my)
