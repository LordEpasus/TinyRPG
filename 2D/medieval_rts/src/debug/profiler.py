from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import time
from typing import Iterator

import pygame


@dataclass(slots=True)
class ProfileSample:
    frame_ms: float = 0.0
    sections: dict[str, float] = field(default_factory=dict)
    counters: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class HotspotReport:
    generated_at: float
    sections: list[tuple[str, float]]
    counters: list[tuple[str, float]]


class ProfilerManager:
    def __init__(self, *, enabled: bool = True, history_frames: int = 180, capture_seconds: float = 10.0) -> None:
        self.enabled = bool(enabled)
        self.history: deque[ProfileSample] = deque(maxlen=max(30, int(history_frames)))
        self.capture_seconds = max(2.0, float(capture_seconds))
        self.overlay_visible = False
        self.capture_active = False
        self.capture_remaining_s = 0.0
        self._frame = ProfileSample()
        self._frame_start = 0.0
        self._section_stack: list[tuple[str, float]] = []
        self._last_report = HotspotReport(0.0, [], [])
        self._fonts_ready = False
        self._font_title: pygame.font.Font | None = None
        self._font_text: pygame.font.Font | None = None
        self._warning_timer_s = 0.0

    def toggle_overlay(self) -> None:
        if not self.enabled:
            return
        self.overlay_visible = not self.overlay_visible
        self._warning_timer_s = 2.0

    def toggle_capture(self) -> None:
        if not self.enabled:
            return
        self.capture_active = not self.capture_active
        self.capture_remaining_s = self.capture_seconds if self.capture_active else 0.0
        self._warning_timer_s = 2.0

    def finalize_report(self) -> HotspotReport:
        sections: dict[str, float] = {}
        counters: dict[str, float] = {}
        for sample in list(self.history):
            for key, value in sample.sections.items():
                sections[key] = max(sections.get(key, 0.0), float(value))
            for key, value in sample.counters.items():
                counters[key] = max(counters.get(key, 0.0), float(value))
        ordered_sections = sorted(sections.items(), key=lambda item: item[1], reverse=True)
        ordered_counters = sorted(counters.items(), key=lambda item: item[1], reverse=True)
        self._last_report = HotspotReport(time.perf_counter(), ordered_sections[:8], ordered_counters[:8])
        self._warning_timer_s = 2.6
        return self._last_report

    def begin_frame(self) -> None:
        if not self.enabled:
            return
        self._frame_start = time.perf_counter()
        self._frame = ProfileSample()
        self._section_stack.clear()

    def end_frame(self, dt: float) -> None:
        if not self.enabled:
            return
        self._frame.frame_ms = (time.perf_counter() - self._frame_start) * 1000.0
        self.history.append(self._frame)
        if self.capture_active:
            self.capture_remaining_s -= max(0.0, float(dt))
            if self.capture_remaining_s <= 0.0:
                self.capture_active = False
                self.capture_remaining_s = 0.0
                self.finalize_report()
        if self._warning_timer_s > 0.0:
            self._warning_timer_s = max(0.0, self._warning_timer_s - max(0.0, float(dt)))

    @contextmanager
    def section(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._frame.sections[name] = self._frame.sections.get(name, 0.0) + elapsed_ms

    def set_counter(self, name: str, value: float | int) -> None:
        if not self.enabled:
            return
        self._frame.counters[name] = float(value)

    def add_counter(self, name: str, value: float | int) -> None:
        if not self.enabled:
            return
        self._frame.counters[name] = self._frame.counters.get(name, 0.0) + float(value)

    def latest_summary(self) -> dict[str, float]:
        if not self.history:
            return {}
        count = float(len(self.history))
        avg: dict[str, float] = {"frame_ms": sum(sample.frame_ms for sample in self.history) / count}
        section_keys = {key for sample in self.history for key in sample.sections}
        counter_keys = {key for sample in self.history for key in sample.counters}
        for key in section_keys:
            avg[key] = sum(sample.sections.get(key, 0.0) for sample in self.history) / count
        for key in counter_keys:
            avg[key] = sum(sample.counters.get(key, 0.0) for sample in self.history) / count
        return avg

    def draw_overlay(self, screen: pygame.Surface) -> None:
        if not self.enabled or not self.overlay_visible:
            return
        self._ensure_fonts()
        if self._font_title is None or self._font_text is None:
            return
        summary = self.latest_summary()
        panel_w = 320
        lines = [
            f"Kare {summary.get('frame_ms', 0.0):5.1f} ms",
            f"Update {summary.get('update_ms', 0.0):5.1f}  Render {summary.get('render_ms', 0.0):5.1f}",
            f"AI {summary.get('ai_ms', 0.0):5.1f}  Politika {summary.get('politics_ms', 0.0):5.1f}",
            f"Diplomasi {summary.get('diplomacy_ms', 0.0):5.1f}  Bina {summary.get('buildings_ms', 0.0):5.1f}",
            f"Path {summary.get('path_ms', 0.0):5.1f}  Mini {summary.get('minimap_ms', 0.0):5.1f}",
            f"Entity cizim {summary.get('entity_draw_count', 0.0):4.0f}  Gorunen karo {summary.get('visible_tile_count', 0.0):4.0f}",
        ]
        if self.capture_active:
            lines.append(f"Kayit acik: {self.capture_remaining_s:0.1f}s")
        elif self._last_report.sections:
            top = self._last_report.sections[0]
            lines.append(f"Sicak nokta: {top[0]} {top[1]:0.1f} ms")
        y = 220
        panel_h = 28 + len(lines) * 18
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (10, 16, 22, 214), panel.get_rect(), border_radius=12)
        pygame.draw.rect(panel, (86, 122, 150, 238), panel.get_rect(), 1, border_radius=12)
        screen.blit(panel, (14, y))
        title = self._font_title.render("Profiler [F8/F9/F10]", True, (230, 236, 244))
        screen.blit(title, (24, y + 10))
        for idx, line in enumerate(lines):
            surf = self._font_text.render(line, True, (208, 222, 236))
            screen.blit(surf, (24, y + 34 + idx * 18))
        if self._warning_timer_s > 0.0:
            info = self._font_text.render("Olcum acik; hafif FPS maliyeti var.", True, (246, 210, 142))
            screen.blit(info, (24, y + panel_h - 18))

    def draw_report(self, screen: pygame.Surface) -> None:
        if not self.enabled or not self.overlay_visible or not self._last_report.sections:
            return
        self._ensure_fonts()
        if self._font_title is None or self._font_text is None:
            return
        x = screen.get_width() - 348
        y = screen.get_height() - 218
        panel = pygame.Surface((334, 204), pygame.SRCALPHA)
        pygame.draw.rect(panel, (10, 16, 22, 214), panel.get_rect(), border_radius=12)
        pygame.draw.rect(panel, (110, 148, 176, 238), panel.get_rect(), 1, border_radius=12)
        screen.blit(panel, (x, y))
        title = self._font_title.render("Hotspot Ozeti", True, (236, 240, 246))
        screen.blit(title, (x + 12, y + 10))
        for idx, (name, value) in enumerate(self._last_report.sections[:6]):
            surf = self._font_text.render(f"{name}: {value:0.1f} ms", True, (210, 224, 236))
            screen.blit(surf, (x + 12, y + 34 + idx * 18))
        base_y = y + 146
        for idx, (name, value) in enumerate(self._last_report.counters[:3]):
            surf = self._font_text.render(f"{name}: {value:0.0f}", True, (180, 208, 228))
            screen.blit(surf, (x + 12, base_y + idx * 16))

    def _ensure_fonts(self) -> None:
        if self._fonts_ready:
            return
        self._fonts_ready = True
        self._font_title = pygame.font.SysFont("georgia", 15, bold=True)
        self._font_text = pygame.font.SysFont("georgia", 13)
