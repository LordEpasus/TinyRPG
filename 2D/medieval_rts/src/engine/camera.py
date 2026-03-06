import pygame
from settings import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    MAP_COLS, MAP_ROWS, TILE_SIZE,
    CAM_SPEED, CAM_EDGE_SCROLL, CAM_EDGE_MARGIN,
    ZOOM_MIN, ZOOM_MAX, ZOOM_DEFAULT, ZOOM_STEP,
)


class Camera:
    def __init__(self):
        self.offset = pygame.math.Vector2(0, 0)
        self.zoom   = ZOOM_DEFAULT
        self._drag  = None   # (start_mouse_vec, start_offset_vec) for MMB pan

    @staticmethod
    def _screen_size() -> tuple[int, int]:
        surf = pygame.display.get_surface()
        if surf is None:
            return SCREEN_WIDTH, SCREEN_HEIGHT
        return surf.get_width(), surf.get_height()

    # ── Events ───────────────────────────────────────────────────────────────
    def handle_event(self, event: pygame.Event) -> None:
        if event.type == pygame.MOUSEWHEEL:
            self._zoom_toward_mouse(event.y, pygame.mouse.get_pos())

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 2:  # middle mouse
                self._drag = (
                    pygame.math.Vector2(event.pos),
                    pygame.math.Vector2(self.offset),
                )

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                self._drag = None

        elif event.type == pygame.MOUSEMOTION:
            if self._drag is not None:
                start_m, start_off = self._drag
                delta = pygame.math.Vector2(event.pos) - start_m
                self.offset = start_off - delta / self.zoom
                self._clamp()

    # ── Update (keyboard + edge scroll) ──────────────────────────────────────
    def update(self, dt: float, keys, *, allow_edge_scroll: bool = True, allow_keyboard_scroll: bool = True) -> None:
        speed = CAM_SPEED * dt / self.zoom
        moved = False

        if allow_keyboard_scroll:
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                self.offset.x -= speed; moved = True
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                self.offset.x += speed; moved = True
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                self.offset.y -= speed; moved = True
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                self.offset.y += speed; moved = True

        if CAM_EDGE_SCROLL and allow_edge_scroll and self._drag is None:
            sw, sh = self._screen_size()
            mx, my = pygame.mouse.get_pos()
            if mx < CAM_EDGE_MARGIN:
                self.offset.x -= speed; moved = True
            elif mx > sw - CAM_EDGE_MARGIN:
                self.offset.x += speed; moved = True
            if my < CAM_EDGE_MARGIN:
                self.offset.y -= speed; moved = True
            elif my > sh - CAM_EDGE_MARGIN:
                self.offset.y += speed; moved = True

        if moved:
            self._clamp()

    # ── Coordinate helpers ────────────────────────────────────────────────────
    def world_to_screen(self, world_pos) -> tuple:
        wx, wy = world_pos
        return (
            (wx - self.offset.x) * self.zoom,
            (wy - self.offset.y) * self.zoom,
        )

    def screen_to_world(self, screen_pos) -> tuple:
        sx, sy = screen_pos
        return (
            sx / self.zoom + self.offset.x,
            sy / self.zoom + self.offset.y,
        )

    def screen_to_tile(self, screen_pos) -> tuple:
        wx, wy = self.screen_to_world(screen_pos)
        return int(wx // TILE_SIZE), int(wy // TILE_SIZE)

    def get_visible_tile_range(self) -> tuple:
        """(col_min, row_min, col_max, row_max) of tiles touching the screen."""
        sw, sh = self._screen_size()
        wx0, wy0 = self.screen_to_world((0, 0))
        wx1, wy1 = self.screen_to_world((sw, sh))
        c0 = max(0, int(wx0 // TILE_SIZE))
        r0 = max(0, int(wy0 // TILE_SIZE))
        c1 = min(MAP_COLS - 1, int(wx1 // TILE_SIZE) + 1)
        r1 = min(MAP_ROWS - 1, int(wy1 // TILE_SIZE) + 1)
        return c0, r0, c1, r1

    def center_on_world(self, wx: float, wy: float) -> None:
        sw, sh = self._screen_size()
        self.offset.x = wx - sw / (2 * self.zoom)
        self.offset.y = wy - sh / (2 * self.zoom)
        self._clamp()

    # ── Private ───────────────────────────────────────────────────────────────
    def _zoom_toward_mouse(self, scroll_y: int, mouse_pos) -> None:
        world_before = self.screen_to_world(mouse_pos)
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom + scroll_y * ZOOM_STEP))
        world_after = self.screen_to_world(mouse_pos)
        # Keep the world-point under the cursor stationary
        diff = pygame.math.Vector2(world_after) - pygame.math.Vector2(world_before)
        self.offset -= diff
        self._clamp()

    def _clamp(self) -> None:
        sw, sh = self._screen_size()
        world_w = MAP_COLS * TILE_SIZE
        world_h = MAP_ROWS * TILE_SIZE
        vis_w   = sw / self.zoom
        vis_h   = sh / self.zoom
        self.offset.x = max(0.0, min(world_w - vis_w, self.offset.x))
        self.offset.y = max(0.0, min(world_h - vis_h, self.offset.y))
