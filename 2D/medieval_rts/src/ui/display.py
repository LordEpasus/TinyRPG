from __future__ import annotations

from dataclasses import dataclass

import pygame

from settings import FULLSCREEN_DEFAULT, SCREEN_HEIGHT, SCREEN_WIDTH


_DEFAULT_WINDOW_SIZE = (SCREEN_WIDTH, SCREEN_HEIGHT)


@dataclass(slots=True)
class _DisplayState:
    fullscreen: bool = FULLSCREEN_DEFAULT
    window_size: tuple[int, int] = _DEFAULT_WINDOW_SIZE


_state = _DisplayState()


def _normalize_resolution(resolution: tuple[int, int]) -> tuple[int, int]:
    w = max(800, int(resolution[0]))
    h = max(600, int(resolution[1]))
    return w, h


def _desktop_size() -> tuple[int, int]:
    info = pygame.display.Info()
    w = int(getattr(info, "current_w", 0) or 0)
    h = int(getattr(info, "current_h", 0) or 0)
    if w <= 0 or h <= 0:
        return _DEFAULT_WINDOW_SIZE
    return w, h


def list_resolution_presets() -> list[tuple[int, int]]:
    desktop = _desktop_size()
    presets = {
        _DEFAULT_WINDOW_SIZE,
        desktop,
        (1024, 768),
        (1152, 648),
        (1280, 720),
        (1366, 768),
        (1440, 900),
        (1600, 900),
        (1920, 1080),
        (2560, 1440),
    }
    out = [
        _normalize_resolution(size)
        for size in presets
        if size[0] <= desktop[0] and size[1] <= desktop[1]
    ]
    if not out:
        out = [_DEFAULT_WINDOW_SIZE]
    out.sort(key=lambda s: (s[0] * s[1], s[0]))
    return out


def apply_display_mode(
    *,
    fullscreen: bool | None = None,
    resolution: tuple[int, int] | None = None,
) -> pygame.Surface:
    if fullscreen is not None:
        _state.fullscreen = bool(fullscreen)
    if resolution is not None:
        _state.window_size = _normalize_resolution(resolution)

    if _state.fullscreen:
        flags = pygame.NOFRAME | pygame.DOUBLEBUF
        size = _desktop_size()
    else:
        flags = pygame.RESIZABLE | pygame.DOUBLEBUF
        size = _state.window_size

    return pygame.display.set_mode(size, flags)


def ensure_display_surface() -> pygame.Surface:
    surf = pygame.display.get_surface()
    if surf is None:
        return apply_display_mode(fullscreen=_state.fullscreen, resolution=_state.window_size)
    return surf


def toggle_fullscreen() -> pygame.Surface:
    return apply_display_mode(fullscreen=not _state.fullscreen)


def set_borderless_fullscreen(enabled: bool) -> pygame.Surface:
    return apply_display_mode(fullscreen=enabled)


def set_window_resolution(resolution: tuple[int, int]) -> pygame.Surface:
    if _state.fullscreen:
        _state.window_size = _normalize_resolution(resolution)
        return ensure_display_surface()
    return apply_display_mode(resolution=resolution)


def get_display_state() -> dict[str, object]:
    surf = pygame.display.get_surface()
    active_size = surf.get_size() if surf is not None else _state.window_size
    return {
        "fullscreen": _state.fullscreen,
        "window_size": _state.window_size,
        "active_size": active_size,
        "desktop_size": _desktop_size(),
    }
