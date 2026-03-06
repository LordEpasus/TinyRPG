from __future__ import annotations

import os

import pygame

from settings import FLARE_SPRITES, TITLE
from src.ui.display import toggle_fullscreen


class MainMenu:
    ACTION_NEW_GAME = "new_game"
    ACTION_TUTORIAL = "tutorial"
    ACTION_CAMPAIGN = "campaign"
    ACTION_REPLAY = "replay"
    ACTION_MULTIPLAYER = "multiplayer"
    ACTION_GRAPHICS = "graphics"
    ACTION_EXIT = "exit"

    def __init__(self) -> None:
        self.font_title = pygame.font.SysFont("georgia", 54, bold=True)
        self.font_sub = pygame.font.SysFont("georgia", 20)
        self.font_button = pygame.font.SysFont("georgia", 24, bold=True)
        self.font_hint = pygame.font.SysFont("georgia", 16)
        self._flare_button = self._load_flare_button()
        self._button_cache: dict[tuple[int, int], pygame.Surface] = {}
        self._buttons: list[tuple[str, pygame.Rect, str]] = []
        self._keyboard_index = 0

    def _load_flare_button(self) -> pygame.Surface | None:
        path = os.path.join(FLARE_SPRITES, "menus", "button_default.png")
        if not os.path.exists(path):
            return None
        try:
            return pygame.image.load(path).convert_alpha()
        except pygame.error:
            return None

    def _scaled_flare_button(self, w: int, h: int) -> pygame.Surface | None:
        if self._flare_button is None:
            return None
        key = (max(1, int(w)), max(1, int(h)))
        cached = self._button_cache.get(key)
        if cached is not None:
            return cached
        scaled = pygame.transform.smoothscale(self._flare_button, key)
        self._button_cache[key] = scaled
        return scaled

    def run(self, screen: pygame.Surface, clock: pygame.time.Clock) -> str:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return self.ACTION_EXIT
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11 or (
                        event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
                        and (event.mod & pygame.KMOD_ALT)
                    ):
                        screen = toggle_fullscreen()
                        continue
                    if event.key == pygame.K_ESCAPE:
                        return self.ACTION_EXIT
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if 0 <= self._keyboard_index < len(self._buttons):
                            return self._buttons[self._keyboard_index][0]
                        return self.ACTION_NEW_GAME
                    if event.key in (pygame.K_UP, pygame.K_w):
                        self._keyboard_index = max(0, self._keyboard_index - 1)
                    if event.key in (pygame.K_DOWN, pygame.K_s):
                        self._keyboard_index = min(len(self._menu_items()) - 1, self._keyboard_index + 1)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    hit = self._hit_button(event.pos)
                    if hit is not None:
                        return hit

            hover_idx = self._hover_index(pygame.mouse.get_pos())
            if hover_idx is not None:
                self._keyboard_index = hover_idx
            self._draw(screen, hover_idx)
            pygame.display.flip()
            clock.tick(60)

    def _draw(self, screen: pygame.Surface, hover_idx: int | None) -> None:
        sw, sh = screen.get_size()
        screen.fill((17, 24, 36))
        self._buttons.clear()

        # Subtle background bands for depth.
        for i, color in enumerate(((22, 30, 46), (20, 28, 42), (18, 26, 38))):
            band = pygame.Rect(0, i * (sh // 3), sw, sh // 3 + 2)
            pygame.draw.rect(screen, color, band)

        panel_w = 760
        panel_h = min(620, sh - 48)
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        # Shadow + panel.
        shadow = pygame.Surface((panel_w + 20, panel_h + 20), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 110), shadow.get_rect(), border_radius=20)
        screen.blit(shadow, (px - 10, py - 2))
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (240, 235, 222, 244), panel.get_rect(), border_radius=18)
        pygame.draw.rect(panel, (74, 62, 47), panel.get_rect(), 2, border_radius=18)
        screen.blit(panel, (px, py))

        title = self.font_title.render(TITLE, True, (30, 30, 30))
        subtitle = self.font_sub.render("Tek Oyuncu RTS", True, (54, 54, 54))
        screen.blit(title, (px + (panel_w - title.get_width()) // 2, py + 72))
        screen.blit(subtitle, (px + (panel_w - subtitle.get_width()) // 2, py + 136))

        items = self._menu_items()
        bw = 420
        bh = 48
        gap = 8
        bx = px + (panel_w - bw) // 2
        total_h = len(items) * bh + max(0, len(items) - 1) * gap
        start_y = py + 160
        max_bottom = py + panel_h - 64
        if start_y + total_h > max_bottom:
            start_y = py + 124
        for i, (action, label) in enumerate(items):
            by = start_y + i * (bh + gap)
            rect = pygame.Rect(bx, by, bw, bh)
            self._buttons.append((action, rect, label))
            selected = i == self._keyboard_index
            hovered = hover_idx == i
            self._draw_button(screen, rect, label, selected=selected, hovered=hovered)

        hint = self.font_hint.render(
            "Secmek icin sol tikla veya [Up/Down + Enter]. F11: Tam ekran",
            True,
            (52, 52, 52),
        )
        screen.blit(hint, (px + (panel_w - hint.get_width()) // 2, py + panel_h - 42))

    def _draw_button(self, screen: pygame.Surface, rect: pygame.Rect, text: str, *, selected: bool, hovered: bool) -> None:
        flare_btn = self._scaled_flare_button(rect.width, rect.height)
        if flare_btn is not None:
            screen.blit(flare_btn, rect.topleft)
            tint = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            if selected:
                tint.fill((70, 136, 212, 88))
                text_color = (247, 250, 255)
            elif hovered:
                tint.fill((86, 150, 226, 66))
                text_color = (247, 250, 255)
            else:
                tint.fill((54, 104, 166, 48))
                text_color = (232, 241, 250)
            screen.blit(tint, rect.topleft)
            pygame.draw.rect(screen, (20, 44, 72), rect, 2, border_radius=12)
            label = self.font_button.render(text, True, text_color)
            screen.blit(
                label,
                (rect.x + (rect.width - label.get_width()) // 2, rect.y + (rect.height - label.get_height()) // 2),
            )
            return

        if selected:
            fill = (74, 126, 178)
            border = (22, 54, 86)
            text_color = (245, 249, 252)
        elif hovered:
            fill = (92, 142, 192)
            border = (30, 64, 98)
            text_color = (250, 252, 255)
        else:
            fill = (126, 174, 220)
            border = (44, 86, 126)
            text_color = (18, 28, 40)
        pygame.draw.rect(screen, fill, rect, border_radius=12)
        pygame.draw.rect(screen, border, rect, 2, border_radius=12)
        label = self.font_button.render(text, True, text_color)
        screen.blit(
            label,
            (rect.x + (rect.width - label.get_width()) // 2, rect.y + (rect.height - label.get_height()) // 2),
        )

    def _menu_items(self) -> tuple[tuple[str, str], ...]:
        return (
            (self.ACTION_NEW_GAME, "Yeni Oyun"),
            (self.ACTION_TUTORIAL, "Tutorial"),
            (self.ACTION_CAMPAIGN, "Campaign"),
            (self.ACTION_REPLAY, "Replay (Son Mac)"),
            (self.ACTION_MULTIPLAYER, "Cok Oyunculu"),
            (self.ACTION_GRAPHICS, "Grafik Ayarlari"),
            (self.ACTION_EXIT, "Cikis"),
        )

    def _hit_button(self, pos: tuple[int, int]) -> str | None:
        for i, (action, rect, _) in enumerate(self._buttons):
            if rect.collidepoint(pos):
                self._keyboard_index = i
                return action
        return None

    def _hover_index(self, pos: tuple[int, int]) -> int | None:
        for i, (_, rect, _) in enumerate(self._buttons):
            if rect.collidepoint(pos):
                return i
        return None
