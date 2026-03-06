from __future__ import annotations

import os

import pygame

from settings import TINY_SWORDS
from src.ui.display import toggle_fullscreen


class CivilizationSelectScreen:
    COLORS = ("Blue", "Red", "Yellow", "Purple", "Black")

    def __init__(self) -> None:
        self.font_title = pygame.font.SysFont("georgia", 34, bold=True)
        self.font_body = pygame.font.SysFont("georgia", 18)
        self.font_label = pygame.font.SysFont("georgia", 20, bold=True)
        self._button_rects: list[tuple[str, pygame.Rect]] = []
        self._castle_preview = self._load_castle_previews()

    def _load_castle_previews(self) -> dict[str, pygame.Surface]:
        out: dict[str, pygame.Surface] = {}
        for civ in self.COLORS:
            path = os.path.join(TINY_SWORDS, "Buildings", f"{civ} Buildings", "Castle.png")
            if not os.path.exists(path):
                continue
            raw = pygame.image.load(path).convert_alpha()
            h = 94
            ratio = h / max(1, raw.get_height())
            w = max(1, int(raw.get_width() * ratio))
            out[civ] = pygame.transform.scale(raw, (w, h))
        return out

    def run(self, screen: pygame.Surface, clock: pygame.time.Clock) -> str | None:
        selected = self.COLORS[0]
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11 or (
                        event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
                        and (event.mod & pygame.KMOD_ALT)
                    ):
                        screen = toggle_fullscreen()
                        continue
                    if event.key == pygame.K_ESCAPE:
                        return None
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        return selected
                    if event.key == pygame.K_LEFT:
                        idx = max(0, self.COLORS.index(selected) - 1)
                        selected = self.COLORS[idx]
                    if event.key == pygame.K_RIGHT:
                        idx = min(len(self.COLORS) - 1, self.COLORS.index(selected) + 1)
                        selected = self.COLORS[idx]
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    hit = self._click_color(event.pos)
                    if hit is not None:
                        selected = hit
                        return selected
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    return selected

            self._draw(screen, selected)
            pygame.display.flip()
            clock.tick(60)

    def _draw(self, screen: pygame.Surface, selected: str) -> None:
        sw, sh = screen.get_size()
        screen.fill((22, 27, 34))
        self._button_rects.clear()

        panel_w = min(1080, sw - 36)
        panel_h = min(560, sh - 36)
        panel_x = (sw - panel_w) // 2
        panel_y = (sh - panel_h) // 2
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (14, 20, 26, 236), panel.get_rect(), border_radius=14)
        pygame.draw.rect(panel, (76, 98, 122), panel.get_rect(), 2, border_radius=14)
        screen.blit(panel, (panel_x, panel_y))

        title = self.font_title.render("Medeniyet Secimi", True, (234, 238, 246))
        screen.blit(title, (panel_x + (panel_w - title.get_width()) // 2, panel_y + 20))
        subtitle = self.font_body.render(
            "5 renk arasindan sec. Her kartta Castle onizleme var. Enter ile baslat.",
            True,
            (184, 198, 214),
        )
        screen.blit(subtitle, (panel_x + (panel_w - subtitle.get_width()) // 2, panel_y + 66))

        gap = 14
        card_w = min(196, (panel_w - 56 - gap * (len(self.COLORS) - 1)) // len(self.COLORS))
        card_h = 348
        start_x = panel_x + (panel_w - (card_w * len(self.COLORS) + gap * (len(self.COLORS) - 1))) // 2
        y = panel_y + 128
        for i, civ in enumerate(self.COLORS):
            x = start_x + i * (card_w + gap)
            rect = pygame.Rect(x, y, card_w, card_h)
            active = civ == selected
            fill = (44, 64, 84) if active else (34, 44, 56)
            border = (152, 194, 244) if active else (90, 112, 140)
            pygame.draw.rect(screen, fill, rect, border_radius=12)
            pygame.draw.rect(screen, border, rect, 2, border_radius=12)
            self._button_rects.append((civ, rect))

            lbl = self.font_label.render(civ, True, (238, 242, 248))
            screen.blit(lbl, (x + (card_w - lbl.get_width()) // 2, y + 12))

            preview = self._castle_preview.get(civ)
            if preview is not None:
                px = x + (card_w - preview.get_width()) // 2
                py = y + 52
                screen.blit(preview, (px, py))
            else:
                fb = pygame.Surface((96, 84), pygame.SRCALPHA)
                pygame.draw.rect(fb, (112, 118, 132), fb.get_rect(), border_radius=8)
                pygame.draw.rect(fb, (72, 78, 92), fb.get_rect(), 2, border_radius=8)
                px = x + (card_w - fb.get_width()) // 2
                py = y + 76
                screen.blit(fb, (px, py))

            start = self.font_body.render("Baslangic Castle", True, (202, 214, 228))
            screen.blit(start, (x + (card_w - start.get_width()) // 2, y + 214))
            tip = self.font_body.render("Secmek icin tikla", True, (170, 184, 201))
            screen.blit(tip, (x + (card_w - tip.get_width()) // 2, y + 248))

        current = self.font_label.render(f"Secilen: {selected}", True, (245, 228, 140))
        screen.blit(current, (panel_x + 24, panel_y + panel_h - 52))
        start_hint = self.font_body.render("Enter: Baslat   Esc: Geri", True, (188, 200, 216))
        screen.blit(start_hint, (panel_x + panel_w - start_hint.get_width() - 24, panel_y + panel_h - 48))

    def _click_color(self, pos: tuple[int, int]) -> str | None:
        for civ, rect in self._button_rects:
            if rect.collidepoint(pos):
                return civ
        return None
