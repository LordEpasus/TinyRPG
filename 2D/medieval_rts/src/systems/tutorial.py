from __future__ import annotations

import pygame


class TutorialManager:
    def __init__(self, *, enabled: bool, initial_house_count: int) -> None:
        self.enabled = bool(enabled)
        self.initial_house_count = int(initial_house_count)
        self.collected_resources = 0
        self.step_index = 0
        self.done = False

        self.steps = [
            "1) Bir isci sec (sol tik)",
            "2) Sag tik ile kaynak topla",
            "3) Bir House insa et",
        ]

    def add_collected(self, amount: int) -> None:
        if not self.enabled or self.done:
            return
        self.collected_resources += max(0, int(amount))

    def update(self, *, worker_selected: bool, current_house_count: int) -> None:
        if not self.enabled or self.done:
            return

        if self.step_index == 0 and worker_selected:
            self.step_index = 1
        if self.step_index == 1 and self.collected_resources >= 40:
            self.step_index = 2
        if self.step_index == 2 and int(current_house_count) > self.initial_house_count:
            self.step_index = 3
            self.done = True

    def draw(self, screen: pygame.Surface, font_md: pygame.font.Font, font_sm: pygame.font.Font) -> None:
        if not self.enabled:
            return

        panel_w = 430
        panel_h = 108
        x = max(10, (screen.get_width() - panel_w) // 2)
        y = 8

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (16, 24, 34, 216), panel.get_rect(), border_radius=10)
        pygame.draw.rect(panel, (92, 138, 182, 240), panel.get_rect(), 1, border_radius=10)
        screen.blit(panel, (x, y))

        title = "Tutorial Tamamlandi" if self.done else "Tutorial"
        tcolor = (136, 232, 156) if self.done else (228, 236, 246)
        ts = font_md.render(title, True, tcolor)
        screen.blit(ts, (x + 12, y + 8))

        for i, text in enumerate(self.steps):
            done = i < self.step_index
            color = (154, 232, 166) if done else (206, 218, 230)
            prefix = "[x]" if done else "[ ]"
            line = font_sm.render(f"{prefix} {text}", True, color)
            screen.blit(line, (x + 12, y + 34 + i * 21))
