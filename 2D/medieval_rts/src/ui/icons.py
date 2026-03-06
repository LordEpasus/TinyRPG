from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import pygame

from settings import GAME_ICONS


_ICON_CACHE: dict[tuple[str, int], pygame.Surface] = {}


def _try_convert_svg(svg_path: str, out_path: str, size: int) -> bool:
    out_dir = os.path.dirname(out_path)
    os.makedirs(out_dir, exist_ok=True)

    # macOS quicklook thumbnailer works well for simple monochrome game-icons SVGs.
    tmp_dir = tempfile.mkdtemp(prefix="rts_icon_")
    try:
        cmd = ["qlmanage", "-t", "-s", str(max(24, int(size))), "-o", tmp_dir, svg_path]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        generated = os.path.join(tmp_dir, os.path.basename(svg_path) + ".png")
        if os.path.exists(generated):
            shutil.move(generated, out_path)
            return True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return False


def _extract_best_frame(sheet: pygame.Surface) -> pygame.Surface:
    sw, sh = sheet.get_size()
    if sw <= 0 or sh <= 0:
        return sheet
    frame = min(sw, sh)
    if frame <= 0:
        return sheet

    frames: list[pygame.Surface] = []
    if sw >= sh and (sw // frame) >= 2:
        count = max(1, sw // frame)
        for i in range(count):
            frames.append(sheet.subsurface((i * frame, 0, frame, frame)).copy())
    elif sh > sw and (sh // frame) >= 2:
        count = max(1, sh // frame)
        for i in range(count):
            frames.append(sheet.subsurface((0, i * frame, frame, frame)).copy())
    else:
        frames = [sheet.copy()]

    best = frames[0]
    best_score = -1
    for f in frames:
        bbox = f.get_bounding_rect(min_alpha=1)
        score = bbox.width * 10000 + bbox.width * bbox.height
        if score > best_score:
            best = f
            best_score = score
    return best


def _is_bad_icon_surface(img: pygame.Surface) -> bool:
    """Reject bad rasterized SVG previews (solid white square thumbnails)."""
    w, h = img.get_size()
    if w <= 0 or h <= 0:
        return True

    opaque = 0
    sum_r = 0
    sum_g = 0
    sum_b = 0
    min_r = 255
    min_g = 255
    min_b = 255
    max_r = 0
    max_g = 0
    max_b = 0
    total = w * h

    for y in range(h):
        for x in range(w):
            c = img.get_at((x, y))
            if c.a <= 4:
                continue
            opaque += 1
            sum_r += c.r
            sum_g += c.g
            sum_b += c.b
            min_r = min(min_r, c.r)
            min_g = min(min_g, c.g)
            min_b = min(min_b, c.b)
            max_r = max(max_r, c.r)
            max_g = max(max_g, c.g)
            max_b = max(max_b, c.b)

    if opaque <= 0:
        return True
    coverage = opaque / float(total)
    mean_r = sum_r / opaque
    mean_g = sum_g / opaque
    mean_b = sum_b / opaque
    flat = (max_r - min_r) < 2 and (max_g - min_g) < 2 and (max_b - min_b) < 2
    near_white = mean_r > 245 and mean_g > 245 and mean_b > 245
    return coverage > 0.96 and flat and near_white


def load_icon(name: str, size: int) -> pygame.Surface | None:
    key = (str(name), int(size))
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached

    size = max(6, int(size))
    png_candidates = [
        os.path.join(GAME_ICONS, "png", f"{name}.png"),
        os.path.join(GAME_ICONS, f"{name}.png"),
    ]

    source: str | None = None
    for candidate in png_candidates:
        if os.path.exists(candidate):
            source = candidate
            break

    if source is None:
        svg_path = os.path.join(GAME_ICONS, f"{name}.svg")
        converted = os.path.join(GAME_ICONS, "png", f"{name}.png")
        if os.path.exists(svg_path):
            if (not os.path.exists(converted)) and _try_convert_svg(svg_path, converted, size * 3):
                source = converted
            elif os.path.exists(converted):
                source = converted

    if source is None:
        return None

    try:
        img = pygame.image.load(source).convert_alpha()
    except pygame.error:
        return None
    img = _extract_best_frame(img)
    if _is_bad_icon_surface(img):
        return None

    if img.get_width() != size or img.get_height() != size:
        img = pygame.transform.smoothscale(img, (size, size))
    _ICON_CACHE[key] = img
    return img
