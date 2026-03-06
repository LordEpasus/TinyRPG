from __future__ import annotations

import os
import random
from dataclasses import dataclass

import pygame

from settings import (
    TILE_DIRT,
    TILE_FOREST,
    TILE_GRASS,
    TILE_SIZE,
    TILE_STONE,
    SPROUT_LANDS,
    TINY_SWORDS,
    TREE_DENSITY_CUTOFF,
    TREE_DENSITY_MOD,
)


@dataclass(slots=True)
class ResourceNode:
    node_id: int
    node_kind: str
    resource_type: str
    col: int
    row: int
    wx: float
    wy: float
    amount: int
    max_amount: int
    gather_amount: int
    gather_duration: float
    radius: float
    sprite: pygame.Surface
    mobile: bool = False
    home_wx: float = 0.0
    home_wy: float = 0.0
    target_wx: float = 0.0
    target_wy: float = 0.0
    move_speed: float = 0.0
    wander_timer: float = 0.0

    @property
    def is_depleted(self) -> bool:
        return self.amount <= 0


class ResourceManager:
    _RESOURCE_KEYS = ("gold", "wood", "stone", "food", "meat")

    def __init__(
        self,
        tilemap,
        seed: int = 2025,
        *,
        forbidden_tiles: set[tuple[int, int]] | None = None,
        starting_resources: dict[str, int] | None = None,
    ):
        defaults = {"gold": 320, "wood": 0, "stone": 0, "food": 0, "meat": 0}
        merged = dict(defaults)
        if starting_resources:
            for key in defaults:
                merged[key] = int(starting_resources.get(key, defaults[key]))

        self.resources: dict[str, int] = merged
        self.capacity: dict[str, int] = {
            "gold": 1800,
            "wood": 1800,
            "stone": 1800,
            "food": 1200,
            "meat": 900,
        }
        for key in self._RESOURCE_KEYS:
            self.capacity[key] = max(self.capacity[key], self.resources[key])

        self.gather_bonus: dict[str, float] = {
            "gold": 1.0,
            "wood": 1.0,
            "stone": 1.0,
            "food": 1.0,
            "meat": 1.0,
        }

        self.nodes: list[ResourceNode] = []
        self.wood_node_tiles: set[tuple[int, int]] = set()
        self._forbidden_tiles = set(forbidden_tiles or ())
        self._rng = random.Random(seed + 9011)
        self._next_id = 1
        self._zoom_cache: dict[tuple[int, int], pygame.Surface] = {}
        self._static_nodes_by_row: list[list[ResourceNode]] = [[] for _ in range(tilemap.rows)]
        self._mobile_nodes: list[ResourceNode] = []
        self._sprite_variants = self._load_sprite_variants()
        self._hud_icons = self._load_hud_icons()
        self._generate_nodes(tilemap)
        self._rebuild_node_cache(tilemap.rows)

    @staticmethod
    def _load_best_frame(path: str) -> pygame.Surface | None:
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
            area = bbox.width * bbox.height
            score = bbox.width * 10000 + area
            if score > best_score:
                best = raw
                best_score = score
        return best

    @staticmethod
    def _load_grid_frames(path: str, frame_w: int, frame_h: int) -> list[pygame.Surface]:
        if not os.path.exists(path):
            return []
        sheet = pygame.image.load(path).convert_alpha()
        sw, sh = sheet.get_size()
        out: list[pygame.Surface] = []
        if frame_w <= 0 or frame_h <= 0:
            return out
        for y in range(0, sh - frame_h + 1, frame_h):
            for x in range(0, sw - frame_w + 1, frame_w):
                raw = sheet.subsurface((x, y, frame_w, frame_h)).copy()
                if raw.get_bounding_rect(min_alpha=1).width <= 0:
                    continue
                out.append(raw)
        return out

    def _load_sprite_variants(self) -> dict[str, list[pygame.Surface]]:
        gold_paths = [
            os.path.join(
                TINY_SWORDS,
                "Terrain",
                "Resources",
                "Gold",
                "Gold Stones",
                f"Gold Stone {i}.png",
            )
            for i in range(1, 7)
        ]
        stone_paths = [
            os.path.join(TINY_SWORDS, "Terrain", "Decorations", "Rocks", f"Rock{i}.png")
            for i in range(1, 5)
        ]
        wood_tree_paths = [
            os.path.join(TINY_SWORDS, "Terrain", "Resources", "Wood", "Trees", f"Tree{i}.png")
            for i in range(1, 5)
        ]

        sheep_paths = [
            os.path.join(TINY_SWORDS, "Terrain", "Resources", "Meat", "Sheep", "Sheep_Grass.png"),
            os.path.join(TINY_SWORDS, "Terrain", "Resources", "Meat", "Sheep", "Sheep_Idle.png"),
            os.path.join(TINY_SWORDS, "Terrain", "Resources", "Meat", "Sheep", "Sheep_Move.png"),
        ]
        farm_sheet_paths = [
            os.path.join(SPROUT_LANDS, "Objects", "Basic_Plants.png"),
            os.path.join(SPROUT_LANDS, "Objects", "Basic Plants.png"),
        ]

        golds = [self._load_best_frame(p) for p in gold_paths]
        golds = [g for g in golds if g is not None]
        stones = [self._load_best_frame(p) for p in stone_paths]
        stones = [s for s in stones if s is not None]
        woods = [self._load_best_frame(p) for p in wood_tree_paths]
        woods = [w for w in woods if w is not None]
        sheep = [self._load_best_frame(p) for p in sheep_paths]
        sheep = [s for s in sheep if s is not None]
        farms: list[pygame.Surface] = []
        for path in farm_sheet_paths:
            farms.extend(self._load_grid_frames(path, 32, 32))
        # Keep larger silhouette crops for readability.
        farms = [f for f in farms if f.get_bounding_rect(min_alpha=1).height >= 18]

        def scale_square(surf: pygame.Surface, size: int) -> pygame.Surface:
            return pygame.transform.scale(surf, (size, size))

        def scale_to_height(surf: pygame.Surface, target_h: int) -> pygame.Surface:
            sw, sh = surf.get_size()
            if sh <= 0:
                return surf
            ratio = target_h / sh
            tw = max(1, int(sw * ratio))
            return pygame.transform.scale(surf, (tw, target_h))

        gold_size = int(TILE_SIZE * 0.84)
        wood_height = int(TILE_SIZE * 2.0)
        stone_size = int(TILE_SIZE * 0.88)
        sheep_size = int(TILE_SIZE * 0.86)
        farm_size = int(TILE_SIZE * 0.82)

        variants: dict[str, list[pygame.Surface]] = {
            "gold": [scale_square(g, gold_size) for g in golds],
            "wood": [scale_to_height(w, wood_height) for w in woods],
            "stone": [scale_square(s, stone_size) for s in stones],
            "food": [scale_square(f, farm_size) for f in farms],
            "sheep": [scale_square(s, sheep_size) for s in sheep],
        }

        if not variants["gold"]:
            fb = pygame.Surface((gold_size, gold_size), pygame.SRCALPHA)
            pygame.draw.circle(fb, (238, 196, 54), (gold_size // 2, gold_size // 2), gold_size // 3)
            variants["gold"] = [fb]
        if not variants["wood"]:
            fb = pygame.Surface((int(TILE_SIZE * 0.9), wood_height), pygame.SRCALPHA)
            pygame.draw.rect(
                fb,
                (42, 122, 68),
                pygame.Rect(4, 6, fb.get_width() - 8, int(fb.get_height() * 0.72)),
                border_radius=16,
            )
            pygame.draw.rect(
                fb,
                (104, 74, 50),
                pygame.Rect(fb.get_width() // 2 - 4, int(fb.get_height() * 0.72), 8, int(fb.get_height() * 0.26)),
            )
            variants["wood"] = [fb]
        if not variants["stone"]:
            fb = pygame.Surface((stone_size, stone_size), pygame.SRCALPHA)
            pygame.draw.circle(fb, (120, 128, 136), (stone_size // 2, stone_size // 2), stone_size // 3)
            variants["stone"] = [fb]
        if not variants["food"]:
            fb = pygame.Surface((farm_size, farm_size), pygame.SRCALPHA)
            pygame.draw.rect(
                fb,
                (126, 88, 50),
                pygame.Rect(4, farm_size // 2, farm_size - 8, farm_size // 2 - 2),
                border_radius=6,
            )
            pygame.draw.rect(
                fb,
                (118, 186, 88),
                pygame.Rect(8, 6, farm_size - 16, farm_size // 2 + 4),
                border_radius=8,
            )
            variants["food"] = [fb]
        if not variants["sheep"]:
            fb = pygame.Surface((sheep_size, sheep_size), pygame.SRCALPHA)
            pygame.draw.ellipse(
                fb,
                (225, 225, 230),
                pygame.Rect(4, sheep_size // 3, sheep_size - 8, sheep_size // 2),
            )
            pygame.draw.circle(fb, (68, 68, 76), (sheep_size - 9, sheep_size // 2), sheep_size // 8)
            variants["sheep"] = [fb]

        return variants

    def _load_hud_icons(self) -> dict[str, pygame.Surface]:
        icons: dict[str, pygame.Surface] = {}

        def best_scaled(path: str, size: int) -> pygame.Surface | None:
            frame = self._load_best_frame(path)
            if frame is None:
                return None
            return pygame.transform.scale(frame, (size, size))

        icon_sz = 18
        gold = best_scaled(
            os.path.join(
                TINY_SWORDS,
                "Terrain",
                "Resources",
                "Gold",
                "Gold Stones",
                "Gold Stone 1.png",
            ),
            icon_sz,
        )
        wood = best_scaled(
            os.path.join(
                TINY_SWORDS,
                "Terrain",
                "Resources",
                "Wood",
                "Wood Resource",
                "Wood Resource.png",
            ),
            icon_sz,
        )
        stone = best_scaled(
            os.path.join(TINY_SWORDS, "Terrain", "Decorations", "Rocks", "Rock1.png"),
            icon_sz,
        )
        meat = best_scaled(
            os.path.join(
                TINY_SWORDS,
                "Terrain",
                "Resources",
                "Meat",
                "Meat Resource",
                "Meat Resource.png",
            ),
            icon_sz,
        )
        food = best_scaled(
            os.path.join(SPROUT_LANDS, "Objects", "Basic_Plants.png"),
            icon_sz,
        )

        def fallback(color: tuple[int, int, int]) -> pygame.Surface:
            fb = pygame.Surface((icon_sz, icon_sz), pygame.SRCALPHA)
            pygame.draw.circle(fb, color, (icon_sz // 2, icon_sz // 2), icon_sz // 2 - 2)
            return fb

        icons["gold"] = gold or fallback((244, 207, 77))
        icons["wood"] = wood or fallback((172, 126, 84))
        icons["stone"] = stone or fallback((172, 184, 196))
        icons["food"] = food or fallback((150, 198, 106))
        icons["meat"] = meat or fallback((208, 90, 82))
        return icons

    def _generate_nodes(self, tilemap) -> None:
        stone_tiles: list[tuple[int, int]] = []
        forest_tiles: list[tuple[int, int]] = []
        graze_tiles: list[tuple[int, int]] = []
        farm_tiles: list[tuple[int, int]] = []

        for row in range(tilemap.rows):
            for col in range(tilemap.cols):
                if self._is_forbidden_tile(col, row):
                    continue
                tt = tilemap.tiles[row][col]
                if tt == TILE_STONE:
                    stone_tiles.append((col, row))
                elif tt == TILE_FOREST and self._is_tree_density_slot(col, row):
                    forest_tiles.append((col, row))
                elif tt == TILE_DIRT:
                    farm_tiles.append((col, row))
                    graze_tiles.append((col, row))
                elif tt == TILE_GRASS:
                    graze_tiles.append((col, row))

        occupied: list[tuple[int, int]] = []
        self._spawn_ore_nodes(stone_tiles, occupied=occupied)
        self._ensure_min_ore("gold", 22)
        self._ensure_min_ore("stone", 22)
        self._spawn_wood_nodes(forest_tiles, occupied=occupied)
        self._spawn_farm_nodes(farm_tiles, occupied=occupied)
        self._spawn_sheep_nodes(graze_tiles, tilemap, occupied=occupied)

    def _spawn_ore_nodes(
        self,
        stone_tiles: list[tuple[int, int]],
        *,
        occupied: list[tuple[int, int]],
    ) -> None:
        if not stone_tiles:
            return

        picks = stone_tiles[:]
        self._rng.shuffle(picks)
        for col, row in picks:
            if self._rng.random() < 0.35:
                resource_type = "gold"
                amount = 180 + self._rng.randint(-24, 34)
                gather_amount = 8
                gather_duration = 1.95
            else:
                resource_type = "stone"
                amount = 150 + self._rng.randint(-20, 28)
                gather_amount = 9
                gather_duration = 1.7

            self._append_node(
                resource_type=resource_type,
                col=col,
                row=row,
                amount=amount,
                gather_amount=gather_amount,
                gather_duration=gather_duration,
            )
            occupied.append((col, row))

    def _set_ore_profile(self, node: ResourceNode, resource_type: str) -> None:
        node.resource_type = resource_type
        if resource_type == "gold":
            node.amount = max(node.amount, 170 + self._rng.randint(-16, 30))
            node.max_amount = node.amount
            node.gather_amount = 8
            node.gather_duration = 1.95
            variants = self._sprite_variants["gold"]
        else:
            node.amount = max(node.amount, 140 + self._rng.randint(-14, 26))
            node.max_amount = node.amount
            node.gather_amount = 9
            node.gather_duration = 1.7
            variants = self._sprite_variants["stone"]
        if variants:
            node.sprite = variants[(node.col * 13 + node.row * 17 + node.node_id) % len(variants)]

    def _ensure_min_ore(self, resource_type: str, min_count: int) -> None:
        if resource_type not in ("gold", "stone"):
            return
        current = [n for n in self.nodes if n.node_kind == "resource" and n.resource_type == resource_type]
        if len(current) >= min_count:
            return

        candidates = [
            n
            for n in self.nodes
            if n.node_kind == "resource" and n.resource_type in ("gold", "stone")
        ]
        self._rng.shuffle(candidates)
        for node in candidates:
            if len(current) >= min_count:
                break
            if node.resource_type == resource_type:
                continue
            self._set_ore_profile(node, resource_type)
            current.append(node)

    def _spawn_wood_nodes(
        self,
        forest_tiles: list[tuple[int, int]],
        *,
        occupied: list[tuple[int, int]],
    ) -> None:
        if not forest_tiles:
            return
        for col, row in forest_tiles:
            if self._is_too_close(col, row, occupied, min_dist=1):
                continue
            amount = 100 + self._rng.randint(-20, 24)
            self._append_node(
                resource_type="wood",
                col=col,
                row=row,
                amount=amount,
                gather_amount=10,
                gather_duration=1.22,
            )
            occupied.append((col, row))
            self.wood_node_tiles.add((col, row))

    def _spawn_sheep_nodes(
        self,
        graze_tiles: list[tuple[int, int]],
        tilemap,
        *,
        occupied: list[tuple[int, int]],
    ) -> None:
        if not graze_tiles:
            return

        centers = graze_tiles[:]
        self._rng.shuffle(centers)
        flock_count = 0

        for center_col, center_row in centers:
            if flock_count >= 8:
                break
            if self._is_too_close(center_col, center_row, occupied, min_dist=6):
                continue

            flock_size = self._rng.randint(3, 5)
            placed = 0
            for _ in range(26):
                col = center_col + self._rng.randint(-2, 2)
                row = center_row + self._rng.randint(-2, 2)
                if not (0 <= col < tilemap.cols and 0 <= row < tilemap.rows):
                    continue
                if self._is_forbidden_tile(col, row):
                    continue
                if tilemap.tiles[row][col] not in (TILE_GRASS, TILE_DIRT):
                    continue
                if self._is_too_close(col, row, occupied, min_dist=1):
                    continue
                amount = 70 + self._rng.randint(-8, 15)
                self._append_node(
                    resource_type="meat",
                    col=col,
                    row=row,
                    amount=amount,
                    gather_amount=7,
                    gather_duration=1.35,
                    node_kind="sheep",
                    mobile=True,
                    move_speed=38 + self._rng.random() * 10,
                )
                occupied.append((col, row))
                placed += 1
                if placed >= flock_size:
                    break

            if placed > 0:
                flock_count += 1

    def _spawn_farm_nodes(
        self,
        farm_tiles: list[tuple[int, int]],
        *,
        occupied: list[tuple[int, int]],
    ) -> None:
        if not farm_tiles:
            return

        picks = farm_tiles[:]
        self._rng.shuffle(picks)
        placed = 0
        target_count = max(14, len(farm_tiles) // 9)

        for col, row in picks:
            if placed >= target_count:
                break
            if self._is_too_close(col, row, occupied, min_dist=2):
                continue
            # Cluster farms into some dirt zones so it looks intentional.
            if (col * 5 + row * 11) % 7 not in (0, 1):
                continue
            amount = 96 + self._rng.randint(-14, 22)
            self._append_node(
                resource_type="food",
                col=col,
                row=row,
                amount=amount,
                gather_amount=9,
                gather_duration=1.05,
                node_kind="farm",
                mobile=False,
            )
            occupied.append((col, row))
            placed += 1

    @staticmethod
    def _is_tree_density_slot(col: int, row: int) -> bool:
        density_mod = max(1, TREE_DENSITY_MOD)
        density_cutoff = max(0, min(density_mod, TREE_DENSITY_CUTOFF))
        return (col * 7 + row * 13) % density_mod < density_cutoff

    def _is_forbidden_tile(self, col: int, row: int) -> bool:
        return (col, row) in self._forbidden_tiles

    def _is_too_close(
        self,
        col: int,
        row: int,
        occupied: list[tuple[int, int]],
        *,
        min_dist: int,
    ) -> bool:
        for oc, orow in occupied:
            dx = col - oc
            dy = row - orow
            if dx * dx + dy * dy < min_dist * min_dist:
                return True
        return False

    def _append_node(
        self,
        *,
        resource_type: str,
        col: int,
        row: int,
        amount: int,
        gather_amount: int,
        gather_duration: float,
        node_kind: str = "resource",
        mobile: bool = False,
        move_speed: float = 0.0,
    ) -> None:
        sprite_key = "sheep" if node_kind == "sheep" else resource_type
        variants = self._sprite_variants[sprite_key]
        sprite = variants[(col * 13 + row * 17) % len(variants)]

        wx = col * TILE_SIZE + TILE_SIZE // 2
        if resource_type == "wood":
            # Keep gather approach target inside the same forest tile for path stability.
            wy = row * TILE_SIZE + int(TILE_SIZE * 0.84)
            radius = max(16, int(TILE_SIZE * 0.35))
        elif resource_type == "food":
            wy = (row + 1) * TILE_SIZE - 3
            radius = max(14, int(TILE_SIZE * 0.30))
        elif resource_type == "meat":
            wy = (row + 1) * TILE_SIZE - 6
            radius = max(14, int(TILE_SIZE * 0.33))
        else:
            wy = (row + 1) * TILE_SIZE - 3
            radius = max(15, int(sprite.get_width() * 0.38))

        amount = max(1, int(amount))

        self.nodes.append(
            ResourceNode(
                node_id=self._next_id,
                node_kind=node_kind,
                resource_type=resource_type,
                col=col,
                row=row,
                wx=wx,
                wy=wy,
                amount=amount,
                max_amount=amount,
                gather_amount=gather_amount,
                gather_duration=gather_duration,
                radius=radius,
                sprite=sprite,
                mobile=mobile,
                home_wx=wx,
                home_wy=wy,
                target_wx=wx,
                target_wy=wy,
                move_speed=float(move_speed),
                wander_timer=self._rng.uniform(0.8, 2.4) if mobile else 0.0,
            )
        )
        self._next_id += 1

    def _rebuild_node_cache(self, rows: int) -> None:
        self._static_nodes_by_row = [[] for _ in range(rows)]
        self._mobile_nodes = []
        for node in self.nodes:
            if node.mobile:
                self._mobile_nodes.append(node)
                continue
            if 0 <= node.row < rows:
                self._static_nodes_by_row[node.row].append(node)

    def update(self, dt: float, tilemap, blocked_tiles: set[tuple[int, int]] | None = None) -> None:
        blocked = blocked_tiles or set()
        for node in self._mobile_nodes:
            if node.amount <= 0:
                continue

            node.wander_timer -= dt
            dx = node.target_wx - node.wx
            dy = node.target_wy - node.wy
            dist2 = dx * dx + dy * dy
            if node.wander_timer <= 0.0 or dist2 < 20.0:
                self._choose_new_wander_target(node, tilemap, blocked)
                dx = node.target_wx - node.wx
                dy = node.target_wy - node.wy
                dist2 = dx * dx + dy * dy

            if dist2 <= 0.0:
                continue

            dist = dist2 ** 0.5
            step = min(dist, max(8.0, node.move_speed) * dt)
            nx = node.wx + dx / dist * step
            ny = node.wy + dy / dist * step
            nc, nr = tilemap.world_to_tile(nx, ny)
            if not (0 <= nc < tilemap.cols and 0 <= nr < tilemap.rows):
                self._choose_new_wander_target(node, tilemap, blocked)
                continue
            if (nc, nr) in blocked or tilemap.get_tile(nc, nr) not in (TILE_GRASS, TILE_DIRT):
                self._choose_new_wander_target(node, tilemap, blocked)
                continue

            node.wx = nx
            node.wy = ny
            node.col = nc
            node.row = nr

    def _choose_new_wander_target(self, node: ResourceNode, tilemap, blocked: set[tuple[int, int]]) -> None:
        for _ in range(20):
            tx = node.home_wx + self._rng.uniform(-TILE_SIZE * 3.0, TILE_SIZE * 3.0)
            ty = node.home_wy + self._rng.uniform(-TILE_SIZE * 2.0, TILE_SIZE * 2.0)
            tc, tr = tilemap.world_to_tile(tx, ty)
            if not (0 <= tc < tilemap.cols and 0 <= tr < tilemap.rows):
                continue
            if (tc, tr) in blocked:
                continue
            if tilemap.get_tile(tc, tr) not in (TILE_GRASS, TILE_DIRT):
                continue
            node.target_wx = tx
            node.target_wy = ty
            node.wander_timer = self._rng.uniform(1.2, 3.0)
            return

        node.target_wx = node.home_wx
        node.target_wy = node.home_wy
        node.wander_timer = self._rng.uniform(1.2, 2.8)

    def occupied_tiles(self, *, include_depleted: bool = False) -> set[tuple[int, int]]:
        out: set[tuple[int, int]] = set()
        for node in self.nodes:
            if include_depleted or not node.is_depleted:
                out.add((node.col, node.row))
        return out

    def node_at_world(self, wx: float, wy: float) -> ResourceNode | None:
        best: ResourceNode | None = None
        best_dist2 = 10e9
        for node in self.nodes:
            if node.is_depleted:
                continue
            dx = wx - node.wx
            dy = wy - node.wy
            dist2 = dx * dx + dy * dy
            if dist2 <= node.radius * node.radius and dist2 < best_dist2:
                best = node
                best_dist2 = dist2
        return best

    def nearest_node(
        self,
        resource_type: str,
        wx: float,
        wy: float,
    ) -> ResourceNode | None:
        best: ResourceNode | None = None
        best_dist2 = 10e12
        for node in self.nodes:
            if node.is_depleted or node.resource_type != resource_type:
                continue
            dx = wx - node.wx
            dy = wy - node.wy
            dist2 = dx * dx + dy * dy
            if dist2 < best_dist2:
                best = node
                best_dist2 = dist2
        return best

    def set_gather_bonus(self, resource_type: str, multiplier: float) -> None:
        if resource_type not in self.gather_bonus:
            return
        self.gather_bonus[resource_type] = max(0.1, float(multiplier))

    def set_capacities(self, capacities: dict[str, int]) -> None:
        for key in self._RESOURCE_KEYS:
            if key in capacities:
                self.capacity[key] = max(1, int(capacities[key]))
            self.capacity[key] = max(self.capacity[key], self.resources.get(key, 0))

    def can_afford(self, costs: dict[str, int]) -> bool:
        for key, value in costs.items():
            if value <= 0:
                continue
            if self.resources.get(key, 0) < int(value):
                return False
        return True

    def spend(self, costs: dict[str, int]) -> bool:
        if not self.can_afford(costs):
            return False
        for key, value in costs.items():
            if value > 0:
                self.resources[key] = max(0, self.resources.get(key, 0) - int(value))
        return True

    def consume(self, resource_type: str, amount: int) -> bool:
        value = max(0, int(amount))
        if self.resources.get(resource_type, 0) < value:
            return False
        self.resources[resource_type] -= value
        return True

    def gain(self, resource_type: str, amount: int) -> int:
        if resource_type not in self.resources:
            return 0
        val = max(0, int(amount))
        if val <= 0:
            return 0
        cap_left = max(0, self.capacity.get(resource_type, 999999) - self.resources.get(resource_type, 0))
        if cap_left <= 0:
            return 0
        got = min(cap_left, val)
        self.resources[resource_type] = self.resources.get(resource_type, 0) + got
        return got

    def drain_node(self, node: ResourceNode, requested_amount: int) -> int:
        if node is None or node.is_depleted:
            return 0
        req = max(0, int(requested_amount))
        if req <= 0:
            return 0
        take = min(node.amount, req)
        if take <= 0:
            return 0
        node.amount -= take
        return take

    def harvest(self, node: ResourceNode, requested_amount: int) -> int:
        if node.is_depleted:
            return 0
        resource_key = node.resource_type
        cap_left = max(0, self.capacity.get(resource_key, 999999) - self.resources.get(resource_key, 0))
        if cap_left <= 0:
            return 0

        req = max(0, int(requested_amount))
        if req <= 0:
            return 0

        bonus = max(0.1, float(self.gather_bonus.get(resource_key, 1.0)))
        max_take_by_cap = max(1, int(cap_left / bonus))
        take = min(node.amount, req, max_take_by_cap)
        if take <= 0:
            return 0

        node.amount -= take
        gained = max(1, int(round(take * bonus)))
        gained = min(cap_left, gained)
        self.resources[resource_key] = self.resources.get(resource_key, 0) + gained
        return gained

    def draw_nodes(self, screen: pygame.Surface, camera) -> None:
        c0, r0, c1, r1 = camera.get_visible_tile_range()
        zoom = camera.zoom
        zoom_key = int(round(zoom * 1000))
        sparse_wood = zoom < 0.54
        sparse_food = zoom < 0.48

        visible: list[ResourceNode] = []
        row_start = max(0, r0)
        row_end = min(len(self._static_nodes_by_row) - 1, r1)
        for row in range(row_start, row_end + 1):
            row_nodes = self._static_nodes_by_row[row]
            if not row_nodes:
                continue
            for node in row_nodes:
                if node.amount <= 0:
                    continue
                if node.col < c0 or node.col > c1:
                    continue
                if sparse_wood and node.resource_type == "wood":
                    # Wood nodes are numerous; thin out at far zoom levels.
                    if (node.col * 7 + node.row * 13) % 3 != 0:
                        continue
                if sparse_food and node.resource_type in ("food", "meat"):
                    if (node.col * 11 + node.row * 5) % 2 != 0:
                        continue
                visible.append(node)

        for node in self._mobile_nodes:
            if node.amount <= 0:
                continue
            if node.col < c0 or node.col > c1 or node.row < r0 or node.row > r1:
                continue
            if sparse_food and node.resource_type in ("food", "meat"):
                if (node.col * 11 + node.row * 5) % 2 != 0:
                    continue
            visible.append(node)

        blit_list: list[tuple[pygame.Surface, tuple[int, int]]] = []
        bars: list[tuple[int, int, int, int, float, tuple[int, int, int]]] = []
        w2s = camera.world_to_screen
        for node in visible:
            base = node.sprite
            if zoom == 1.0:
                surf = base
            else:
                key = (id(base), zoom_key)
                surf = self._zoom_cache.get(key)
                if surf is None:
                    w = max(1, int(base.get_width() * zoom))
                    h = max(1, int(base.get_height() * zoom))
                    surf = pygame.transform.scale(base, (w, h))
                    self._zoom_cache[key] = surf

            sx, sy = w2s((node.wx, node.wy))
            draw_x = int(sx) - surf.get_width() // 2
            draw_y = int(sy) - surf.get_height()
            blit_list.append((surf, (draw_x, draw_y)))

            if node.resource_type in ("gold", "stone", "food", "meat") and camera.zoom >= 0.55:
                bw = max(14, int(26 * zoom))
                bh = max(2, int(3 * zoom))
                bx = int(sx) - bw // 2
                by = draw_y - bh - max(2, int(4 * zoom))
                ratio = 0.0 if node.max_amount <= 0 else node.amount / node.max_amount
                ratio = max(0.0, min(1.0, ratio))
                if node.resource_type == "gold":
                    color = (238, 196, 54)
                elif node.resource_type == "stone":
                    color = (168, 182, 198)
                elif node.resource_type == "food":
                    color = (146, 204, 98)
                else:
                    color = (210, 98, 88)
                bars.append((bx, by, bw, bh, ratio, color))
        if blit_list:
            screen.blits(blit_list)
        for bx, by, bw, bh, ratio, color in bars:
            pygame.draw.rect(screen, (0, 0, 0), (bx, by, bw, bh))
            fill_w = max(1, int((bw - 2) * ratio))
            pygame.draw.rect(screen, color, (bx + 1, by + 1, fill_w, max(1, bh - 2)))

    def draw_hud(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        lines = [
            ("gold", "Altin", (244, 207, 77)),
            ("wood", "Odun", (190, 136, 88)),
            ("stone", "Tas", (184, 196, 208)),
            ("food", "Yemek", (146, 204, 98)),
            ("meat", "Et", (212, 108, 96)),
        ]

        row_w = 198
        row_h = 24
        x = screen.get_width() - row_w - 12
        y = 10
        for key, label, color in lines:
            value = self.resources.get(key, 0)
            cap = max(1, self.capacity.get(key, value))
            ratio = max(0.0, min(1.0, value / cap))

            bg = pygame.Surface((row_w, row_h), pygame.SRCALPHA)
            pygame.draw.rect(bg, (10, 14, 20, 196), bg.get_rect(), border_radius=8)
            pygame.draw.rect(bg, (64, 88, 108, 230), bg.get_rect(), 1, border_radius=8)
            screen.blit(bg, (x, y))

            bar_rect = pygame.Rect(x + 62, y + row_h - 7, row_w - 70, 3)
            pygame.draw.rect(screen, (34, 42, 52), bar_rect, border_radius=2)
            fill_w = max(1, int((bar_rect.width - 2) * ratio))
            pygame.draw.rect(
                screen,
                color,
                (bar_rect.x + 1, bar_rect.y + 1, fill_w, max(1, bar_rect.height - 2)),
                border_radius=2,
            )

            icon = self._hud_icons.get(key)
            if icon is not None:
                icon_y = y + (row_h - icon.get_height()) // 2
                screen.blit(icon, (x + 4, icon_y))

            label_surf = font.render(label, True, color)
            value_surf = font.render(f"{value}/{cap}", True, (232, 236, 242))
            screen.blit(label_surf, (x + 24, y + 2))
            screen.blit(value_surf, (x + row_w - value_surf.get_width() - 6, y + 2))

            y += row_h + 5
