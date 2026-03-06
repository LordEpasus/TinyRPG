from __future__ import annotations

import pygame

from src.ui.display import (
    get_display_state,
    list_resolution_presets,
    set_borderless_fullscreen,
    set_window_resolution,
    toggle_fullscreen,
)


class GraphicsMenu:
    ACTION_BACK = "back"
    ACTION_EXIT = "exit"

    def __init__(self) -> None:
        self.font_title = pygame.font.SysFont("georgia", 44, bold=True)
        self.font_sub = pygame.font.SysFont("georgia", 22)
        self.font_btn = pygame.font.SysFont("georgia", 24, bold=True)
        self.font_hint = pygame.font.SysFont("georgia", 16)
        self.font_res = pygame.font.SysFont("monospace", 17)
        self._resolution_buttons: list[tuple[pygame.Rect, tuple[int, int]]] = []

    def run(self, screen: pygame.Surface, clock: pygame.time.Clock) -> str:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return self.ACTION_EXIT
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return self.ACTION_BACK
                    if event.key == pygame.K_F11 or (
                        event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
                        and (event.mod & pygame.KMOD_ALT)
                    ):
                        screen = toggle_fullscreen()
                        continue
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self._back_rect(screen).collidepoint(event.pos):
                        return self.ACTION_BACK
                    if self._mode_rect(screen).collidepoint(event.pos):
                        state = get_display_state()
                        screen = set_borderless_fullscreen(not bool(state["fullscreen"]))
                        continue
                    for rect, res in self._resolution_buttons:
                        if rect.collidepoint(event.pos):
                            screen = set_window_resolution(res)
                            break

            self._draw(screen)
            pygame.display.flip()
            clock.tick(60)

    def _draw(self, screen: pygame.Surface) -> None:
        sw, sh = screen.get_size()
        state = get_display_state()
        fullscreen = bool(state["fullscreen"])
        window_size = tuple(state["window_size"])
        active_size = tuple(state["active_size"])
        desktop_size = tuple(state["desktop_size"])

        screen.fill((15, 22, 34))
        for i, color in enumerate(((20, 30, 46), (18, 26, 40), (16, 22, 34))):
            band = pygame.Rect(0, i * (sh // 3), sw, sh // 3 + 2)
            pygame.draw.rect(screen, color, band)

        panel_w = min(920, sw - 80)
        panel_h = min(620, sh - 80)
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (236, 231, 218, 246), panel.get_rect(), border_radius=18)
        pygame.draw.rect(panel, (72, 62, 50), panel.get_rect(), 2, border_radius=18)
        screen.blit(panel, (px, py))

        title = self.font_title.render("Grafik Ayarlari", True, (28, 32, 38))
        screen.blit(title, (px + (panel_w - title.get_width()) // 2, py + 28))

        mode_label = "Ekran Modu: Cercevesiz Tam Ekran" if fullscreen else "Ekran Modu: Pencere"
        sub = self.font_sub.render(mode_label, True, (54, 60, 68))
        screen.blit(sub, (px + 42, py + 108))

        mode_rect = self._mode_rect(screen)
        mode_btn_text = "Pencereye Gec" if fullscreen else "Cercevesiz Tam Ekran"
        self._draw_button(screen, mode_rect, mode_btn_text, selected=fullscreen)

        active_text = f"Aktif: {active_size[0]} x {active_size[1]}   Masaustu: {desktop_size[0]} x {desktop_size[1]}"
        active = self.font_hint.render(active_text, True, (64, 68, 74))
        screen.blit(active, (px + 42, py + 188))

        res_title = self.font_sub.render("Cozunurluk (Pencere)", True, (48, 54, 60))
        screen.blit(res_title, (px + 42, py + 224))

        self._resolution_buttons.clear()
        presets = list_resolution_presets()
        cols = 3
        gap_x = 12
        gap_y = 10
        card_w = (panel_w - 84 - (cols - 1) * gap_x) // cols
        card_h = 42
        start_x = px + 42
        start_y = py + 262
        for i, res in enumerate(presets):
            row_i = i // cols
            col_i = i % cols
            rx = start_x + col_i * (card_w + gap_x)
            ry = start_y + row_i * (card_h + gap_y)
            rect = pygame.Rect(rx, ry, card_w, card_h)
            self._resolution_buttons.append((rect, res))
            selected = tuple(res) == tuple(window_size)
            hover = rect.collidepoint(pygame.mouse.get_pos())
            if selected:
                fill, border, tc = (78, 130, 184), (24, 56, 88), (246, 250, 252)
            elif hover:
                fill, border, tc = (164, 188, 214), (72, 94, 120), (20, 30, 42)
            else:
                fill, border, tc = (198, 210, 224), (96, 116, 138), (28, 38, 50)
            pygame.draw.rect(screen, fill, rect, border_radius=8)
            pygame.draw.rect(screen, border, rect, 1, border_radius=8)
            txt = self.font_res.render(f"{res[0]} x {res[1]}", True, tc)
            screen.blit(txt, (rect.x + (rect.width - txt.get_width()) // 2, rect.y + 11))

        note = (
            "Not: Cercevesiz tam ekranda masaustu cozunurlugu kullanilir."
            if fullscreen
            else "Not: F11 veya Alt+Enter ile hizli tam ekran gecisi."
        )
        note_surf = self.font_hint.render(note, True, (72, 74, 78))
        screen.blit(note_surf, (px + 42, py + panel_h - 78))

        hint = self.font_hint.render(
            "Secmek icin tikla. ESC: geri", True, (64, 68, 74)
        )
        screen.blit(hint, (px + 42, py + panel_h - 54))

        self._draw_button(screen, self._back_rect(screen), "Geri")

    def _mode_rect(self, screen: pygame.Surface) -> pygame.Rect:
        sw, sh = screen.get_size()
        panel_w = min(920, sw - 80)
        panel_h = min(620, sh - 80)
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2
        return pygame.Rect(px + panel_w - 332, py + 98, 290, 48)

    def _back_rect(self, screen: pygame.Surface) -> pygame.Rect:
        sw, sh = screen.get_size()
        panel_w = min(920, sw - 80)
        panel_h = min(620, sh - 80)
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2
        return pygame.Rect(px + panel_w - 166, py + panel_h - 66, 124, 42)

    def _draw_button(self, screen: pygame.Surface, rect: pygame.Rect, text: str, *, selected: bool = False) -> None:
        hover = rect.collidepoint(pygame.mouse.get_pos())
        if selected:
            fill, border, tc = (74, 126, 178), (22, 54, 86), (245, 249, 252)
        elif hover:
            fill, border, tc = (92, 142, 192), (30, 64, 98), (250, 252, 255)
        else:
            fill, border, tc = (126, 174, 220), (44, 86, 126), (18, 28, 40)
        pygame.draw.rect(screen, fill, rect, border_radius=10)
        pygame.draw.rect(screen, border, rect, 2, border_radius=10)
        lbl = self.font_btn.render(text, True, tc)
        screen.blit(lbl, (rect.x + (rect.width - lbl.get_width()) // 2, rect.y + (rect.height - lbl.get_height()) // 2))
