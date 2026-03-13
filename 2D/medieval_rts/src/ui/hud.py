from __future__ import annotations

import os

import pygame

from settings import FLARE_SPRITES, TILE_DIRT, TILE_FOREST, TILE_GRASS, TILE_STONE, TILE_WATER, TINY_SWORDS
from src.ui.icons import load_icon


class GameHUD:
    _CIV_COLORS = {
        "Blue": (68, 138, 242),
        "Red": (226, 84, 74),
        "Yellow": (232, 198, 64),
        "Purple": (164, 94, 220),
        "Black": (90, 90, 96),
        "OrcRed": (200, 72, 72),
        "OrcYellow": (208, 188, 78),
        "SlimeBlue": (106, 174, 228),
        "SlimePink": (224, 138, 190),
    }

    _TILE_MINIMAP_COLORS = {
        TILE_GRASS: (139, 188, 102),
        TILE_FOREST: (84, 132, 78),
        TILE_DIRT: (199, 174, 132),
        TILE_STONE: (122, 126, 134),
        TILE_WATER: (112, 188, 201),
    }

    def __init__(self, tilemap) -> None:
        self.tilemap = tilemap
        self.font_label = pygame.font.SysFont("georgia", 14, bold=True)
        self.font_value = pygame.font.SysFont("georgia", 14)
        self.font_end = pygame.font.SysFont("georgia", 42, bold=True)
        self._skin = self._load_skin()
        self._flare = self._load_flare_skin()
        self._scaled_cache: dict[tuple[str, int, int], pygame.Surface] = {}
        self._icons = self._load_resource_icons()
        self._minimap_base = self._build_minimap_surface()
        self._minimap_scaled_cache: dict[tuple[int, int], pygame.Surface] = {}

    def _load_skin(self) -> dict[str, pygame.Surface]:
        base = os.path.join(TINY_SWORDS, "UI Elements", "UI Elements")
        skin: dict[str, pygame.Surface] = {}
        paths = {
            "paper": os.path.join(base, "Papers", "RegularPaper.png"),
            "wood": os.path.join(base, "Wood Table", "WoodTable.png"),
            "banner": os.path.join(base, "Banners", "Banner.png"),
        }
        for key, path in paths.items():
            if os.path.exists(path):
                skin[key] = pygame.image.load(path).convert_alpha()
        return skin

    def _load_flare_skin(self) -> dict[str, pygame.Surface]:
        out: dict[str, pygame.Surface] = {}
        paths = {
            "dialog_box": os.path.join(FLARE_SPRITES, "menus", "dialog_box.png"),
            "minimap": os.path.join(FLARE_SPRITES, "menus", "minimap.png"),
            "button": os.path.join(FLARE_SPRITES, "menus", "button_default.png"),
        }
        for key, path in paths.items():
            if not os.path.exists(path):
                continue
            try:
                out[key] = pygame.image.load(path).convert_alpha()
            except pygame.error:
                continue
        return out

    def _scaled_flare(self, key: str, w: int, h: int) -> pygame.Surface | None:
        base = self._flare.get(key)
        if base is None:
            return None
        w = max(1, int(w))
        h = max(1, int(h))
        ck = (key, w, h)
        cached = self._scaled_cache.get(ck)
        if cached is not None:
            return cached
        scaled = pygame.transform.smoothscale(base, (w, h))
        self._scaled_cache[ck] = scaled
        return scaled

    @staticmethod
    def _load_best_frame(path: str, size: int) -> pygame.Surface | None:
        if not os.path.exists(path):
            return None
        sheet = pygame.image.load(path).convert_alpha()
        sw, sh = sheet.get_size()
        frame_w = sh if sh > 0 else sw
        if frame_w <= 0:
            return None
        frame_w = min(frame_w, sw)
        count = max(1, sw // frame_w)
        best = None
        best_score = -1
        for i in range(count):
            raw = sheet.subsurface((i * frame_w, 0, frame_w, sh)).copy()
            bbox = raw.get_bounding_rect(min_alpha=1)
            score = bbox.width * 10000 + bbox.width * bbox.height
            if score > best_score:
                best_score = score
                best = raw
        if best is None:
            return None
        return pygame.transform.scale(best, (size, size))

    def _load_resource_icons(self) -> dict[str, pygame.Surface]:
        size = 16
        icon_names = {
            "gold": "coin_gold",
            "wood": "wood-pile",
            "stone": "stone-pile",
            "food": "wheat",
            "meat": "heart",
        }
        out: dict[str, pygame.Surface] = {}
        for key, name in icon_names.items():
            icon = load_icon(name, size=size)
            if icon is not None:
                out[key] = icon
        # Fallbacks if custom icon set is missing.
        if "gold" not in out:
            path = os.path.join(TINY_SWORDS, "Terrain", "Resources", "Gold", "Gold Stones", "Gold Stone 1.png")
            icon = self._load_best_frame(path, size=size)
            if icon is not None:
                out["gold"] = icon
        if "wood" not in out:
            path = os.path.join(TINY_SWORDS, "Terrain", "Resources", "Wood", "Wood Resource", "Wood Resource.png")
            icon = self._load_best_frame(path, size=size)
            if icon is not None:
                out["wood"] = icon
        if "stone" not in out:
            path = os.path.join(TINY_SWORDS, "Terrain", "Decorations", "Rocks", "Rock1.png")
            icon = self._load_best_frame(path, size=size)
            if icon is not None:
                out["stone"] = icon
        return out

    def _build_minimap_surface(self) -> pygame.Surface:
        surf = pygame.Surface((self.tilemap.cols, self.tilemap.rows))
        for row in range(self.tilemap.rows):
            tile_row = self.tilemap.tiles[row]
            for col in range(self.tilemap.cols):
                color = self._TILE_MINIMAP_COLORS.get(tile_row[col], (120, 120, 120))
                surf.set_at((col, row), color)
        return surf

    def draw_resources(self, screen: pygame.Surface, resource_manager) -> None:
        row_w = 182
        row_h = 24
        x = screen.get_width() - row_w - 14
        y = 10
        rows = (
            ("gold", "Altin", (241, 205, 78)),
            ("wood", "Odun", (194, 142, 95)),
            ("stone", "Tas", (184, 196, 208)),
            ("food", "Yemek", (146, 204, 98)),
            ("meat", "Et", (212, 108, 96)),
        )
        for key, label, color in rows:
            value = int(resource_manager.resources.get(key, 0))
            cap = max(1, int(resource_manager.capacity.get(key, value)))
            ratio = max(0.0, min(1.0, value / cap))

            flare_bg = self._scaled_flare("dialog_box", row_w + 18, row_h + 10)
            if flare_bg is not None:
                row_skin = flare_bg.copy()
                row_skin.set_alpha(196)
                screen.blit(row_skin, (x - 9, y - 5))
            else:
                bg = pygame.Surface((row_w, row_h), pygame.SRCALPHA)
                pygame.draw.rect(bg, (12, 16, 22, 196), bg.get_rect(), border_radius=8)
                pygame.draw.rect(bg, (58, 86, 108, 230), bg.get_rect(), 1, border_radius=8)
                screen.blit(bg, (x, y))

            icon = self._icons.get(key)
            if icon is not None:
                screen.blit(icon, (x + 5, y + (row_h - icon.get_height()) // 2))

            label_surf = self.font_label.render(label, True, color)
            value_surf = self.font_value.render(f"{value}/{cap}", True, (230, 234, 242))
            screen.blit(label_surf, (x + 26, y + 3))
            screen.blit(value_surf, (x + row_w - value_surf.get_width() - 6, y + 3))

            bar = pygame.Rect(x + 26, y + row_h - 6, row_w - 34, 3)
            pygame.draw.rect(screen, (34, 42, 52), bar, border_radius=2)
            fill_w = max(1, int((bar.width - 2) * ratio))
            pygame.draw.rect(screen, color, (bar.x + 1, bar.y + 1, fill_w, max(1, bar.height - 2)), border_radius=2)
            y += row_h + 5

    def draw_minimap(
        self,
        screen: pygame.Surface,
        camera,
        units,
        buildings,
        *,
        player_civilization: str,
        player_label: str | None = None,
        color_resolver=None,
    ) -> None:
        map_w = 160
        map_h = 120
        px = screen.get_width() - map_w - 18
        py = screen.get_height() - map_h - 18
        scale_x = map_w / max(1, self.tilemap.cols)
        scale_y = map_h / max(1, self.tilemap.rows)

        flare_frame = self._scaled_flare("minimap", map_w + 26, map_h + 34)
        if flare_frame is not None:
            mm_skin = flare_frame.copy()
            mm_skin.set_alpha(218)
            screen.blit(mm_skin, (px - 13, py - 19))

        frame = pygame.Surface((map_w + 8, map_h + 8), pygame.SRCALPHA)
        pygame.draw.rect(frame, (10, 16, 22, 210), frame.get_rect(), border_radius=8)
        pygame.draw.rect(frame, (82, 102, 126, 234), frame.get_rect(), 1, border_radius=8)
        screen.blit(frame, (px - 4, py - 4))

        # Map size already 160x120 in this project target.
        if self._minimap_base.get_size() == (map_w, map_h):
            mm = self._minimap_base
        else:
            cache_key = (map_w, map_h)
            mm = self._minimap_scaled_cache.get(cache_key)
            if mm is None:
                mm = pygame.transform.scale(self._minimap_base, (map_w, map_h))
                self._minimap_scaled_cache[cache_key] = mm
        work = mm.copy()

        def resolve_color(entity, fallback_key: str) -> tuple[int, int, int]:
            if callable(color_resolver):
                try:
                    color = color_resolver(entity)
                except Exception:
                    color = None
                if color is not None:
                    return tuple(color)
            return self._CIV_COLORS.get(fallback_key, (220, 220, 220))

        # Buildings first, units on top.
        for b in buildings:
            if b.is_dead:
                continue
            tc, tr = self.tilemap.world_to_tile(b.world_pos.x, b.world_pos.y)
            mx = px + int(tc * scale_x)
            my = py + int(tr * scale_y)
            if not (px <= mx < px + map_w and py <= my < py + map_h):
                continue
            color = resolve_color(b, getattr(b, "civilization", ""))
            work.set_at((mx - px, my - py), color)

        for u in units:
            if u.is_dead:
                continue
            tc, tr = self.tilemap.world_to_tile(u.world_pos.x, u.world_pos.y)
            mx = px + int(tc * scale_x)
            my = py + int(tr * scale_y)
            if not (px <= mx < px + map_w and py <= my < py + map_h):
                continue
            color = resolve_color(u, getattr(u, "civilization", ""))
            work.set_at((mx - px, my - py), color)
        screen.blit(work, (px, py))

        # Camera viewport rectangle.
        c0, r0, c1, r1 = camera.get_visible_tile_range()
        rx = px + int(c0 * scale_x)
        ry = py + int(r0 * scale_y)
        vw = max(1, int((c1 - c0 + 1) * scale_x))
        vh = max(1, int((r1 - r0 + 1) * scale_y))
        rect = pygame.Rect(rx, ry, vw, vh)
        pygame.draw.rect(screen, (255, 255, 255), rect, 1)

        title = self.font_label.render("Mini Harita", True, (236, 240, 246))
        screen.blit(title, (px + 4, py - 20))
        label = player_label or player_civilization
        civ_color = self._CIV_COLORS.get(
            player_civilization,
            self._CIV_COLORS.get(player_civilization.split("_", 1)[0], (235, 235, 235)),
        )
        my_civ = self.font_value.render(label, True, civ_color)
        screen.blit(my_civ, (px + map_w - my_civ.get_width(), py - 20))

    def draw_endgame(self, screen: pygame.Surface, result: str) -> None:
        sw, sh = screen.get_size()
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((8, 10, 14, 174))
        screen.blit(overlay, (0, 0))

        panel_w = 560
        panel_h = 240
        x = (sw - panel_w) // 2
        y = (sh - panel_h) // 2
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (16, 22, 30, 236), panel.get_rect(), border_radius=14)
        pygame.draw.rect(panel, (110, 142, 174, 240), panel.get_rect(), 2, border_radius=14)
        screen.blit(panel, (x, y))

        color = (136, 232, 156) if result == "victory" else (236, 132, 132)
        label = "ZAFER" if result == "victory" else "YENILGI"
        title = self.font_end.render(label, True, color)
        screen.blit(title, (x + (panel_w - title.get_width()) // 2, y + 62))
        info = self.font_label.render("Esc ile cikis yapabilirsin", True, (222, 228, 236))
        screen.blit(info, (x + (panel_w - info.get_width()) // 2, y + 164))
