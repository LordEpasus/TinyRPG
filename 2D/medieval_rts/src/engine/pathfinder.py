from __future__ import annotations

import heapq
import math
import time


class Pathfinder:
    """Grid A* pathfinder over TileMap walkability."""

    _DIRS: tuple[tuple[int, int, float], ...] = (
        (1, 0, 1.0),
        (-1, 0, 1.0),
        (0, 1, 1.0),
        (0, -1, 1.0),
        (1, 1, math.sqrt(2.0)),
        (1, -1, math.sqrt(2.0)),
        (-1, 1, math.sqrt(2.0)),
        (-1, -1, math.sqrt(2.0)),
    )

    def __init__(self, tilemap):
        self.tilemap = tilemap
        self.cols = tilemap.cols
        self.rows = tilemap.rows
        self.walkable = getattr(tilemap, "walkable_map", None)
        self._stats = {"calls": 0, "time_ms": 0.0, "failures": 0, "expanded": 0}

    def reset_stats(self) -> None:
        self._stats = {"calls": 0, "time_ms": 0.0, "failures": 0, "expanded": 0}

    def consume_stats(self) -> dict[str, float]:
        out = dict(self._stats)
        self.reset_stats()
        return out

    def find_path_world(
        self,
        start_world: tuple[float, float],
        goal_world: tuple[float, float],
        *,
        blocked: set[tuple[int, int]] | None = None,
        walkable_fn=None,
        max_expansions: int | None = None,
    ) -> list[tuple[float, float]]:
        sc, sr = self.tilemap.world_to_tile(start_world[0], start_world[1])
        gc, gr = self.tilemap.world_to_tile(goal_world[0], goal_world[1])
        tile_path = self.find_path_tile(
            (sc, sr),
            (gc, gr),
            blocked=blocked,
            walkable_fn=walkable_fn,
            max_expansions=max_expansions,
        )
        return [self.tilemap.tile_center(c, r) for c, r in tile_path]

    def find_path_tile(
        self,
        start: tuple[int, int],
        goal: tuple[int, int],
        *,
        blocked: set[tuple[int, int]] | None = None,
        walkable_fn=None,
        max_expansions: int | None = None,
    ) -> list[tuple[int, int]]:
        t0 = time.perf_counter()
        self._stats["calls"] += 1
        blocked = blocked or set()
        if not self._in_bounds(start) or not self._in_bounds(goal):
            self._stats["failures"] += 1
            self._stats["time_ms"] += (time.perf_counter() - t0) * 1000.0
            return []

        goal = self._nearest_walkable(goal, blocked, walkable_fn, max_radius=26)
        if goal is None:
            self._stats["failures"] += 1
            self._stats["time_ms"] += (time.perf_counter() - t0) * 1000.0
            return []

        start = self._normalize_start(start, blocked, walkable_fn, max_radius=16)
        if start is None:
            self._stats["failures"] += 1
            self._stats["time_ms"] += (time.perf_counter() - t0) * 1000.0
            return []
        if start == goal:
            self._stats["time_ms"] += (time.perf_counter() - t0) * 1000.0
            return [goal]

        if max_expansions is None:
            h = self._heuristic(start, goal)
            cap = int(2800 + h * 34.0)
            max_expansions = max(2200, min(self.cols * self.rows, cap))

        open_heap: list[tuple[float, int, tuple[int, int]]] = []
        counter = 0
        g_score: dict[tuple[int, int], float] = {start: 0.0}
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        closed: set[tuple[int, int]] = set()
        dirs = self._DIRS
        walkable = self._is_walkable
        heur = self._heuristic

        heapq.heappush(open_heap, (heur(start, goal), counter, start))

        expanded = 0
        while open_heap:
            _, _, current = heapq.heappop(open_heap)
            if current in closed:
                continue
            expanded += 1
            if expanded > max_expansions:
                self._stats["expanded"] += expanded
                self._stats["failures"] += 1
                self._stats["time_ms"] += (time.perf_counter() - t0) * 1000.0
                return []
            if current == goal:
                self._stats["expanded"] += expanded
                self._stats["time_ms"] += (time.perf_counter() - t0) * 1000.0
                return self._reconstruct(came_from, current)
            closed.add(current)

            base_g = g_score[current]
            c, r = current
            for dc, dr, step_cost in dirs:
                nc, nr = c + dc, r + dr
                nxt = (nc, nr)
                if nxt in closed:
                    continue
                if not walkable(nxt, blocked, walkable_fn):
                    continue
                if dc != 0 and dr != 0:
                    # No corner cutting through blocked edges.
                    if not walkable((c + dc, r), blocked, walkable_fn):
                        continue
                    if not walkable((c, r + dr), blocked, walkable_fn):
                        continue
                tentative = base_g + step_cost
                old = g_score.get(nxt)
                if old is not None and tentative >= old:
                    continue
                came_from[nxt] = current
                g_score[nxt] = tentative
                counter += 1
                f = tentative + heur(nxt, goal)
                heapq.heappush(open_heap, (f, counter, nxt))
        self._stats["expanded"] += expanded
        self._stats["failures"] += 1
        self._stats["time_ms"] += (time.perf_counter() - t0) * 1000.0
        return []

    def _neighbors(
        self,
        node: tuple[int, int],
        blocked: set[tuple[int, int]],
        walkable_fn,
    ) -> list[tuple[tuple[int, int], float]]:
        c, r = node
        out: list[tuple[tuple[int, int], float]] = []
        for dc, dr, cost in self._DIRS:
            nc, nr = c + dc, r + dr
            nxt = (nc, nr)
            if not self._is_walkable(nxt, blocked, walkable_fn):
                continue
            if dc != 0 and dr != 0:
                # No corner cutting through blocked edges.
                if not self._is_walkable((c + dc, r), blocked, walkable_fn):
                    continue
                if not self._is_walkable((c, r + dr), blocked, walkable_fn):
                    continue
            out.append((nxt, cost))
        return out

    @staticmethod
    def _heuristic(a: tuple[int, int], b: tuple[int, int]) -> float:
        dx = abs(a[0] - b[0])
        dy = abs(a[1] - b[1])
        # Octile distance for 8-direction movement.
        return (dx + dy) + (math.sqrt(2.0) - 2.0) * min(dx, dy)

    def _reconstruct(
        self,
        came_from: dict[tuple[int, int], tuple[int, int]],
        end: tuple[int, int],
    ) -> list[tuple[int, int]]:
        path = [end]
        cur = end
        while cur in came_from:
            cur = came_from[cur]
            path.append(cur)
        path.reverse()
        return self._compress(path)

    @staticmethod
    def _compress(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if len(path) <= 2:
            return path
        out = [path[0]]
        prev_dc = path[1][0] - path[0][0]
        prev_dr = path[1][1] - path[0][1]
        for i in range(1, len(path) - 1):
            dc = path[i + 1][0] - path[i][0]
            dr = path[i + 1][1] - path[i][1]
            if dc != prev_dc or dr != prev_dr:
                out.append(path[i])
            prev_dc, prev_dr = dc, dr
        out.append(path[-1])
        return out

    def _nearest_walkable(
        self,
        tile: tuple[int, int],
        blocked: set[tuple[int, int]],
        walkable_fn,
        *,
        max_radius: int = 26,
    ) -> tuple[int, int] | None:
        if self._is_walkable(tile, blocked, walkable_fn):
            return tile
        tc, tr = tile
        max_r = max(self.cols, self.rows)
        end_radius = min(max_r, max(1, int(max_radius)) + 1)
        for radius in range(1, end_radius):
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if abs(dc) != radius and abs(dr) != radius:
                        continue
                    cand = (tc + dc, tr + dr)
                    if self._is_walkable(cand, blocked, walkable_fn):
                        return cand
        return None

    def _normalize_start(
        self,
        tile: tuple[int, int],
        blocked: set[tuple[int, int]],
        walkable_fn,
        *,
        max_radius: int = 16,
    ) -> tuple[int, int] | None:
        if tile in blocked:
            blocked = set(blocked)
            blocked.discard(tile)
        if self._is_walkable(tile, blocked, walkable_fn):
            return tile
        return self._nearest_walkable(tile, blocked, walkable_fn, max_radius=max_radius)

    def _is_walkable(
        self,
        tile: tuple[int, int],
        blocked: set[tuple[int, int]],
        walkable_fn,
    ) -> bool:
        c, r = tile
        if c < 0 or r < 0 or c >= self.cols or r >= self.rows:
            return False
        if tile in blocked:
            return False
        if walkable_fn is not None:
            return bool(walkable_fn(c, r))
        if self.walkable is not None:
            return self.walkable[r][c]
        return self.tilemap.is_walkable(c, r)

    def _in_bounds(self, tile: tuple[int, int]) -> bool:
        c, r = tile
        return 0 <= c < self.cols and 0 <= r < self.rows
