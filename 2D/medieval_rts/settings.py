import os

# ── Window ──────────────────────────────────────────────────────────────────
TITLE           = "Medieval Kingdoms RTS"
SCREEN_WIDTH    = 1280
SCREEN_HEIGHT   = 720
FPS             = 60
FULLSCREEN_DEFAULT = False

# ── World / Grid ─────────────────────────────────────────────────────────────
TILE_SIZE  = 64          # pixels per tile (world scale)
MAP_COLS   = 160
MAP_ROWS   = 120

# ── Camera ────────────────────────────────────────────────────────────────────
CAM_SPEED        = 600   # world px / second at zoom=1
CAM_EDGE_SCROLL  = True
CAM_EDGE_MARGIN  = 30    # pixels from edge that triggers scroll
ZOOM_MIN         = 0.25
ZOOM_MAX         = 2.5
ZOOM_DEFAULT     = 1.0
ZOOM_STEP        = 0.12

# ── HUD / UI ──────────────────────────────────────────────────────────────────
HUD_FULL_SHOW_MS = 2200
HUD_IDLE_HIDE_MS = 7000
GRID_ALPHA_MIN   = 16
GRID_ALPHA_MAX   = 52

# ── Environment animation ─────────────────────────────────────────────────────
WATER_ANIM_FPS = 3.5
TREE_ANIM_FPS  = 2.6

# ── World decoration / generation tuning ─────────────────────────────────────
TREE_DENSITY_MOD    = 10
TREE_DENSITY_CUTOFF = 8   # 8/10 = %80 orman tile → ağaç göster
SPAWN_SAFE_RADIUS   = 3

# ── Asset Paths ───────────────────────────────────────────────────────────────
_HERE        = os.path.dirname(os.path.abspath(__file__))

# ── Downloaded In-Game Assets ─────────────────────────────────────────────────
GAME_ASSETS      = os.path.join(_HERE, "assets")
GAME_SOUNDS      = os.path.join(GAME_ASSETS, "sounds")    # .ogg ses efektleri
GAME_MUSIC       = os.path.join(GAME_ASSETS, "music")     # .ogg arka plan müzik
GAME_ICONS       = os.path.join(GAME_ASSETS, "icons")     # SVG + PNG ikonlar
GAME_SPRITES     = os.path.join(GAME_ASSETS, "sprites")   # Flare RPG sprites (CC-BY-SA 3.0)
FLARE_SPRITES    = os.path.join(GAME_SPRITES, "flare")    # alt kategoriler: enemies, npcs, tilesets...
COMPAT_SPRITES   = os.path.join(GAME_SPRITES, "compatible")
VENDOR_2D        = os.path.join(GAME_ASSETS, "vendor2d")


def _resolve_assets_2d_root() -> str:
    # Portable builds (GitHub release / PyInstaller) carry assets inside the project.
    if os.path.isdir(VENDOR_2D):
        return VENDOR_2D
    # Local dev fallback: legacy external /Projeler/2D tree.
    return os.path.join(_HERE, "..")


ASSETS_2D    = _resolve_assets_2d_root()
TINY_SWORDS  = os.path.join(ASSETS_2D, "Tiny Swords (Free Pack)")
MYSTIC_WOODS = os.path.join(ASSETS_2D, "mystic_woods_free_2")
PIXEL_TOPDOWN= os.path.join(ASSETS_2D, "Pixel Art Top Down - Basic v1")
SPROUT_LANDS = os.path.join(ASSETS_2D, "Sprout Lands - Sprites - Basic pack")
TINY_RPG     = os.path.join(ASSETS_2D, "Tiny RPG Character Asset Pack v1.03 -Free Soldier&Orc")

# ── Tile Types ────────────────────────────────────────────────────────────────
TILE_GRASS  = 0
TILE_WATER  = 1
TILE_STONE  = 2
TILE_DIRT   = 3
TILE_FOREST = 4

TILE_COLORS = {
    TILE_GRASS:  (76, 140, 60),
    TILE_WATER:  (35, 100, 180),
    TILE_STONE:  (120, 120, 128),
    TILE_DIRT:   (155, 115, 65),
    TILE_FOREST: (28, 78, 28),
}

TILE_WALKABLE = {
    TILE_GRASS:  True,
    TILE_WATER:  False,
    TILE_STONE:  True,
    TILE_DIRT:   True,
    TILE_FOREST: True,
}

# ── Colors ────────────────────────────────────────────────────────────────────
WHITE  = (255, 255, 255)
BLACK  = (0,   0,   0)
RED    = (220, 50,  50)
GREEN  = (50,  220, 50)
YELLOW = (255, 220, 0)
