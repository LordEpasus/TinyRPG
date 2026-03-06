from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pygame

from settings import ASSETS_2D, TILE_SIZE, TILE_WATER, WHITE

if TYPE_CHECKING:
    from src.engine.pathfinder import Pathfinder
    from src.entities.unit import Unit


class Ship:
    SPEED = 176.0
    CAPACITY = 4
    CARGO_CAPACITY = 220
    BOARD_RANGE = TILE_SIZE * 0.95
    DISPLAY_W = 144
    DISPLAY_H = 108
    _sid_seq = 0

    def __init__(self, wx: float, wy: float, *, civilization: str = "Blue", kingdom_id: str | None = None):
        Ship._sid_seq += 1
        self.sid = Ship._sid_seq
        self.world_pos = pygame.math.Vector2(wx, wy)
        self.civilization = civilization
        self.asset_color = civilization
        self.kingdom_id = kingdom_id or civilization
        self.selected = False
        self.max_hp = 520
        self.hp = float(self.max_hp)

        self.target_pos: pygame.math.Vector2 | None = None
        self._path: list[pygame.math.Vector2] = []
        self._path_index = 0
        self._moving = False

        self.passengers: list[Unit] = []
        self._boarding_queue: list[Unit] = []
        self._unload_request: tuple[float, float] | None = None
        self.cargo: dict[str, int] = {"gold": 0, "wood": 0, "stone": 0}
        self._sprite = self._load_sprite()
        self._zoom_cache: dict[int, pygame.Surface] = {}

    @property
    def has_space(self) -> bool:
        return len(self.passengers) < self.CAPACITY

    @property
    def passenger_count(self) -> int:
        return len(self.passengers)

    @property
    def cargo_used(self) -> int:
        return sum(max(0, int(v)) for v in self.cargo.values())

    @property
    def cargo_free(self) -> int:
        return max(0, self.CARGO_CAPACITY - self.cargo_used)

    def has_cargo_space(self, amount: int = 1) -> bool:
        return self.cargo_free >= max(1, int(amount))

    def store_resource(self, resource_type: str, amount: int) -> int:
        if resource_type not in self.cargo:
            return 0
        val = max(0, int(amount))
        if val <= 0:
            return 0
        put = min(val, self.cargo_free)
        if put <= 0:
            return 0
        self.cargo[resource_type] = self.cargo.get(resource_type, 0) + put
        return put

    def _load_sprite(self) -> pygame.Surface:
        path = os.path.join(ASSETS_2D, "Ship_full.png")
        if os.path.exists(path):
            raw = pygame.image.load(path).convert_alpha()
            return pygame.transform.scale(raw, (self.DISPLAY_W, self.DISPLAY_H))
        fb = pygame.Surface((self.DISPLAY_W, self.DISPLAY_H), pygame.SRCALPHA)
        pygame.draw.ellipse(fb, (122, 94, 66), fb.get_rect())
        pygame.draw.ellipse(fb, (26, 18, 12), fb.get_rect(), 3)
        return fb

    def move_to(
        self,
        wx: float,
        wy: float,
        *,
        pathfinder: Pathfinder,
        blocked_tiles: set[tuple[int, int]] | None = None,
    ) -> bool:
        def water_only(col: int, row: int) -> bool:
            return pathfinder.tilemap.get_tile(col, row) == TILE_WATER

        points = pathfinder.find_path_world(
            (self.world_pos.x, self.world_pos.y),
            (wx, wy),
            blocked=blocked_tiles,
            walkable_fn=water_only,
        )
        if not points:
            self._path.clear()
            self._moving = False
            self.target_pos = None
            return False

        self._path = [pygame.math.Vector2(px, py) for px, py in points]
        exact_goal = pygame.math.Vector2(wx, wy)
        if (exact_goal - self._path[-1]).length_squared() > 9.0:
            self._path.append(exact_goal)
        self._path_index = 0
        self.target_pos = pygame.math.Vector2(self._path[0])
        self._moving = True
        return True

    def request_board(
        self,
        unit: Unit,
        *,
        pathfinder: Pathfinder,
        blocked_tiles: set[tuple[int, int]] | None = None,
    ) -> bool:
        if unit.is_dead:
            return False
        if unit in self.passengers or unit in self._boarding_queue:
            return True
        if not self.has_space:
            return False
        unit.move_to(
            self.world_pos.x,
            self.world_pos.y,
            pathfinder=pathfinder,
            blocked_tiles=blocked_tiles,
        )
        self._boarding_queue.append(unit)
        return True

    def request_unload(self, wx: float, wy: float) -> None:
        self._unload_request = (wx, wy)

    def update(
        self,
        dt: float,
        *,
        tilemap,
    ) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        if self.target_pos is not None and self._moving:
            direction = self.target_pos - self.world_pos
            dist = direction.length()
            step = self.SPEED * dt
            if dist <= step:
                self.world_pos = pygame.math.Vector2(self.target_pos)
                if self._path and self._path_index + 1 < len(self._path):
                    self._path_index += 1
                    self.target_pos = pygame.math.Vector2(self._path[self._path_index])
                    self._moving = True
                else:
                    self._path.clear()
                    self._path_index = 0
                    self.target_pos = None
                    self._moving = False
            else:
                direction.scale_to_length(step)
                self.world_pos += direction

        if self._boarding_queue and self.has_space:
            for unit in list(self._boarding_queue):
                if unit.is_dead:
                    self._boarding_queue.remove(unit)
                    continue
                if not self.has_space:
                    break
                if (unit.world_pos - self.world_pos).length_squared() <= self.BOARD_RANGE * self.BOARD_RANGE:
                    self._boarding_queue.remove(unit)
                    self.passengers.append(unit)
                    events.append({"kind": "board", "ship": self, "unit": unit})

        if self._unload_request is not None and not self._moving and self.passengers:
            unload_tiles = self._find_unload_tiles(tilemap, self._unload_request[0], self._unload_request[1], len(self.passengers))
            if not unload_tiles:
                unload_tiles = self._find_unload_tiles(tilemap, self.world_pos.x, self.world_pos.y, len(self.passengers))
            if unload_tiles:
                for i, unit in enumerate(list(self.passengers)):
                    wx, wy = unload_tiles[i % len(unload_tiles)]
                    events.append({"kind": "unload", "ship": self, "unit": unit, "wx": wx, "wy": wy})
                self.passengers.clear()
            self._unload_request = None

        return events

    @staticmethod
    def _find_unload_tiles(tilemap, wx: float, wy: float, count: int) -> list[tuple[float, float]]:
        tc, tr = tilemap.world_to_tile(wx, wy)
        out: list[tuple[float, float]] = []
        for radius in range(1, 8):
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if abs(dc) != radius and abs(dr) != radius:
                        continue
                    c = tc + dc
                    r = tr + dr
                    if not (0 <= c < tilemap.cols and 0 <= r < tilemap.rows):
                        continue
                    if not tilemap.is_walkable(c, r):
                        continue
                    # Must be coastline-adjacent to water.
                    coast = False
                    for ndc, ndr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nc, nr = c + ndc, r + ndr
                        if 0 <= nc < tilemap.cols and 0 <= nr < tilemap.rows and tilemap.get_tile(nc, nr) == TILE_WATER:
                            coast = True
                            break
                    if not coast:
                        continue
                    out.append(tilemap.tile_center(c, r))
                    if len(out) >= max(1, count):
                        return out
        return out

    def contains_point(self, wx: float, wy: float) -> bool:
        dx = wx - self.world_pos.x
        dy = wy - self.world_pos.y
        rx = (self.DISPLAY_W * 0.30)
        ry = (self.DISPLAY_H * 0.22)
        if rx <= 0 or ry <= 0:
            return False
        nx = dx / rx
        ny = dy / ry
        return nx * nx + ny * ny <= 1.0

    def draw(self, screen: pygame.Surface, camera) -> None:
        zoom = camera.zoom
        if zoom == 1.0:
            sprite = self._sprite
        else:
            key = int(round(zoom * 1000))
            sprite = self._zoom_cache.get(key)
            if sprite is None:
                w = max(1, int(self._sprite.get_width() * zoom))
                h = max(1, int(self._sprite.get_height() * zoom))
                sprite = pygame.transform.scale(self._sprite, (w, h))
                self._zoom_cache[key] = sprite

        sx, sy = camera.world_to_screen((self.world_pos.x, self.world_pos.y))
        x = int(sx) - sprite.get_width() // 2
        y = int(sy) - sprite.get_height() // 2
        screen.blit(sprite, (x, y))

        if self.selected:
            rr = pygame.Rect(int(sx - 28 * zoom), int(sy + 18 * zoom), max(10, int(56 * zoom)), max(4, int(14 * zoom)))
            pygame.draw.ellipse(screen, (0, 0, 0), rr, 3)
            pygame.draw.ellipse(screen, WHITE, rr, 2)

        # Show capacity.
        font = pygame.font.SysFont("monospace", max(9, int(11 * zoom)))
        txt = font.render(
            f"P {self.passenger_count}/{self.CAPACITY}  C {self.cargo_used}/{self.CARGO_CAPACITY}",
            True,
            (214, 228, 246),
        )
        bg = pygame.Surface((txt.get_width() + 6, txt.get_height() + 4), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 136))
        bx = int(sx) - bg.get_width() // 2
        by = y - bg.get_height() - 3
        screen.blit(bg, (bx, by))
        screen.blit(txt, (bx + 3, by + 2))
