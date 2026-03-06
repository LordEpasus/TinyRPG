import os
import random
import math
import pygame
from settings import (
    TILE_SIZE, MAP_COLS, MAP_ROWS,
    TILE_GRASS, TILE_WATER, TILE_STONE, TILE_DIRT, TILE_FOREST,
    TILE_COLORS, TILE_WALKABLE,
    ZOOM_MIN, ZOOM_MAX,
    GRID_ALPHA_MIN, GRID_ALPHA_MAX,
    WATER_ANIM_FPS,
    TREE_DENSITY_MOD, TREE_DENSITY_CUTOFF,
    SPAWN_SAFE_RADIUS,
    SPROUT_LANDS, PIXEL_TOPDOWN,
)

# ── Tileset paths ─────────────────────────────────────────────────────────────
_GRASS_SHEET = os.path.join(SPROUT_LANDS, "Tilesets", "Grass.png")
_DIRT_SHEET  = os.path.join(SPROUT_LANDS, "Tilesets", "Tilled_Dirt.png")
_STONE_SHEET = os.path.join(PIXEL_TOPDOWN, "Texture", "TX Tileset Stone Ground.png")
_WATER_SHEET = os.path.join(SPROUT_LANDS, "Tilesets", "Water.png")

_SRC = 16   # source tile size

# ── Variant definitions: (path, col, row [, src_size]) ───────────────────────
# IMPORTANT: only use SEAMLESS INTERIOR tiles (fully opaque, matching edges).
# Sprout Lands rows 5-6 are the seamless interior grass/dirt tiles.
# PixelTopDown Stone rows 1-4 are the seamless interior stone tiles.
_VARIANTS: dict[int, list[tuple]] = {
    TILE_GRASS: [
        # Sprout Lands row 5-6: seamless interior grass (edge pixels identical)
        (_GRASS_SHEET, 0, 5), (_GRASS_SHEET, 1, 5), (_GRASS_SHEET, 2, 5),
        (_GRASS_SHEET, 3, 5), (_GRASS_SHEET, 4, 5), (_GRASS_SHEET, 5, 5),
        (_GRASS_SHEET, 0, 6), (_GRASS_SHEET, 1, 6), (_GRASS_SHEET, 2, 6),
        (_GRASS_SHEET, 3, 6), (_GRASS_SHEET, 4, 6), (_GRASS_SHEET, 5, 6),
    ],
    TILE_FOREST: [
        # Same seamless grass base (trees drawn as overlay)
        (_GRASS_SHEET, 0, 5), (_GRASS_SHEET, 1, 5), (_GRASS_SHEET, 3, 5),
        (_GRASS_SHEET, 0, 6), (_GRASS_SHEET, 2, 6), (_GRASS_SHEET, 4, 6),
    ],
    TILE_WATER: [
        # Sprout Lands water strip has 4 tile variants in row 0.
        (_WATER_SHEET, 0, 0), (_WATER_SHEET, 1, 0),
        (_WATER_SHEET, 2, 0), (_WATER_SHEET, 3, 0),
    ],
    TILE_DIRT: [
        # Sprout Lands Tilled_Dirt row 5-6: seamless interior dirt
        (_DIRT_SHEET, 0, 5), (_DIRT_SHEET, 1, 5), (_DIRT_SHEET, 2, 5),
        (_DIRT_SHEET, 0, 6), (_DIRT_SHEET, 1, 6), (_DIRT_SHEET, 2, 6),
    ],
    TILE_STONE: [
        # PixelTopDown Stone rows 1-4: seamless interior stone
        (_STONE_SHEET, 1, 1), (_STONE_SHEET, 2, 1), (_STONE_SHEET, 3, 1),
        (_STONE_SHEET, 4, 1), (_STONE_SHEET, 1, 2), (_STONE_SHEET, 2, 2),
        (_STONE_SHEET, 3, 2), (_STONE_SHEET, 4, 2), (_STONE_SHEET, 1, 3),
        (_STONE_SHEET, 2, 3), (_STONE_SHEET, 3, 3), (_STONE_SHEET, 4, 3),
    ],
}

# Flip multiplier — each source tile is pre-baked as 4 rotations
# (original + H-flip + V-flip + HV-flip) for natural variety.
_FLIP_MULT = 4


class TileMap:
    def __init__(
        self,
        seed: int = 42,
        spawn_center: tuple[float, float] | None = None,
        spawn_centers: list[tuple[float, float]] | None = None,
        spawn_safe_radius: int = SPAWN_SAFE_RADIUS,
    ):
        self.cols = MAP_COLS
        self.rows = MAP_ROWS
        self.seed = int(seed)
        self.spawn_center = spawn_center
        self.spawn_centers = list(spawn_centers or [])
        if spawn_center is not None:
            self.spawn_centers.append(spawn_center)
        self.spawn_safe_radius = max(0, int(spawn_safe_radius))

        self.tiles: list[list[int]] = [
            [TILE_GRASS] * self.cols for _ in range(self.rows)
        ]
        self.variant_map: list[list[int]] = [
            [0] * self.cols for _ in range(self.rows)
        ]
        self.forest_tiles: list[tuple[int, int]] = []
        self.forest_cols_by_row: list[list[int]] = [
            [] for _ in range(self.rows)
        ]
        self.walkable_map: list[list[bool]] = [
            [True] * self.cols for _ in range(self.rows)
        ]

        self._generate(seed)

        # Base tile surfaces at TILE_SIZE (64 px) — composited, fully opaque
        self._tile_variants: dict[int, list[pygame.Surface]] = {}
        self._load_variants()

        # Zoom-scaled surface cache — rebuilt only when zoom changes
        self._zoom_key: float | None     = None
        self._zoom_tile_px: int          = TILE_SIZE
        self._zoom_variants: dict[int, list[pygame.Surface]] = {}

        # Persistent tree scale cache — keyed by (surface id, zoom*1000)
        # avoids re-scaling the same tree sprite every single frame
        self._tree_scale_cache: dict[tuple[int, int], pygame.Surface] = {}

    # ── Tile loading ──────────────────────────────────────────────────────────
    @staticmethod
    def _frames_identical(frames: list[pygame.Surface]) -> bool:
        if len(frames) <= 1:
            return True
        head = pygame.image.tobytes(frames[0], "RGBA")
        return all(pygame.image.tobytes(f, "RGBA") == head for f in frames[1:])

    @staticmethod
    def _make_wrapped_shift_frames(base: pygame.Surface) -> list[pygame.Surface]:
        w, h = base.get_size()
        shifts = ((0, 0), (4, 0), (4, 2), (0, 2))
        frames: list[pygame.Surface] = []
        for sx, sy in shifts:
            frame = pygame.Surface((w, h), pygame.SRCALPHA)
            frame.blit(base, (-sx, -sy))
            if sx:
                frame.blit(base, (w - sx, -sy))
            if sy:
                frame.blit(base, (-sx, h - sy))
            if sx and sy:
                frame.blit(base, (w - sx, h - sy))
            frames.append(frame)
        return frames

    def _load_variants(self) -> None:
        """Extract seamless interior tiles from sheets, scale to TILE_SIZE."""
        cache: dict[str, pygame.Surface] = {}

        for tile_type, defs in _VARIANTS.items():
            base_color = TILE_COLORS[tile_type]
            surfs: list[pygame.Surface] = []

            for entry in defs:
                path, col, row = entry[0], entry[1], entry[2]
                src_size = entry[3] if len(entry) == 4 else _SRC

                if path not in cache:
                    cache[path] = (
                        pygame.image.load(path).convert_alpha()
                        if os.path.exists(path) else None
                    )
                sheet = cache[path]
                if sheet is None:
                    continue

                sx, sy = col * src_size, row * src_size
                sw, sh = sheet.get_size()
                if sx + src_size > sw or sy + src_size > sh:
                    continue

                # Extract tile region
                tile = sheet.subsurface((sx, sy, src_size, src_size)).copy()

                # Scale to TILE_SIZE (nearest-neighbour keeps pixel art crisp)
                if src_size != TILE_SIZE:
                    tile = pygame.transform.scale(tile, (TILE_SIZE, TILE_SIZE))

                surfs.append(tile)

            if not surfs:                      # fallback solid colour
                fb = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
                fb.fill((*base_color, 255))
                surfs.append(fb)

            if tile_type == TILE_WATER:
                if self._frames_identical(surfs):
                    surfs = self._make_wrapped_shift_frames(surfs[0])
                # Keep source order for animated strip frames.
                self._tile_variants[tile_type] = surfs
                continue

            # Pre-bake 4 flip orientations per tile → seamless variety
            expanded: list[pygame.Surface] = []
            for s in surfs:
                expanded.append(s)
                expanded.append(pygame.transform.flip(s, True, False))
                expanded.append(pygame.transform.flip(s, False, True))
                expanded.append(pygame.transform.flip(s, True, True))

            self._tile_variants[tile_type] = expanded

    # ── Zoom cache ────────────────────────────────────────────────────────────
    def _refresh_zoom(self, zoom: float) -> None:
        """Pre-scale tile variants for the current zoom (cached)."""
        key = round(zoom, 4)
        if key == self._zoom_key:
            return

        # Ceil prevents 1px gaps when projected tile step rounds up on screen.
        tile_px = max(1, int(math.ceil(TILE_SIZE * zoom)))
        zv: dict[int, list[pygame.Surface]] = {}

        for tt, variants in self._tile_variants.items():
            if tile_px == TILE_SIZE:
                zv[tt] = variants           # no scaling needed
            else:
                zv[tt] = [
                    pygame.transform.scale(v, (tile_px, tile_px))
                    for v in variants
                ]

        self._zoom_key      = key
        self._zoom_tile_px  = tile_px
        self._zoom_variants = zv

    # ── Map generation ────────────────────────────────────────────────────────
    def _generate(self, seed: int) -> None:
        rng = random.Random(seed)
        self.tiles = [[TILE_WATER] * self.cols for _ in range(self.rows)]

        core_points = self._island_core_points(rng)
        for cx, cy in core_points:
            self._carve_island(rng, cx, cy)
        self._reinforce_mainlands(rng)

        # Cellular smoothing to avoid jagged coastlines.
        for _ in range(3):
            src = [row[:] for row in self.tiles]
            for row in range(1, self.rows - 1):
                for col in range(1, self.cols - 1):
                    land_n = self._land_neighbors(src, col, row)
                    if src[row][col] == TILE_WATER:
                        if land_n >= 5:
                            self.tiles[row][col] = TILE_GRASS
                    else:
                        if land_n <= 2:
                            self.tiles[row][col] = TILE_WATER

        self._carve_ocean_channels(rng)

        for _ in range(max(20, (self.cols * self.rows) // 900)):
            self._paint_disk(
                rng.randint(3, self.cols - 4),
                rng.randint(3, self.rows - 4),
                rng.randint(2, 5),
                TILE_STONE,
                only_on={TILE_GRASS},
            )

        for _ in range(max(90, (self.cols * self.rows) // 280)):
            self._paint_disk(
                rng.randint(3, self.cols - 4),
                rng.randint(3, self.rows - 4),
                rng.randint(5, 13),
                TILE_FOREST,
                only_on={TILE_GRASS},
            )

        for _ in range(max(18, (self.cols * self.rows) // 1400)):
            x = rng.randint(6, self.cols - 7)
            y = rng.randint(6, self.rows - 7)
            length = rng.randint(18, 46)
            d = rng.choice([(1, 0), (0, 1)])
            w = rng.randint(1, 2)
            for i in range(length):
                for ow in range(-w, w + 1):
                    tx = x + d[0] * i + d[1] * ow
                    ty = y + d[1] * i + d[0] * ow
                    if 0 <= tx < self.cols and 0 <= ty < self.rows and self.tiles[ty][tx] != TILE_WATER:
                        self.tiles[ty][tx] = TILE_DIRT

        self._apply_spawn_safe_zone()
        self._smooth_transitions()
        self._rebuild_metadata(rng)

    def _island_core_points(self, rng: random.Random) -> list[tuple[int, int]]:
        points: list[tuple[int, int]] = []
        if self.spawn_centers:
            for wx, wy in self.spawn_centers[:4]:
                points.append(self.world_to_tile(wx, wy))
        else:
            margin_c = max(8, self.cols // 12)
            margin_r = max(8, self.rows // 12)
            points.extend(
                [
                    (margin_c, margin_r),
                    (self.cols - margin_c - 1, margin_r),
                    (margin_c, self.rows - margin_r - 1),
                    (self.cols - margin_c - 1, self.rows - margin_r - 1),
                ]
            )
        edge_extras = [
            (self.cols // 2, max(6, self.rows // 6)),
            (self.cols // 2, min(self.rows - 7, self.rows - self.rows // 6)),
            (max(6, self.cols // 6), self.rows // 2),
            (min(self.cols - 7, self.cols - self.cols // 6), self.rows // 2),
            (self.cols // 2, self.rows // 2),
        ]
        rng.shuffle(edge_extras)
        points.extend(edge_extras[:3])
        return points

    def _carve_island(self, rng: random.Random, cx: int, cy: int) -> None:
        span = min(self.cols, self.rows)
        orbit = max(12, span // 8)
        for _ in range(40):
            ang = rng.random() * math.tau
            dist = rng.uniform(0, orbit)
            x = int(cx + math.cos(ang) * dist)
            y = int(cy + math.sin(ang) * dist)
            r = rng.randint(4, max(7, span // 22))
            self._paint_disk(x, y, r, TILE_GRASS, only_on={TILE_WATER, TILE_GRASS})

    def _reinforce_mainlands(self, rng: random.Random) -> None:
        centers: list[tuple[int, int]] = []
        if self.spawn_centers:
            centers = [self.world_to_tile(wx, wy) for wx, wy in self.spawn_centers[:4]]
        if not centers:
            centers = [
                (self.cols // 4, self.rows // 4),
                (self.cols * 3 // 4, self.rows // 4),
                (self.cols // 4, self.rows * 3 // 4),
                (self.cols * 3 // 4, self.rows * 3 // 4),
            ]

        for cx, cy in centers:
            for _ in range(24):
                x = cx + rng.randint(-12, 12)
                y = cy + rng.randint(-12, 12)
                r = rng.randint(10, 18)
                self._paint_disk(x, y, r, TILE_GRASS, only_on={TILE_WATER, TILE_GRASS})

        # Global fill so map is not over-watered on large sizes.
        for _ in range(max(48, (self.cols * self.rows) // 320)):
            x = rng.randint(6, self.cols - 7)
            y = rng.randint(6, self.rows - 7)
            r = rng.randint(5, 11)
            self._paint_disk(x, y, r, TILE_GRASS, only_on={TILE_WATER, TILE_GRASS})

    def _carve_ocean_channels(self, rng: random.Random) -> None:
        # Keep major sea lanes so quadrants stay strategically separated.
        mid_col = self.cols // 2
        mid_row = self.rows // 2
        channel_half = max(1, min(self.cols, self.rows) // 64)

        if rng.random() < 0.42:
            # Vertical sea lane with meander.
            drift = 0
            for row in range(self.rows):
                if row % 9 == 0:
                    drift += rng.choice((-1, 0, 1))
                    drift = max(-4, min(4, drift))
                c0 = mid_col + drift
                for col in range(c0 - channel_half, c0 + channel_half + 1):
                    if 0 <= col < self.cols:
                        self.tiles[row][col] = TILE_WATER
        if rng.random() < 0.22:
            # One horizontal lane, thinner than vertical.
            drift = 0
            for col in range(self.cols):
                if col % 11 == 0:
                    drift += rng.choice((-1, 0, 1))
                    drift = max(-3, min(3, drift))
                r0 = mid_row + drift
                for row in range(r0 - channel_half, r0 + channel_half + 1):
                    if 0 <= row < self.rows:
                        self.tiles[row][col] = TILE_WATER

    def _paint_disk(
        self,
        cx: int,
        cy: int,
        r: int,
        tile_type: int,
        *,
        only_on: set[int] | None = None,
    ) -> None:
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy > r * r:
                    continue
                tx, ty = cx + dx, cy + dy
                if not (0 <= tx < self.cols and 0 <= ty < self.rows):
                    continue
                if only_on is not None and self.tiles[ty][tx] not in only_on:
                    continue
                self.tiles[ty][tx] = tile_type

    @staticmethod
    def _land_neighbors(src: list[list[int]], col: int, row: int) -> int:
        total = 0
        for nr in range(row - 1, row + 2):
            for nc in range(col - 1, col + 2):
                if nr == row and nc == col:
                    continue
                if src[nr][nc] != TILE_WATER:
                    total += 1
        return total

    def _apply_spawn_safe_zone(self) -> None:
        centers: list[tuple[int, int]] = []
        if self.spawn_centers:
            for wx, wy in self.spawn_centers:
                centers.append(self.world_to_tile(wx, wy))
        elif self.spawn_center is not None:
            centers.append(self.world_to_tile(self.spawn_center[0], self.spawn_center[1]))
        else:
            centers.append((self.cols // 2, self.rows // 2))

        r = self.spawn_safe_radius
        for sc, sr in centers:
            for row in range(sr - r, sr + r + 1):
                if not (0 <= row < self.rows):
                    continue
                for col in range(sc - r, sc + r + 1):
                    if not (0 <= col < self.cols):
                        continue
                    dx = col - sc
                    dy = row - sr
                    if dx * dx + dy * dy > r * r:
                        continue
                    if self.tiles[row][col] in (TILE_WATER, TILE_FOREST):
                        self.tiles[row][col] = TILE_GRASS

    def _smooth_transitions(self) -> None:
        original = [row[:] for row in self.tiles]
        shoreline = [row[:] for row in original]

        # Add a shoreline band: ground touching water becomes dirt.
        for row in range(self.rows):
            for col in range(self.cols):
                tt = original[row][col]
                if tt not in (TILE_GRASS, TILE_FOREST):
                    continue
                has_water_neighbor = False
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nc, nr = col + dx, row + dy
                    if 0 <= nc < self.cols and 0 <= nr < self.rows:
                        if original[nr][nc] == TILE_WATER:
                            has_water_neighbor = True
                            break
                if has_water_neighbor:
                    shoreline[row][col] = TILE_DIRT

        # Gentle majority smoothing for non-water terrain.
        smoothed = [row[:] for row in shoreline]
        safe_centers: list[tuple[int, int]] = []
        if self.spawn_centers:
            for wx, wy in self.spawn_centers:
                safe_centers.append(self.world_to_tile(wx, wy))
        elif self.spawn_center is not None:
            safe_centers.append(self.world_to_tile(self.spawn_center[0], self.spawn_center[1]))
        else:
            safe_centers.append((self.cols // 2, self.rows // 2))
        keep_r2 = self.spawn_safe_radius * self.spawn_safe_radius

        for row in range(1, self.rows - 1):
            for col in range(1, self.cols - 1):
                current = shoreline[row][col]
                if current == TILE_WATER:
                    continue
                keep = False
                for sc, sr in safe_centers:
                    dx0 = col - sc
                    dy0 = row - sr
                    if dx0 * dx0 + dy0 * dy0 <= keep_r2:
                        keep = True
                        break
                if keep:
                    continue

                counts: dict[int, int] = {}
                for nr in range(row - 1, row + 2):
                    for nc in range(col - 1, col + 2):
                        t = shoreline[nr][nc]
                        if t == TILE_WATER:
                            continue
                        counts[t] = counts.get(t, 0) + 1
                if not counts:
                    continue
                best_tile, best_count = max(counts.items(), key=lambda item: item[1])
                if best_tile != current and best_count >= 6:
                    smoothed[row][col] = best_tile

        self.tiles = smoothed

    def _rebuild_metadata(self, rng: random.Random) -> None:
        self.forest_tiles.clear()
        self.forest_cols_by_row = [[] for _ in range(self.rows)]
        self.variant_map = [[0] * self.cols for _ in range(self.rows)]
        self.walkable_map = [[False] * self.cols for _ in range(self.rows)]

        for row in range(self.rows):
            for col in range(self.cols):
                tt = self.tiles[row][col]
                n = len(_VARIANTS.get(tt, [(None, 0, 0)])) * _FLIP_MULT
                self.variant_map[row][col] = rng.randint(0, n - 1)
                self.walkable_map[row][col] = bool(TILE_WALKABLE.get(tt, False))
                if tt == TILE_FOREST:
                    self.forest_tiles.append((col, row))
                    self.forest_cols_by_row[row].append(col)

    def refresh_metadata(self) -> None:
        self._rebuild_metadata(random.Random(self.seed + 8111))

    def sample_spawn_worlds(
        self,
        *,
        count: int,
        seed: int,
        margin: int = 10,
        min_distance_tiles: int = 28,
    ) -> list[tuple[float, float]]:
        rng = random.Random(seed + 13331)
        candidates: list[tuple[int, int, int]] = []
        for row in range(max(2, margin), min(self.rows - 2, self.rows - margin)):
            for col in range(max(2, margin), min(self.cols - 2, self.cols - margin)):
                if not self.is_walkable(col, row):
                    continue
                tile = self.get_tile(col, row)
                if tile == TILE_WATER:
                    continue
                score = self._land_score(col, row, radius=8)
                if score < 56:
                    continue
                candidates.append((score, col, row))

        candidates.sort(key=lambda item: (-item[0], item[2], item[1]))
        if not candidates:
            fallback = [
                self.tile_center(self.cols // 4, self.rows // 4),
                self.tile_center(self.cols * 3 // 4, self.rows // 4),
                self.tile_center(self.cols // 4, self.rows * 3 // 4),
                self.tile_center(self.cols * 3 // 4, self.rows * 3 // 4),
                self.tile_center(self.cols // 2, self.rows // 2),
            ]
            return fallback[: max(1, count)]

        chosen: list[tuple[int, int]] = []
        radius2 = max(1, min_distance_tiles) * max(1, min_distance_tiles)
        for _, col, row in candidates:
            if any((col - cc) * (col - cc) + (row - rr) * (row - rr) < radius2 for cc, rr in chosen):
                continue
            chosen.append((col, row))
            if len(chosen) >= count:
                break

        pool = [(col, row) for _, col, row in candidates if (col, row) not in chosen]
        while len(chosen) < count and pool:
            index = rng.randrange(len(pool))
            col, row = pool.pop(index)
            if any((col - cc) * (col - cc) + (row - rr) * (row - rr) < radius2 // 2 for cc, rr in chosen):
                continue
            chosen.append((col, row))

        return [self.tile_center(col, row) for col, row in chosen[:count]]

    def apply_spawn_safe_zones(self, spawn_worlds: list[tuple[float, float]]) -> None:
        self.spawn_centers = list(spawn_worlds)
        self._apply_spawn_safe_zone()
        self.refresh_metadata()

    def _land_score(self, col: int, row: int, *, radius: int) -> int:
        score = 0
        for nr in range(max(0, row - radius), min(self.rows, row + radius + 1)):
            for nc in range(max(0, col - radius), min(self.cols, col + radius + 1)):
                tile = self.tiles[nr][nc]
                if tile == TILE_WATER:
                    continue
                score += 1
                if tile == TILE_FOREST:
                    score += 1
                elif tile == TILE_DIRT:
                    score += 2
        return score

    # ── Draw: ground ─────────────────────────────────────────────────────────
    def draw(self, screen: pygame.Surface, camera) -> None:
        self._refresh_zoom(camera.zoom)
        c0, r0, c1, r1 = camera.get_visible_tile_range()
        zv      = self._zoom_variants
        water_frames = zv.get(TILE_WATER, [])
        water_vi = 0
        if water_frames:
            water_period_ms = max(40, int(1000 / max(0.1, WATER_ANIM_FPS)))
            water_vi = (pygame.time.get_ticks() // water_period_ms) % len(water_frames)

        # Batch all tile blits → single blits() call for major speedup
        blit_list: list[tuple[pygame.Surface, tuple[int, int]]] = []
        w2s = camera.world_to_screen
        tiles = self.tiles
        vmap  = self.variant_map
        ts    = TILE_SIZE

        for row in range(r0, r1 + 1):
            tile_row  = tiles[row]
            vmap_row  = vmap[row]
            for col in range(c0, c1 + 1):
                tt    = tile_row[col]
                vlist = zv[tt]
                if tt == TILE_WATER and water_frames:
                    vi = water_vi
                else:
                    vi = vmap_row[col] % len(vlist)
                sx, sy = w2s((col * ts, row * ts))
                blit_list.append((vlist[vi], (int(round(sx)), int(round(sy)))))

        screen.blits(blit_list)

    # ── Draw: grid ────────────────────────────────────────────────────────────
    def draw_grid(self, screen: pygame.Surface, camera) -> None:
        if TILE_SIZE * camera.zoom < 12:
            return
        c0, r0, c1, r1 = camera.get_visible_tile_range()
        sw, sh = screen.get_size()
        gs = pygame.Surface((sw, sh), pygame.SRCALPHA)

        z_span = max(0.001, ZOOM_MAX - ZOOM_MIN)
        z_norm = max(0.0, min(1.0, (camera.zoom - ZOOM_MIN) / z_span))
        alpha_minor = int(GRID_ALPHA_MIN + (GRID_ALPHA_MAX - GRID_ALPHA_MIN) * z_norm)
        alpha_major = min(255, alpha_minor + 18)
        color_minor = (22, 26, 30, alpha_minor)
        color_major = (14, 18, 22, alpha_major)

        for col in range(c0, c1 + 2):
            sx, _ = camera.world_to_screen((col * TILE_SIZE, 0))
            color = color_major if col % 4 == 0 else color_minor
            pygame.draw.line(gs, color, (int(sx), 0), (int(sx), sh))
        for row in range(r0, r1 + 2):
            _, sy = camera.world_to_screen((0, row * TILE_SIZE))
            color = color_major if row % 4 == 0 else color_minor
            pygame.draw.line(gs, color, (0, int(sy)), (sw, int(sy)))
        screen.blit(gs, (0, 0))

    # ── Draw: trees ───────────────────────────────────────────────────────────
    def draw_trees(
        self,
        screen: pygame.Surface,
        camera,
        tree_sets: list[list[pygame.Surface]],
        skip_tiles: set[tuple[int, int]] | None = None,
    ) -> None:
        if not tree_sets:
            return
        c0, r0, c1, r1 = camera.get_visible_tile_range()
        zoom = camera.zoom
        density_mod    = max(1, TREE_DENSITY_MOD)
        density_cutoff = max(0, min(density_mod, TREE_DENSITY_CUTOFF))
        # Keep forests dense up close, lightly thin only at far zoom for FPS.
        lod_mod = 1
        if zoom < 0.32:
            lod_mod = 4
        elif zoom < 0.42:
            lod_mod = 3
        elif zoom < 0.56:
            lod_mod = 2
        zoom_key       = int(round(zoom * 1000))
        scaled_cache   = self._tree_scale_cache   # persistent across frames

        tree_blit_list: list[tuple[pygame.Surface, tuple[int, int]]] = []
        w2s = camera.world_to_screen
        ts  = TILE_SIZE

        row_start = max(0, r0)
        row_end = min(self.rows - 1, r1)
        for row in range(row_start, row_end + 1):
            cols_in_row = self.forest_cols_by_row[row]
            if not cols_in_row:
                continue
            for col in cols_in_row:
                if col < c0 or col > c1:
                    continue
                if skip_tiles is not None and (col, row) in skip_tiles:
                    continue
                if (col * 7 + row * 13) % density_mod >= density_cutoff:
                    continue
                if lod_mod > 1 and (col * 19 + row * 23) % lod_mod != 0:
                    continue
                frames = tree_sets[(col * 3 + row * 7) % len(tree_sets)]
                if not frames:
                    continue
                frame_i = (col * 11 + row * 17) % len(frames)
                base = frames[frame_i]
                if zoom != 1.0:
                    key = (id(base), zoom_key)
                    surf = scaled_cache.get(key)
                    if surf is None:
                        w = max(1, int(base.get_width() * zoom))
                        h = max(1, int(base.get_height() * zoom))
                        surf = pygame.transform.scale(base, (w, h))
                        scaled_cache[key] = surf
                else:
                    surf = base
                wx = col * ts + ts // 2
                wy = (row + 1) * ts
                sx, sy = w2s((wx, wy))
                tree_blit_list.append((surf, (int(sx) - surf.get_width() // 2,
                                              int(sy) - surf.get_height())))

        screen.blits(tree_blit_list)

    # ── Queries ───────────────────────────────────────────────────────────────
    def get_tile(self, col: int, row: int) -> int | None:
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return self.tiles[row][col]
        return None

    def is_walkable(self, col: int, row: int) -> bool:
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return self.walkable_map[row][col]
        return False

    def tile_center(self, col: int, row: int) -> tuple:
        return (
            col * TILE_SIZE + TILE_SIZE // 2,
            row * TILE_SIZE + TILE_SIZE // 2,
        )

    def world_to_tile(self, wx: float, wy: float) -> tuple:
        return int(wx // TILE_SIZE), int(wy // TILE_SIZE)
