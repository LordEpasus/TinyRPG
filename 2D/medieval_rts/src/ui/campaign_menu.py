from __future__ import annotations

import pygame

from src.ui.display import toggle_fullscreen


class CampaignMenu:
    ACTION_BACK = -1
    ACTION_EXIT = -2

    def __init__(self) -> None:
        self.font_title = pygame.font.SysFont("georgia", 46, bold=True)
        self.font_sub = pygame.font.SysFont("georgia", 22)
        self.font_btn = pygame.font.SysFont("georgia", 24, bold=True)
        self.font_hint = pygame.font.SysFont("georgia", 16)
        self._buttons: list[tuple[int, pygame.Rect]] = []
        self._idx = 0

    def run(self, screen: pygame.Surface, clock: pygame.time.Clock) -> int:
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return self.ACTION_EXIT
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_F11 or (
                        ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
                        and (ev.mod & pygame.KMOD_ALT)
                    ):
                        screen = toggle_fullscreen()
                        continue
                    if ev.key == pygame.K_ESCAPE:
                        return self.ACTION_BACK
                    if ev.key in (pygame.K_UP, pygame.K_w):
                        self._idx = max(0, self._idx - 1)
                    if ev.key in (pygame.K_DOWN, pygame.K_s):
                        self._idx = min(2, self._idx + 1)
                    if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if self._idx == 0:
                            return 1
                        if self._idx == 1:
                            return 2
                        return self.ACTION_BACK
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    hit = self._hit(ev.pos)
                    if hit is not None:
                        return hit

            hover = self._hover(pygame.mouse.get_pos())
            if hover is not None:
                self._idx = hover
            self._draw(screen, hover)
            pygame.display.flip()
            clock.tick(60)

    def _draw(self, screen: pygame.Surface, hover: int | None) -> None:
        sw, sh = screen.get_size()
        screen.fill((15, 22, 34))

        panel_w = min(860, sw - 80)
        panel_h = min(520, sh - 80)
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (235, 230, 218, 246), panel.get_rect(), border_radius=18)
        pygame.draw.rect(panel, (72, 62, 50), panel.get_rect(), 2, border_radius=18)
        screen.blit(panel, (px, py))

        title = self.font_title.render("Campaign", True, (30, 30, 30))
        screen.blit(title, (px + (panel_w - title.get_width()) // 2, py + 34))

        sub = self.font_sub.render("Gorev secimi", True, (56, 58, 60))
        screen.blit(sub, (px + (panel_w - sub.get_width()) // 2, py + 92))

        self._buttons.clear()
        labels = [
            (1, "Gorev 1 - Kurulus"),
            (2, "Gorev 2 - Kusatma"),
            (self.ACTION_BACK, "Geri"),
        ]

        bw, bh = 420, 70
        bx = px + (panel_w - bw) // 2
        start_y = py + 156
        for i, (action, label) in enumerate(labels):
            by = start_y + i * 94
            rect = pygame.Rect(bx, by, bw, bh)
            self._buttons.append((action, rect))
            sel = i == self._idx
            hov = hover == i
            self._draw_button(screen, rect, label, selected=sel, hovered=hov)

        hint = self.font_hint.render("Sol tik veya Enter ile sec. ESC: geri", True, (64, 66, 68))
        screen.blit(hint, (px + (panel_w - hint.get_width()) // 2, py + panel_h - 42))

    def _draw_button(self, screen: pygame.Surface, rect: pygame.Rect, text: str, *, selected: bool, hovered: bool) -> None:
        if selected:
            fill, border, tc = (74, 126, 178), (22, 54, 86), (245, 249, 252)
        elif hovered:
            fill, border, tc = (92, 142, 192), (30, 64, 98), (250, 252, 255)
        else:
            fill, border, tc = (126, 174, 220), (44, 86, 126), (18, 28, 40)
        pygame.draw.rect(screen, fill, rect, border_radius=11)
        pygame.draw.rect(screen, border, rect, 2, border_radius=11)
        txt = self.font_btn.render(text, True, tc)
        screen.blit(txt, (rect.x + (rect.width - txt.get_width()) // 2, rect.y + (rect.height - txt.get_height()) // 2))

    def _hit(self, pos: tuple[int, int]) -> int | None:
        for i, (action, rect) in enumerate(self._buttons):
            if rect.collidepoint(pos):
                self._idx = i
                return action
        return None

    def _hover(self, pos: tuple[int, int]) -> int | None:
        for i, (_, rect) in enumerate(self._buttons):
            if rect.collidepoint(pos):
                return i
        return None
