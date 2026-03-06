from __future__ import annotations

import os

import pygame

from settings import TINY_SWORDS, TILE_SIZE, WHITE


class Building:
    TYPE_BARRACKS = "barracks"
    TYPE_ARCHERY = "archery"
    TYPE_CASTLE = "castle"
    TYPE_SMITHY = "smithy"
    TYPE_HOUSE1 = "house1"
    TYPE_HOUSE2 = "house2"
    TYPE_HOUSE3 = "house3"
    TYPE_TOWER = "tower"

    # Backward alias for earlier saves/code paths.
    TYPE_MONASTERY = TYPE_SMITHY

    _FILE_BY_TYPE = {
        TYPE_BARRACKS: "Barracks.png",
        TYPE_ARCHERY: "Archery.png",
        TYPE_CASTLE: "Castle.png",
        TYPE_SMITHY: "Monastery.png",
        TYPE_HOUSE1: "House1.png",
        TYPE_HOUSE2: "House2.png",
        TYPE_HOUSE3: "House3.png",
        TYPE_TOWER: "Tower.png",
    }

    _DISPLAY_NAME_BY_TYPE = {
        TYPE_BARRACKS: "Barracks",
        TYPE_ARCHERY: "Archery",
        TYPE_CASTLE: "Castle",
        TYPE_SMITHY: "Smithy",
        TYPE_HOUSE1: "House 1",
        TYPE_HOUSE2: "House 2",
        TYPE_HOUSE3: "House 3",
        TYPE_TOWER: "Tower",
    }

    _FOOTPRINT_BY_TYPE = {
        TYPE_BARRACKS: (3, 3),
        TYPE_ARCHERY: (3, 3),
        TYPE_CASTLE: (5, 3),
        TYPE_SMITHY: (3, 4),
        TYPE_HOUSE1: (2, 2),
        TYPE_HOUSE2: (2, 2),
        TYPE_HOUSE3: (2, 2),
        TYPE_TOWER: (2, 3),
    }

    _BUILD_COST_BY_TYPE = {
        TYPE_BARRACKS: {"wood": 260, "stone": 180, "gold": 120},
        TYPE_ARCHERY: {"wood": 240, "stone": 120, "gold": 130},
        TYPE_CASTLE: {"wood": 450, "stone": 350, "gold": 260},
        TYPE_SMITHY: {"wood": 240, "stone": 240, "gold": 180},
        TYPE_HOUSE1: {"wood": 120, "stone": 60, "gold": 40},
        TYPE_HOUSE2: {"wood": 120, "stone": 60, "gold": 40},
        TYPE_HOUSE3: {"wood": 120, "stone": 60, "gold": 40},
        TYPE_TOWER: {"wood": 170, "stone": 250, "gold": 90},
    }

    # Worker construction times (seconds) by building scale/type.
    _CONSTRUCTION_TIME_BY_TYPE = {
        TYPE_HOUSE1: 8.5,
        TYPE_HOUSE2: 8.5,
        TYPE_HOUSE3: 8.5,
        TYPE_BARRACKS: 14.0,
        TYPE_ARCHERY: 13.0,
        TYPE_SMITHY: 15.0,
        TYPE_TOWER: 12.0,
        TYPE_CASTLE: 23.0,
    }

    _STORAGE_BONUS_BY_TYPE = {
        TYPE_HOUSE1: 550,
        TYPE_HOUSE2: 550,
        TYPE_HOUSE3: 550,
        TYPE_TOWER: 380,
    }

    _GARRISON_CAP_BY_TYPE = {
        TYPE_TOWER: 3,
    }

    _PRODUCTION_BY_TYPE = {
        TYPE_BARRACKS: [
            {
                "kind": "unit",
                "unit_class": "warrior",
                "label": "Warrior",
                "required_age": "dark",
                "build_time": 5.1,
                "gold_cost": 95,
                "wood_cost": 15,
                "stone_cost": 10,
            },
            {
                "kind": "unit",
                "unit_class": "archer",
                "label": "Archer",
                "required_age": "feudal",
                "build_time": 5.8,
                "gold_cost": 120,
                "wood_cost": 22,
                "stone_cost": 10,
            },
            {
                "kind": "unit",
                "unit_class": "lancer",
                "label": "Lancer",
                "required_age": "castle",
                "build_time": 6.6,
                "gold_cost": 150,
                "wood_cost": 20,
                "stone_cost": 25,
            },
        ],
        TYPE_ARCHERY: [
            {
                "kind": "unit",
                "unit_class": "archer",
                "label": "Archer",
                "required_age": "feudal",
                "build_time": 5.8,
                "gold_cost": 120,
                "wood_cost": 22,
                "stone_cost": 10,
            },
        ],
        TYPE_CASTLE: [
            {
                "kind": "unit",
                "unit_class": "lancer",
                "label": "Lancer",
                "required_age": "castle",
                "build_time": 6.6,
                "gold_cost": 150,
                "wood_cost": 20,
                "stone_cost": 25,
            },
        ],
        TYPE_SMITHY: [
            {
                "kind": "unit",
                "unit_class": "monk",
                "label": "Monk Builder",
                "required_age": "feudal",
                "build_time": 6.2,
                "gold_cost": 110,
                "wood_cost": 20,
                "stone_cost": 20,
            },
            {
                "kind": "tool",
                "tool_id": "tool_01",
                "label": "Axe Tools",
                "required_age": "dark",
                "build_time": 6.0,
                "gold_cost": 90,
                "wood_cost": 65,
                "stone_cost": 40,
            },
            {
                "kind": "tool",
                "tool_id": "tool_02",
                "label": "Hammer Tools",
                "required_age": "feudal",
                "build_time": 6.8,
                "gold_cost": 95,
                "wood_cost": 40,
                "stone_cost": 70,
            },
            {
                "kind": "tool",
                "tool_id": "tool_03",
                "label": "Battle Tools",
                "required_age": "feudal",
                "build_time": 7.0,
                "gold_cost": 120,
                "wood_cost": 50,
                "stone_cost": 55,
            },
            {
                "kind": "tool",
                "tool_id": "tool_04",
                "label": "Mine Tools",
                "required_age": "castle",
                "build_time": 7.4,
                "gold_cost": 110,
                "wood_cost": 35,
                "stone_cost": 85,
            },
        ],
        TYPE_TOWER: [],
    }

    @classmethod
    def footprint_size(cls, building_type: str) -> tuple[int, int]:
        return cls._FOOTPRINT_BY_TYPE.get(building_type, (2, 2))

    @classmethod
    def build_cost(cls, building_type: str) -> dict[str, int]:
        return dict(cls._BUILD_COST_BY_TYPE.get(building_type, {}))

    @classmethod
    def buildable_types(cls) -> list[str]:
        return [
            cls.TYPE_HOUSE1,
            cls.TYPE_HOUSE2,
            cls.TYPE_HOUSE3,
            cls.TYPE_BARRACKS,
            cls.TYPE_ARCHERY,
            cls.TYPE_SMITHY,
            cls.TYPE_TOWER,
            cls.TYPE_CASTLE,
        ]

    @classmethod
    def construction_time(cls, building_type: str) -> float:
        return float(cls._CONSTRUCTION_TIME_BY_TYPE.get(building_type, 10.0))

    def __init__(
        self,
        wx: float,
        wy: float,
        *,
        building_type: str,
        civilization: str = "Blue",
        kingdom_id: str | None = None,
        max_hp: int = 1600,
        start_progress: float = 1.0,
    ):
        self.world_pos = pygame.math.Vector2(wx, wy)  # bottom-center anchor
        self.building_type = building_type
        self.civilization = civilization
        self.asset_color = civilization
        self.kingdom_id = kingdom_id or civilization
        self.selected = False
        self.max_hp = max(1, int(max_hp))
        self.build_time_total = self.construction_time(building_type)
        self.build_progress = max(0.0, min(1.0, float(start_progress)))
        self.hp = max(1, int(self.max_hp * max(0.12, self.build_progress)))
        self.queue: list[dict[str, float | str | int]] = []
        self.max_queue = 5
        self.garrisoned_archers = 0
        self.is_dock = False
        self.is_dead = False

        self._sprite = self._load_sprite()
        self._sprite_zoom_cache: dict[int, pygame.Surface] = {}

    @property
    def can_produce(self) -> bool:
        if self.is_dead:
            return False
        return self.is_complete and bool(self.production_options())

    @property
    def is_complete(self) -> bool:
        return self.build_progress >= 0.999

    @property
    def under_construction(self) -> bool:
        return not self.is_complete

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME_BY_TYPE.get(self.building_type, self.building_type.title())

    @property
    def storage_bonus(self) -> int:
        if self.is_dead or not self.is_complete:
            return 0
        return int(self._STORAGE_BONUS_BY_TYPE.get(self.building_type, 0))

    @property
    def can_garrison_archers(self) -> bool:
        return (not self.is_dead) and self.is_complete and self.garrison_capacity > 0

    @property
    def garrison_capacity(self) -> int:
        return int(self._GARRISON_CAP_BY_TYPE.get(self.building_type, 0))

    @property
    def has_garrison_space(self) -> bool:
        return self.garrisoned_archers < self.garrison_capacity

    def production_options(self) -> list[dict[str, str | float | int]]:
        if self.is_dead:
            return []
        base = self._PRODUCTION_BY_TYPE.get(self.building_type, [])
        options = [dict(option) for option in base]
        if self.building_type == self.TYPE_TOWER and self.is_dock and self.is_complete:
            options.append(
                {
                    "kind": "ship",
                    "unit_class": "ship",
                    "label": "Ship",
                    "required_age": "feudal",
                    "build_time": 10.0,
                    "gold_cost": 180,
                    "wood_cost": 120,
                    "stone_cost": 40,
                }
            )
        return options

    @property
    def queue_size(self) -> int:
        return len(self.queue)

    def _load_sprite(self) -> pygame.Surface:
        file_name = self._FILE_BY_TYPE.get(self.building_type, "House1.png")
        path = os.path.join(TINY_SWORDS, "Buildings", f"{self.asset_color} Buildings", file_name)
        if os.path.exists(path):
            return pygame.image.load(path).convert_alpha()
        fb = pygame.Surface((TILE_SIZE * 2, TILE_SIZE * 2), pygame.SRCALPHA)
        fb.fill((120, 140, 170, 220))
        pygame.draw.rect(fb, (30, 30, 36), fb.get_rect(), 2)
        return fb

    def enqueue_option(self, option: dict[str, str | float | int]) -> bool:
        if not self.can_produce or len(self.queue) >= self.max_queue:
            return False
        item = dict(option)
        item["build_time"] = max(0.2, float(item.get("build_time", 3.0)))
        item["remaining"] = float(item["build_time"])
        item["kind"] = str(item.get("kind", "unit"))
        self.queue.append(item)
        return True

    def apply_construction_work(self, work_seconds: float) -> bool:
        if self.is_dead or self.is_complete:
            return False
        ratio_gain = max(0.0, float(work_seconds)) / max(0.001, self.build_time_total)
        self.build_progress = min(1.0, self.build_progress + ratio_gain)
        self.hp = max(1, int(self.max_hp * max(0.12, self.build_progress)))
        if self.is_complete:
            self.hp = self.max_hp
            return True
        return False

    def update(self, dt: float) -> list[dict[str, str | int | float]]:
        finished_events: list[dict[str, str | int | float]] = []
        if self.is_dead:
            return finished_events
        if not self.is_complete:
            return finished_events
        if not self.queue:
            return finished_events

        self.queue[0]["remaining"] = float(self.queue[0]["remaining"]) - dt
        while self.queue and float(self.queue[0]["remaining"]) <= 0.0:
            done = self.queue.pop(0)
            overflow = float(done.get("remaining", 0.0))
            event = {
                key: value
                for key, value in done.items()
                if key not in ("remaining", "build_time")
            }
            finished_events.append(event)
            if self.queue:
                self.queue[0]["remaining"] = float(self.queue[0]["remaining"]) + overflow
        return finished_events

    def current_queue_progress(self) -> float:
        if not self.queue:
            return 0.0
        rem = float(self.queue[0]["remaining"])
        total = max(0.001, float(self.queue[0]["build_time"]))
        return max(0.0, min(1.0, 1.0 - rem / total))

    def world_rect(self) -> pygame.Rect:
        w, h = self._sprite.get_size()
        return pygame.Rect(
            int(self.world_pos.x - w / 2),
            int(self.world_pos.y - h),
            w,
            h,
        )

    def contains_point(self, wx: float, wy: float) -> bool:
        if self.is_dead:
            return False
        return self.world_rect().collidepoint(wx, wy)

    def footprint_tiles(self, tilemap) -> set[tuple[int, int]]:
        fw, fh = self._FOOTPRINT_BY_TYPE.get(self.building_type, (2, 2))
        anchor_col, anchor_row = tilemap.world_to_tile(self.world_pos.x, self.world_pos.y)
        start_col = anchor_col - fw // 2
        start_row = anchor_row - fh + 1
        out: set[tuple[int, int]] = set()
        for row in range(start_row, start_row + fh):
            for col in range(start_col, start_col + fw):
                if 0 <= col < tilemap.cols and 0 <= row < tilemap.rows:
                    out.add((col, row))
        return out

    def spawn_anchor(self) -> tuple[float, float]:
        return self.world_pos.x, self.world_pos.y + TILE_SIZE * 0.6

    def garrison_archer(self) -> bool:
        if self.is_dead:
            return False
        if not self.can_garrison_archers or not self.has_garrison_space:
            return False
        self.garrisoned_archers += 1
        return True

    def pop_garrison_archer(self) -> bool:
        if self.is_dead:
            return False
        if self.garrisoned_archers <= 0:
            return False
        self.garrisoned_archers -= 1
        return True

    def take_damage(self, amount: float) -> bool:
        if self.is_dead:
            return False
        dmg = max(0.0, float(amount))
        if dmg <= 0.0:
            return False
        self.hp = max(0.0, self.hp - dmg)
        if self.hp <= 0.0:
            self.hp = 0.0
            self.is_dead = True
            self.selected = False
            self.queue.clear()
            self.garrisoned_archers = 0
            return True
        return False

    def draw(self, screen: pygame.Surface, camera) -> None:
        if self.is_dead:
            return
        zoom = camera.zoom
        base = self._sprite
        if zoom == 1.0:
            sprite = base
        else:
            key = int(round(zoom * 1000))
            sprite = self._sprite_zoom_cache.get(key)
            if sprite is None:
                w = max(1, int(base.get_width() * zoom))
                h = max(1, int(base.get_height() * zoom))
                sprite = pygame.transform.scale(base, (w, h))
                self._sprite_zoom_cache[key] = sprite

        sx, sy = camera.world_to_screen((self.world_pos.x, self.world_pos.y))
        x = int(sx) - sprite.get_width() // 2
        y = int(sy) - sprite.get_height()
        if self.under_construction:
            ghost = sprite.copy()
            ghost.fill((168, 152, 138, 156), special_flags=pygame.BLEND_RGBA_MULT)
            screen.blit(ghost, (x, y))
        else:
            screen.blit(sprite, (x, y))

        if self.selected:
            ring_w = max(18, int(TILE_SIZE * 1.8 * zoom))
            ring_h = max(8, int(TILE_SIZE * 0.45 * zoom))
            rx = int(sx) - ring_w // 2
            ry = int(sy) - ring_h // 2
            rr = pygame.Rect(rx, ry, ring_w, ring_h)
            pygame.draw.ellipse(screen, (0, 0, 0), rr, 3)
            pygame.draw.ellipse(screen, WHITE, rr, 2)

        if self.can_garrison_archers and self.garrisoned_archers > 0:
            label = f"A{self.garrisoned_archers}/{self.garrison_capacity}"
            font = pygame.font.SysFont("monospace", max(9, int(11 * zoom)))
            surf = font.render(label, True, (238, 220, 120))
            bg = pygame.Surface((surf.get_width() + 6, surf.get_height() + 4), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 150))
            tx = int(sx) - bg.get_width() // 2
            ty = y - bg.get_height() - 4
            screen.blit(bg, (tx, ty))
            screen.blit(surf, (tx + 3, ty + 2))

        if self.selected or self.under_construction:
            bar_w = max(28, int(TILE_SIZE * 1.1 * zoom))
            bar_h = max(3, int(5 * zoom))
            bx = int(sx) - bar_w // 2
            by = y - bar_h - max(4, int(5 * zoom))
            ratio = max(0.0, min(1.0, self.hp / self.max_hp))
            pygame.draw.rect(screen, (0, 0, 0), (bx, by, bar_w, bar_h))
            pygame.draw.rect(screen, (120, 44, 44), (bx + 1, by + 1, bar_w - 2, max(1, bar_h - 2)))
            pygame.draw.rect(
                screen,
                (62, 200, 74),
                (bx + 1, by + 1, max(1, int((bar_w - 2) * ratio)), max(1, bar_h - 2)),
            )

        if self.under_construction:
            bw = max(30, int(TILE_SIZE * 1.15 * zoom))
            bh = max(3, int(4 * zoom))
            bx = int(sx) - bw // 2
            by = y + max(4, int(8 * zoom))
            pygame.draw.rect(screen, (0, 0, 0), (bx, by, bw, bh))
            pygame.draw.rect(screen, (90, 128, 220), (bx + 1, by + 1, max(1, int((bw - 2) * self.build_progress)), bh - 2))
