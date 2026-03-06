import os
from typing import TYPE_CHECKING

import pygame
from settings import FLARE_SPRITES, MYSTIC_WOODS, TINY_RPG, TINY_SWORDS, TILE_SIZE, WHITE, GREEN, RED, YELLOW

if TYPE_CHECKING:
    from src.engine.pathfinder import Pathfinder
    from src.entities.building import Building
    from src.systems.resources import ResourceNode


# ── Animation helper ──────────────────────────────────────────────────────────

class Animation:
    """Horizontal sprite-sheet strip, square frames (w // h = frame_count)."""

    def __init__(self, sheet: pygame.Surface, fps: float = 8, display_size: int = 96):
        w, h = sheet.get_size()
        frame_count = max(1, w // h) if h > 0 else 1
        frame_w = w // frame_count

        self.fps = fps
        self._t = 0.0
        self.index = 0
        self.frames: list[pygame.Surface] = []

        for i in range(frame_count):
            raw = sheet.subsurface((i * frame_w, 0, frame_w, h))
            if display_size != frame_w or display_size != h:
                raw = pygame.transform.scale(raw, (display_size, display_size))
            self.frames.append(raw)

        self.display_size = display_size

    def update(self, dt: float) -> None:
        self._t += dt
        period = 1.0 / self.fps
        if self._t >= period:
            self._t -= period
            self.index = (self.index + 1) % len(self.frames)

    def reset(self) -> None:
        self.index = 0
        self._t = 0.0

    @property
    def current(self) -> pygame.Surface:
        return self.frames[self.index]


def _load_animation(path: str, fps: float, display_size: int) -> Animation | None:
    if not os.path.exists(path):
        return None
    sheet = pygame.image.load(path).convert_alpha()
    return Animation(sheet, fps=fps, display_size=display_size)


def _fallback_animation(display_size: int, color=(100, 200, 100)) -> Animation:
    """Circle sprite used when the PNG is missing."""
    surf = pygame.Surface((display_size, display_size), pygame.SRCALPHA)
    pygame.draw.circle(
        surf,
        color,
        (display_size // 2, display_size // 2),
        display_size // 2 - 2,
    )
    pygame.draw.circle(
        surf,
        (255, 255, 255),
        (display_size // 2, display_size // 2),
        display_size // 2 - 2,
        2,
    )
    anim = Animation.__new__(Animation)
    anim.fps = 1
    anim._t = 0.0
    anim.index = 0
    anim.frames = [surf]
    anim.display_size = display_size
    return anim


def _single_frame_animation(frame: pygame.Surface) -> Animation:
    anim = Animation.__new__(Animation)
    anim.fps = 1
    anim._t = 0.0
    anim.index = 0
    anim.frames = [frame]
    anim.display_size = frame.get_width()
    return anim


def _animation_from_frames(frames: list[pygame.Surface], fps: float) -> Animation | None:
    if not frames:
        return None
    anim = Animation.__new__(Animation)
    anim.fps = fps
    anim._t = 0.0
    anim.index = 0
    anim.frames = frames
    anim.display_size = frames[0].get_width()
    return anim


def _load_grid_row_animation(
    path: str,
    *,
    row: int,
    frame_size: int,
    frame_count: int,
    fps: float,
    display_size: int,
) -> Animation | None:
    if not os.path.exists(path):
        return None
    sheet = pygame.image.load(path).convert_alpha()
    sw, sh = sheet.get_size()
    if frame_size <= 0:
        return None
    sy = row * frame_size
    if sy + frame_size > sh:
        return None
    max_cols = sw // frame_size
    frame_count = max(1, min(frame_count, max_cols))
    frames: list[pygame.Surface] = []
    for i in range(frame_count):
        sx = i * frame_size
        raw = sheet.subsurface((sx, sy, frame_size, frame_size)).copy()
        if display_size != frame_size:
            raw = pygame.transform.scale(raw, (display_size, display_size))
        frames.append(raw)
    return _animation_from_frames(frames, fps=fps)


def _load_flare_sheet_animation(
    path: str,
    *,
    fps: float,
    display_size: int,
    max_frames: int = 12,
) -> Animation | None:
    if not os.path.exists(path):
        return None
    sheet = pygame.image.load(path).convert_alpha()
    sw, sh = sheet.get_size()
    if sw <= 0 or sh <= 0:
        return None

    raw_frames: list[pygame.Surface] = []
    if sw >= sh and sw // max(1, sh) >= 2:
        frame = sh
        count = max(1, sw // frame)
        for i in range(count):
            raw_frames.append(sheet.subsurface((i * frame, 0, frame, frame)).copy())
    elif sh > sw and sh // max(1, sw) >= 2:
        frame = sw
        count = max(1, sh // frame)
        for i in range(count):
            raw_frames.append(sheet.subsurface((0, i * frame, frame, frame)).copy())
    else:
        size = min(sw, sh)
        raw_frames.append(sheet.subsurface((0, 0, size, size)).copy())

    raw_frames = [f for f in raw_frames if f.get_bounding_rect(min_alpha=1).width > 0]
    if not raw_frames:
        return None
    if len(raw_frames) > max_frames:
        step = len(raw_frames) / max_frames
        sampled: list[pygame.Surface] = []
        for i in range(max_frames):
            sampled.append(raw_frames[int(i * step)])
        raw_frames = sampled

    frames: list[pygame.Surface] = []
    for frame in raw_frames:
        if frame.get_width() != display_size:
            frame = pygame.transform.scale(frame, (display_size, display_size))
        frames.append(frame)
    return _animation_from_frames(frames, fps=fps)


# ── Unit ──────────────────────────────────────────────────────────────────────

class Unit:
    SPEED = 200
    DISPLAY_SIZE = 96
    GATHER_RANGE = TILE_SIZE * 1.08
    _SCALED_FRAME_CACHE: dict[tuple[int, int], pygame.Surface] = {}
    _SCALED_FRAME_CACHE_MAX = 1800
    _HP_SKIN_READY = False
    _HP_BAR_BG: pygame.Surface | None = None
    _HP_BAR_FILL: pygame.Surface | None = None
    _HP_BAR_CACHE: dict[tuple[str, int, int], pygame.Surface] = {}
    PLAYER_CIVILIZATION = "Blue"

    # ── Deterministic UID counter (reset to 0 at Game start) ─────────────────
    _uid_seq: int = 0

    HUNGER_MAX_S = 95.0
    HUNGER_STARVE_SPEED_MULT = 0.68
    HUNGER_FEED_SECONDS = 36.0

    DEATH_DURATION_S = 1.8

    ROLE_WORKER = "worker"
    ROLE_WARRIOR = "warrior"
    ROLE_ARCHER = "archer"
    ROLE_LANCER = "lancer"
    ROLE_MONK = "monk"
    ROLE_HERO = "hero"
    STANCE_AGGRESSIVE = "aggressive"
    STANCE_DEFENSIVE = "defensive"
    STANCE_HOLD = "hold"

    CIV_COLORS = {
        "Blue": (60, 120, 220),
        "Red": (220, 60, 60),
        "Yellow": (220, 200, 30),
        "Black": (50, 50, 50),
        "Purple": (160, 60, 220),
        "OrcRed": (220, 70, 70),
        "OrcYellow": (226, 206, 84),
        "SlimeBlue": (92, 158, 220),
        "SlimePink": (220, 124, 190),
    }

    def __init__(
        self,
        wx: float,
        wy: float,
        civilization: str = "Blue",
        kingdom_id: str | None = None,
        unit_class: str = ROLE_WORKER,
    ):
        # Assign a deterministic integer UID (same on host & guest if same seed).
        Unit._uid_seq += 1
        self.uid: int = Unit._uid_seq

        self.world_pos = pygame.math.Vector2(wx, wy)
        self.target_pos: pygame.math.Vector2 | None = None
        self.civilization = civilization
        self.asset_color = civilization
        self.kingdom_id = kingdom_id or civilization
        self.unit_class = self._normalize_unit_class(unit_class)

        self.can_gather = self.unit_class == self.ROLE_WORKER
        self.can_construct = self.unit_class in (self.ROLE_WORKER, self.ROLE_MONK)
        self.base_speed = self._speed_for_class(self.unit_class)
        self.move_speed = self.base_speed

        combat = self._combat_profile(self.unit_class)
        self.max_hp = int(combat["max_hp"])
        self.hp = float(self.max_hp)
        self.attack = float(combat["attack"])
        self.attack_range = float(combat["attack_range"])
        self.attack_cooldown = float(combat["attack_cooldown"])
        # Chaos mobs are pressure units; keep them dangerous but not overpowering kingdoms.
        if self.asset_color.startswith("Orc"):
            self.max_hp = max(40, int(self.max_hp * 0.80))
            self.hp = float(self.max_hp)
            self.attack *= 0.72
            self.attack_cooldown *= 1.22
        elif self.asset_color.startswith("Slime"):
            self.max_hp = max(36, int(self.max_hp * 0.74))
            self.hp = float(self.max_hp)
            self.attack *= 0.66
            self.attack_cooldown *= 1.28
        self.can_attack = self.attack > 0 and self.attack_range > 0
        self.base_max_hp = float(self.max_hp)
        self.base_attack = float(self.attack)
        self.stance = self.STANCE_AGGRESSIVE

        self.hunger_enabled = self.unit_class in (
            self.ROLE_HERO,
            self.ROLE_WARRIOR,
            self.ROLE_ARCHER,
            self.ROLE_LANCER,
        )
        if self.asset_color.startswith("Orc") or self.asset_color.startswith("Slime"):
            self.hunger_enabled = False
        self.hunger_s = float(self.HUNGER_MAX_S)
        self.starving = False

        self.selected = False
        self._moving = False

        self.gather_target: ResourceNode | None = None
        self._gathering = False
        self._gather_cycle_s = 1.0
        self._gather_timer_s = 0.0
        self.build_target: Building | None = None
        self._building = False
        self._build_cycle_s = 0.72
        self._build_timer_s = 0.0

        self.attack_target: Unit | None = None
        self._attack_cooldown_s = 0.0
        self._attack_repath_timer_s = 0.0
        self._attack_path_fail_count = 0

        self.is_dead = False
        self._death_timer_s = 0.0

        self._path: list[pygame.math.Vector2] = []
        self._path_index = 0
        self._pathfinder: Pathfinder | None = None
        self._blocked_tiles: set[tuple[int, int]] | None = None

        self._anims: dict[str, Animation] = {}
        self._state = "idle"
        self._load_anims()
        self._apply_hunger_speed()

        self.radius = self.DISPLAY_SIZE // 3

    @classmethod
    def _normalize_unit_class(cls, unit_class: str) -> str:
        if unit_class in (
            cls.ROLE_WORKER,
            cls.ROLE_WARRIOR,
            cls.ROLE_ARCHER,
            cls.ROLE_LANCER,
            cls.ROLE_MONK,
            cls.ROLE_HERO,
        ):
            return unit_class
        return cls.ROLE_WORKER

    @classmethod
    def _speed_for_class(cls, unit_class: str) -> float:
        if unit_class == cls.ROLE_LANCER:
            return 240.0
        if unit_class == cls.ROLE_ARCHER:
            return 210.0
        if unit_class == cls.ROLE_MONK:
            return 188.0
        if unit_class in (cls.ROLE_WARRIOR, cls.ROLE_HERO):
            return 195.0
        return float(cls.SPEED)

    @classmethod
    def _combat_profile(cls, unit_class: str) -> dict[str, float | int]:
        if unit_class == cls.ROLE_HERO:
            return {"max_hp": 220, "attack": 26, "attack_range": TILE_SIZE * 0.95, "attack_cooldown": 0.88}
        if unit_class == cls.ROLE_WARRIOR:
            return {"max_hp": 160, "attack": 20, "attack_range": TILE_SIZE * 0.92, "attack_cooldown": 1.02}
        if unit_class == cls.ROLE_ARCHER:
            return {"max_hp": 104, "attack": 17, "attack_range": TILE_SIZE * 3.8, "attack_cooldown": 1.24}
        if unit_class == cls.ROLE_LANCER:
            return {"max_hp": 132, "attack": 24, "attack_range": TILE_SIZE * 1.28, "attack_cooldown": 1.08}
        if unit_class == cls.ROLE_MONK:
            return {"max_hp": 96, "attack": 7, "attack_range": TILE_SIZE * 1.0, "attack_cooldown": 1.46}
        if unit_class == cls.ROLE_WORKER:
            return {"max_hp": 84, "attack": 6, "attack_range": TILE_SIZE * 0.85, "attack_cooldown": 1.25}
        return {"max_hp": 100, "attack": 8, "attack_range": TILE_SIZE * 0.9, "attack_cooldown": 1.2}

    @property
    def hunger_ratio(self) -> float:
        if not self.hunger_enabled:
            return 1.0
        return max(0.0, min(1.0, self.hunger_s / max(0.001, self.HUNGER_MAX_S)))

    @property
    def needs_food(self) -> bool:
        return self.hunger_enabled and self.hunger_ratio <= 0.35

    @property
    def hp_ratio(self) -> float:
        return max(0.0, min(1.0, self.hp / max(1.0, float(self.max_hp))))

    @property
    def death_finished(self) -> bool:
        return self.is_dead and self._death_timer_s >= self.DEATH_DURATION_S

    def _apply_hunger_speed(self) -> None:
        if self.starving:
            self.move_speed = self.base_speed * self.HUNGER_STARVE_SPEED_MULT
        else:
            self.move_speed = self.base_speed

    def tick_hunger(self, dt: float) -> None:
        if not self.hunger_enabled or self.is_dead:
            return
        self.hunger_s = max(0.0, self.hunger_s - dt)
        was_starving = self.starving
        self.starving = self.hunger_s <= 0.0
        if self.starving != was_starving:
            self._apply_hunger_speed()

    def feed(self, seconds: float | None = None) -> bool:
        if not self.hunger_enabled or self.is_dead:
            return False
        prev = self.hunger_s
        self.hunger_s = min(self.HUNGER_MAX_S, self.hunger_s + float(seconds or self.HUNGER_FEED_SECONDS))
        was_starving = self.starving
        self.starving = self.hunger_s <= 0.0
        if self.starving != was_starving:
            self._apply_hunger_speed()
        return self.hunger_s > prev

    def is_hostile_to(self, other: "Unit") -> bool:
        return self.kingdom_id != getattr(other, "kingdom_id", getattr(other, "civilization", self.kingdom_id))

    # ── Asset loading ──────────────────────────────────────────────────────────
    def _load_anims(self) -> None:
        ds = self.DISPLAY_SIZE
        if self.asset_color.startswith("Orc"):
            self._load_orc_anims(ds)
            self._ensure_dead_anim()
            return
        if self.asset_color.startswith("Slime"):
            self._load_slime_anims(ds)
            self._ensure_dead_anim()
            return

        civ_base = os.path.join(TINY_SWORDS, "Units", f"{self.asset_color} Units")

        if self.unit_class in (self.ROLE_HERO, self.ROLE_WARRIOR):
            base = os.path.join(civ_base, "Warrior")
            idle = _load_animation(os.path.join(base, "Warrior_Idle.png"), fps=6, display_size=ds)
            run = _load_animation(os.path.join(base, "Warrior_Run.png"), fps=8, display_size=ds)
            guard = _load_animation(os.path.join(base, "Warrior_Guard.png"), fps=6, display_size=ds)
            attack = _load_animation(os.path.join(base, "Warrior_Attack1.png"), fps=10, display_size=ds)
            if idle is None:
                idle = _fallback_animation(ds, self.CIV_COLORS.get(self.civilization, (128, 128, 128)))
            run = run or idle
            guard = guard or idle
            attack = attack or guard
            self._anims = {
                "idle": idle,
                "run": run,
                "attack": attack,
                "build": guard,
                "gather_gold": guard,
                "gather_stone": guard,
                "gather_wood": guard,
                "gather_food": guard,
                "gather_meat": guard,
            }
        elif self.unit_class == self.ROLE_ARCHER:
            base = os.path.join(civ_base, "Archer")
            idle = _load_animation(os.path.join(base, "Archer_Idle.png"), fps=6, display_size=ds)
            run = _load_animation(os.path.join(base, "Archer_Run.png"), fps=8, display_size=ds)
            shoot = _load_animation(os.path.join(base, "Archer_Shoot.png"), fps=9, display_size=ds)
            if idle is None:
                idle = _fallback_animation(ds, self.CIV_COLORS.get(self.civilization, (128, 128, 128)))
            run = run or idle
            shoot = shoot or idle
            self._anims = {
                "idle": idle,
                "run": run,
                "attack": shoot,
                "build": idle,
                "gather_gold": idle,
                "gather_stone": idle,
                "gather_wood": idle,
                "gather_food": idle,
                "gather_meat": idle,
            }
        elif self.unit_class == self.ROLE_LANCER:
            base = os.path.join(civ_base, "Lancer")
            idle = _load_animation(os.path.join(base, "Lancer_Idle.png"), fps=6, display_size=ds)
            run = _load_animation(os.path.join(base, "Lancer_Run.png"), fps=8, display_size=ds)
            attack = None
            for attack_name in (
                "Lancer_Right_Attack.png",
                "Lancer_DownRight_Attack.png",
                "Lancer_UpRight_Attack.png",
                "Lancer_Up_Attack.png",
                "Lancer_Down_Attack.png",
            ):
                attack = _load_animation(os.path.join(base, attack_name), fps=9, display_size=ds)
                if attack is not None:
                    break
            if idle is None:
                idle = _fallback_animation(ds, self.CIV_COLORS.get(self.civilization, (128, 128, 128)))
            run = run or idle
            attack = attack or idle
            self._anims = {
                "idle": idle,
                "run": run,
                "attack": attack,
                "build": idle,
                "gather_gold": idle,
                "gather_stone": idle,
                "gather_wood": idle,
                "gather_food": idle,
                "gather_meat": idle,
            }
        elif self.unit_class == self.ROLE_MONK:
            base = os.path.join(civ_base, "Monk")
            idle = _load_animation(os.path.join(base, "Idle.png"), fps=6, display_size=ds)
            run = _load_animation(os.path.join(base, "Run.png"), fps=8, display_size=ds)
            attack = _load_animation(os.path.join(base, "Heal.png"), fps=8, display_size=ds)
            if idle is None:
                idle = _fallback_animation(ds, self.CIV_COLORS.get(self.civilization, (128, 128, 128)))
            run = run or idle
            attack = attack or idle
            self._anims = {
                "idle": idle,
                "run": run,
                "attack": attack,
                "build": idle,
                "gather_gold": idle,
                "gather_stone": idle,
                "gather_wood": idle,
                "gather_food": idle,
                "gather_meat": idle,
            }
        else:
            base = os.path.join(civ_base, "Pawn")
            idle = _load_animation(os.path.join(base, "Pawn_Idle.png"), fps=6, display_size=ds)
            run = _load_animation(os.path.join(base, "Pawn_Run.png"), fps=8, display_size=ds)
            gather_pickaxe = _load_animation(os.path.join(base, "Pawn_Interact Pickaxe.png"), fps=8, display_size=ds)
            gather_axe = _load_animation(os.path.join(base, "Pawn_Interact Axe.png"), fps=8, display_size=ds)
            gather_knife = _load_animation(os.path.join(base, "Pawn_Interact Knife.png"), fps=8, display_size=ds)
            gather_hammer = _load_animation(os.path.join(base, "Pawn_Interact Hammer.png"), fps=8, display_size=ds)
            if idle is None:
                idle = _fallback_animation(ds, self.CIV_COLORS.get(self.civilization, (128, 128, 128)))
            run = run or idle
            gather_pickaxe = gather_pickaxe or idle
            gather_axe = gather_axe or gather_pickaxe
            gather_knife = gather_knife or gather_axe
            gather_hammer = gather_hammer or gather_pickaxe
            self._anims = {
                "idle": idle,
                "run": run,
                "attack": gather_knife,
                "build": gather_hammer,
                "gather_gold": gather_pickaxe,
                "gather_stone": gather_pickaxe,
                "gather_wood": gather_axe,
                "gather_food": gather_axe,
                "gather_meat": gather_knife,
            }

        self._ensure_dead_anim()

    def _load_orc_anims(self, ds: int) -> None:
        base = os.path.join(
            TINY_RPG,
            "Characters(100x100)",
            "Orc",
            "Orc with shadows",
        )
        idle = _load_animation(os.path.join(base, "Orc-Idle.png"), fps=6, display_size=ds)
        run = _load_animation(os.path.join(base, "Orc-Walk.png"), fps=8, display_size=ds)
        attack = _load_animation(os.path.join(base, "Orc-Attack01.png"), fps=9, display_size=ds)
        if idle is None:
            idle = _fallback_animation(ds, self.CIV_COLORS.get(self.civilization, (122, 188, 112)))
        run = run or idle
        attack = attack or run
        self._anims = {
            "idle": idle,
            "run": run,
            "attack": attack,
            "build": idle,
            "gather_gold": idle,
            "gather_stone": idle,
            "gather_wood": idle,
            "gather_food": idle,
            "gather_meat": idle,
        }

    def _load_slime_anims(self, ds: int) -> None:
        path = os.path.join(MYSTIC_WOODS, "sprites", "characters", "slime.png")
        idle = _load_grid_row_animation(
            path,
            row=0,
            frame_size=32,
            frame_count=7,
            fps=6,
            display_size=ds,
        )
        run = _load_grid_row_animation(
            path,
            row=4,
            frame_size=32,
            frame_count=7,
            fps=8,
            display_size=ds,
        )
        attack = _load_grid_row_animation(
            path,
            row=7,
            frame_size=32,
            frame_count=7,
            fps=9,
            display_size=ds,
        )
        if idle is None:
            idle = _fallback_animation(ds, self.CIV_COLORS.get(self.civilization, (128, 188, 210)))
        run = run or idle
        attack = attack or run
        self._anims = {
            "idle": idle,
            "run": run,
            "attack": attack,
            "build": idle,
            "gather_gold": idle,
            "gather_stone": idle,
            "gather_wood": idle,
            "gather_food": idle,
            "gather_meat": idle,
        }

    def _ensure_dead_anim(self) -> None:
        dead_paths = [
            os.path.join(TINY_SWORDS, "Units", f"{self.asset_color} Units", "Tiny_Dead.png"),
            os.path.join(TINY_SWORDS, "Units", "Tiny_Dead.png"),
        ]
        if self.asset_color.startswith("Orc"):
            dead_paths.insert(
                0,
                os.path.join(
                    TINY_RPG,
                    "Characters(100x100)",
                    "Orc",
                    "Orc with shadows",
                    "Orc-Death.png",
                ),
            )
        dead_anim = None
        for path in dead_paths:
            dead_anim = _load_animation(path, fps=1, display_size=self.DISPLAY_SIZE)
            if dead_anim is not None:
                break

        if dead_anim is None:
            idle_frame = self._anims.get("idle", _fallback_animation(self.DISPLAY_SIZE)).current.copy()
            shadow = pygame.Surface(idle_frame.get_size(), pygame.SRCALPHA)
            shadow.fill((22, 18, 20, 145))
            idle_frame.blit(shadow, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            dead_anim = _single_frame_animation(idle_frame)

        self._anims["dead"] = dead_anim

    @classmethod
    def _ensure_hp_skin(cls) -> None:
        if cls._HP_SKIN_READY:
            return
        cls._HP_SKIN_READY = True
        bg_path = os.path.join(FLARE_SPRITES, "menus", "bar_hp_background.png")
        fill_path = os.path.join(FLARE_SPRITES, "menus", "bar_hp.png")
        try:
            if os.path.exists(bg_path):
                cls._HP_BAR_BG = pygame.image.load(bg_path).convert_alpha()
            if os.path.exists(fill_path):
                cls._HP_BAR_FILL = pygame.image.load(fill_path).convert_alpha()
        except pygame.error:
            cls._HP_BAR_BG = None
            cls._HP_BAR_FILL = None

    @classmethod
    def _scaled_hp_surface(cls, kind: str, surface: pygame.Surface | None, w: int, h: int) -> pygame.Surface | None:
        if surface is None:
            return None
        w = max(1, int(w))
        h = max(1, int(h))
        key = (kind, w, h)
        cached = cls._HP_BAR_CACHE.get(key)
        if cached is not None:
            return cached
        scaled = pygame.transform.smoothscale(surface, (w, h))
        cls._HP_BAR_CACHE[key] = scaled
        return scaled

    # ── Commands ───────────────────────────────────────────────────────────────
    def move_to(
        self,
        wx: float,
        wy: float,
        *,
        pathfinder: "Pathfinder" | None = None,
        blocked_tiles: set[tuple[int, int]] | None = None,
    ) -> None:
        if self.is_dead:
            return
        self.stop_gathering()
        self.stop_constructing()
        self.stop_attack()
        self._pathfinder = pathfinder
        self._blocked_tiles = blocked_tiles
        self._set_move_target(wx, wy)

    def gather(
        self,
        resource_node: "ResourceNode",
        approach_pos: tuple[float, float] | None = None,
        *,
        pathfinder: "Pathfinder" | None = None,
        blocked_tiles: set[tuple[int, int]] | None = None,
    ) -> bool:
        if self.is_dead or not self.can_gather:
            return False
        self.stop_constructing()
        self.stop_attack()
        self.gather_target = resource_node
        self._gathering = False
        self._gather_cycle_s = max(0.2, float(resource_node.gather_duration))
        self._gather_timer_s = self._gather_cycle_s
        self._pathfinder = pathfinder
        self._blocked_tiles = blocked_tiles
        tx, ty = approach_pos if approach_pos is not None else (resource_node.wx, resource_node.wy)
        self._set_move_target(tx, ty)
        return True

    def construct(
        self,
        building: "Building",
        approach_pos: tuple[float, float] | None = None,
        *,
        pathfinder: "Pathfinder" | None = None,
        blocked_tiles: set[tuple[int, int]] | None = None,
    ) -> bool:
        if self.is_dead or not self.can_construct:
            return False
        self.stop_gathering()
        self.stop_attack()
        self.build_target = building
        self._building = False
        self._build_timer_s = self._build_cycle_s
        self._pathfinder = pathfinder
        self._blocked_tiles = blocked_tiles
        tx, ty = approach_pos if approach_pos is not None else (building.world_pos.x, building.world_pos.y)
        self._set_move_target(tx, ty)
        return True

    def attack_command(
        self,
        target_unit,
        *,
        pathfinder: "Pathfinder" | None = None,
        blocked_tiles: set[tuple[int, int]] | None = None,
    ) -> bool:
        if self.is_dead or not self.can_attack:
            return False
        if target_unit is self:
            return False
        if getattr(target_unit, "is_dead", False):
            return False
        target_kingdom = getattr(target_unit, "kingdom_id", getattr(target_unit, "civilization", self.kingdom_id))
        if target_kingdom == self.kingdom_id:
            return False

        self.stop_gathering()
        self.stop_constructing()
        self.attack_target = target_unit
        self._pathfinder = pathfinder
        self._blocked_tiles = blocked_tiles
        self._attack_repath_timer_s = 0.0
        self._attack_path_fail_count = 0
        return True

    def stop_gathering(self) -> None:
        self.gather_target = None
        self._gathering = False
        self._gather_timer_s = 0.0
        self._gather_cycle_s = 1.0

    def stop_constructing(self) -> None:
        self.build_target = None
        self._building = False
        self._build_timer_s = 0.0

    def stop_attack(self) -> None:
        self.attack_target = None
        self._attack_repath_timer_s = 0.0
        self._attack_path_fail_count = 0
        if not self._moving:
            self._set_state("idle")

    def set_stance(self, stance: str) -> None:
        if stance not in (self.STANCE_AGGRESSIVE, self.STANCE_DEFENSIVE, self.STANCE_HOLD):
            return
        self.stance = stance
        if stance == self.STANCE_HOLD and self.attack_target is not None and not self._moving:
            self.target_pos = None

    def apply_combat_scale(self, scale: float) -> None:
        s = max(0.4, float(scale))
        hp_ratio = self.hp / max(1.0, float(self.max_hp))
        self.max_hp = max(1, int(round(self.base_max_hp * s)))
        self.attack = max(0.0, self.base_attack * s)
        self.hp = max(1.0, min(float(self.max_hp), float(self.max_hp) * hp_ratio))

    def _set_move_target(
        self,
        wx: float,
        wy: float,
        *,
        precise_world: bool = False,
        max_path_expansions: int | None = None,
    ) -> bool:
        if self.is_dead:
            return False
        self._path.clear()
        self._path_index = 0

        if self._pathfinder is not None:
            # Fast path for short, obstacle-free steering to avoid costly A* churn.
            dx = wx - self.world_pos.x
            dy = wy - self.world_pos.y
            if (dx * dx + dy * dy) <= (TILE_SIZE * 18.0) ** 2 and self._can_direct_move(wx, wy):
                self.target_pos = pygame.math.Vector2(wx, wy)
                self._moving = True
                self._set_state("run")
                return True

            points = self._pathfinder.find_path_world(
                (self.world_pos.x, self.world_pos.y),
                (wx, wy),
                blocked=self._blocked_tiles,
                max_expansions=max_path_expansions,
            )
            if points:
                self._path = [pygame.math.Vector2(px, py) for px, py in points]
                if precise_world:
                    exact_goal = pygame.math.Vector2(wx, wy)
                    if (exact_goal - self._path[-1]).length_squared() > 9.0:
                        self._path.append(exact_goal)
                self.target_pos = pygame.math.Vector2(self._path[0])
                self._path_index = 0
            else:
                # If pathfinder cannot produce a route, do not fall back to direct movement
                # (direct steering can cut through blocked/water tiles).
                self.target_pos = None
                self._moving = False
                if self.attack_target is None and not self._gathering and not self._building:
                    self._set_state("idle")
                return False
        else:
            self.target_pos = pygame.math.Vector2(wx, wy)

        self._moving = True
        self._set_state("run")
        return True

    def _can_direct_move(self, wx: float, wy: float) -> bool:
        if self._pathfinder is None:
            return True
        tilemap = self._pathfinder.tilemap
        blocked = self._blocked_tiles

        sx, sy = self.world_pos.x, self.world_pos.y
        dx = wx - sx
        dy = wy - sy
        dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
        steps = max(2, int(dist / (TILE_SIZE * 0.42)))
        inv_steps = 1.0 / steps

        for i in range(steps + 1):
            t = i * inv_steps
            tx = sx + dx * t
            ty = sy + dy * t
            tc, tr = tilemap.world_to_tile(tx, ty)
            if blocked is not None and (tc, tr) in blocked:
                return False
            if not tilemap.is_walkable(tc, tr):
                return False
        return True

    def _advance_path_or_stop(self) -> None:
        if self._path and self._path_index + 1 < len(self._path):
            self._path_index += 1
            self.target_pos = pygame.math.Vector2(self._path[self._path_index])
            self._moving = True
            return
        self._path.clear()
        self._path_index = 0
        self.target_pos = None
        self._moving = False
        if self.attack_target is None and not self._gathering and not self._building:
            self._set_state("idle")

    # ── Combat ─────────────────────────────────────────────────────────────────
    def take_damage(self, amount: float) -> bool:
        if self.is_dead:
            return False
        self.hp = max(0.0, self.hp - max(0.0, amount))
        if self.hp <= 0.0:
            self._die()
            return True
        return False

    def _die(self) -> None:
        self.is_dead = True
        self.hp = 0.0
        self.selected = False
        self.stop_gathering()
        self.stop_constructing()
        self.stop_attack()
        self._moving = False
        self.target_pos = None
        self._path.clear()
        self._path_index = 0
        self._death_timer_s = 0.0
        self._set_state("dead")

    def _update_attack(self, dt: float) -> None:
        target = self.attack_target
        if target is None:
            return
        if target.is_dead:
            self.stop_attack()
            return

        target_vec = target.world_pos - self.world_pos
        range_limit = max(8.0, self.attack_range)
        dist2 = target_vec.length_squared()
        hard_chase_range = range_limit * 1.28
        hit_range = range_limit * 1.05

        if self.stance == self.STANCE_HOLD and dist2 > hit_range * hit_range:
            self._moving = False
            self.target_pos = None
            self._path.clear()
            self._path_index = 0
            self._set_state("idle")
            return

        if self.stance == self.STANCE_DEFENSIVE:
            leash = max(TILE_SIZE * 2.2, range_limit * 2.5)
            if dist2 > leash * leash:
                self.stop_attack()
                return

        if dist2 > hard_chase_range * hard_chase_range:
            self._attack_repath_timer_s -= dt
            if self._attack_repath_timer_s <= 0.0:
                dist = max(0.001, dist2 ** 0.5)
                approach_dist = max(8.0, range_limit * 0.78)
                ax = target.world_pos.x - (target_vec.x / dist) * approach_dist
                ay = target.world_pos.y - (target_vec.y / dist) * approach_dist
                should_repath = (
                    not self._moving
                    or self.target_pos is None
                    or (self.target_pos - pygame.math.Vector2(ax, ay)).length_squared() > (TILE_SIZE * 0.72) ** 2
                )
                if should_repath:
                    moved = self._set_move_target(
                        ax,
                        ay,
                        precise_world=True,
                        max_path_expansions=1350,
                    )
                    if moved:
                        self._attack_path_fail_count = 0
                        self._attack_repath_timer_s = 0.74 if self.attack_range <= TILE_SIZE * 1.5 else 0.62
                    else:
                        self._attack_path_fail_count += 1
                        self._attack_repath_timer_s = 1.15
                        if self._attack_path_fail_count >= 4:
                            self.stop_attack()
                else:
                    self._attack_repath_timer_s = 0.32
            return

        if dist2 > hit_range * hit_range:
            # Keep closing in when inside soft chase range but still outside hit range.
            self._attack_repath_timer_s -= dt
            if self._attack_repath_timer_s <= 0.0:
                dist = max(0.001, dist2 ** 0.5)
                approach_dist = max(6.0, range_limit * 0.92)
                ax = target.world_pos.x - (target_vec.x / dist) * approach_dist
                ay = target.world_pos.y - (target_vec.y / dist) * approach_dist
                should_repath = (
                    not self._moving
                    or self.target_pos is None
                    or (self.target_pos - pygame.math.Vector2(ax, ay)).length_squared() > (TILE_SIZE * 0.56) ** 2
                )
                if should_repath:
                    moved = self._set_move_target(
                        ax,
                        ay,
                        precise_world=True,
                        max_path_expansions=1200,
                    )
                    if moved:
                        self._attack_path_fail_count = 0
                        self._attack_repath_timer_s = 0.44
                    else:
                        self._attack_path_fail_count += 1
                        self._attack_repath_timer_s = 0.95
                        if self._attack_path_fail_count >= 4:
                            self.stop_attack()
                else:
                    self._attack_repath_timer_s = 0.22
            self._set_state("run")
            return

        # In hit range: hold position and strike.
        self._moving = False
        self.target_pos = None
        self._path.clear()
        self._path_index = 0
        self._attack_path_fail_count = 0
        self._set_state("attack" if "attack" in self._anims else "idle")
        if self._attack_cooldown_s <= 0.0:
            self._attack_cooldown_s = max(0.18, self.attack_cooldown)
            target.take_damage(self.attack)
            self._set_state("attack" if "attack" in self._anims else "idle")
            if target.is_dead:
                self.stop_attack()

    # ── Update ─────────────────────────────────────────────────────────────────
    def update(self, dt: float) -> dict[str, object] | None:
        if self.is_dead:
            self._death_timer_s += dt
            self._anims[self._state].update(dt)
            return None

        event: dict[str, object] | None = None
        self._attack_cooldown_s = max(0.0, self._attack_cooldown_s - dt)

        if self.target_pos and self._moving:
            direction = self.target_pos - self.world_pos
            dist = direction.length()
            step = self.move_speed * dt

            if dist <= step:
                self.world_pos = pygame.math.Vector2(self.target_pos)
                self._advance_path_or_stop()
            else:
                direction.scale_to_length(step)
                self.world_pos += direction

        if self.attack_target is not None:
            self._update_attack(dt)
            self._anims[self._state].update(dt)
            return None

        if self.build_target is not None and not self._moving:
            site = self.build_target
            if site.is_complete:
                self.stop_constructing()
                self._set_state("idle")
            else:
                site_vec = pygame.math.Vector2(site.world_pos.x, site.world_pos.y)
                build_range = max(self.GATHER_RANGE, TILE_SIZE * 1.6)
                if (site_vec - self.world_pos).length_squared() > (build_range ** 2):
                    self._set_move_target(site.world_pos.x, site.world_pos.y)
                    self._building = False
                    self._set_state("run")
                else:
                    if not self._building:
                        self._building = True
                        self._build_timer_s = self._build_cycle_s
                        self._set_state("build")
                    else:
                        self._build_timer_s -= dt
                        if self._build_timer_s <= 0.0:
                            self._build_timer_s += self._build_cycle_s
                            event = {
                                "kind": "build",
                                "building": site,
                                "work_seconds": self._build_cycle_s,
                            }
                            self._set_state("build")
        elif self.build_target is None and self._building:
            self._building = False
            self._set_state("idle")

        if not self.can_gather and self.gather_target is not None:
            self.stop_gathering()

        if self.gather_target is not None and not self._moving:
            node = self.gather_target
            if node.is_depleted:
                self.stop_gathering()
                self._set_state("idle")
            else:
                node_vec = pygame.math.Vector2(node.wx, node.wy)
                if (node_vec - self.world_pos).length_squared() > (self.GATHER_RANGE ** 2):
                    self._set_move_target(node.wx, node.wy)
                    self._gathering = False
                    self._set_state("run")
                else:
                    gather_state = f"gather_{node.resource_type}"
                    if gather_state not in self._anims:
                        gather_state = "idle"
                    if not self._gathering:
                        self._gathering = True
                        self._gather_cycle_s = max(0.2, float(node.gather_duration))
                        self._gather_timer_s = self._gather_cycle_s
                        self._set_state(gather_state)
                    else:
                        self._gather_timer_s -= dt
                        if self._gather_timer_s <= 0.0:
                            self._gather_timer_s += self._gather_cycle_s
                            event = {
                                "kind": "gather",
                                "node": node,
                                "amount": int(node.gather_amount),
                            }
                            self._set_state(gather_state)
        elif self.gather_target is None and self._gathering:
            self._gathering = False
            self._set_state("idle")

        self._anims[self._state].update(dt)
        return event

    # ── Draw ───────────────────────────────────────────────────────────────────
    def draw(self, screen: pygame.Surface, camera) -> None:
        frame = self._anims[self._state].current
        zoom = camera.zoom

        if zoom != 1.0:
            zkey = int(round(zoom * 1000))
            key = (id(frame), zkey)
            cached = self._SCALED_FRAME_CACHE.get(key)
            if cached is None:
                sz = max(1, int(self.DISPLAY_SIZE * zoom))
                cached = pygame.transform.scale(frame, (sz, sz))
                cache = self._SCALED_FRAME_CACHE
                if len(cache) >= self._SCALED_FRAME_CACHE_MAX:
                    cache.clear()
                cache[key] = cached
            frame = cached

        if self.is_dead:
            fade = max(0.0, 1.0 - self._death_timer_s / self.DEATH_DURATION_S)
            frame = frame.copy()
            frame.set_alpha(max(20, int(255 * fade)))

        sx, sy = camera.world_to_screen(self.world_pos)
        sx, sy = int(sx), int(sy)
        fw = frame.get_width()
        fh = frame.get_height()
        screen.blit(frame, (sx - fw // 2, sy - fh // 2))

        if self.is_dead:
            return

        if self.selected:
            ring_w = max(12, int(self.radius * zoom * 2.0))
            ring_h = max(5, int(self.radius * zoom * 0.75))
            ring_x = sx - ring_w // 2
            ring_y = sy + int(fh * 0.36)

            shadow = pygame.Surface((ring_w + 6, ring_h + 6), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (0, 0, 0, 120), shadow.get_rect())
            screen.blit(shadow, (ring_x - 3, ring_y + 1))

            ring_rect = pygame.Rect(ring_x, ring_y, ring_w, ring_h)
            pygame.draw.ellipse(screen, (0, 0, 0), ring_rect, 3)
            pygame.draw.ellipse(screen, WHITE, ring_rect, 2)
            inner = ring_rect.inflate(-4, -2)
            if inner.width > 4 and inner.height > 2:
                ring_color = GREEN if self.can_gather else YELLOW
                pygame.draw.ellipse(screen, ring_color, inner, 2)

        show_health = self.selected or self.kingdom_id != self.PLAYER_CIVILIZATION
        if show_health:
            bar_w = int(44 * zoom)
            bar_h = max(3, int(5 * zoom))
            bx = sx - bar_w // 2
            by = sy - fh // 2 - bar_h - int(4 * zoom)
            self._ensure_hp_skin()
            bar_bg = self._scaled_hp_surface("bg", self._HP_BAR_BG, bar_w, bar_h)
            fill_w = max(1, int(bar_w * self.hp_ratio))
            bar_fill = self._scaled_hp_surface("fill", self._HP_BAR_FILL, fill_w, bar_h)
            if bar_bg is not None and bar_fill is not None:
                screen.blit(bar_bg, (bx, by))
                screen.blit(bar_fill, (bx, by))
                pygame.draw.rect(screen, (0, 0, 0), (bx, by, bar_w, bar_h), 1)
            else:
                pygame.draw.rect(screen, RED, (bx, by, bar_w, bar_h))
                pygame.draw.rect(screen, GREEN, (bx, by, fill_w, bar_h))
                pygame.draw.rect(screen, (0, 0, 0), (bx, by, bar_w, bar_h), 1)

            if self.selected and self.hunger_enabled:
                hy = by + bar_h + max(2, int(2 * zoom))
                ratio = self.hunger_ratio
                hunger_bg = (104, 64, 42)
                hunger_fill = (216, 168, 74) if not self.starving else (168, 68, 52)
                pygame.draw.rect(screen, hunger_bg, (bx, hy, bar_w, bar_h))
                pygame.draw.rect(
                    screen,
                    hunger_fill,
                    (bx, hy, max(1, int(bar_w * ratio)), bar_h),
                )
                pygame.draw.rect(screen, (0, 0, 0), (bx, hy, bar_w, bar_h), 1)

        if self._gathering and self.gather_target is not None:
            t = 1.0 - max(0.0, min(1.0, self._gather_timer_s / max(0.001, self._gather_cycle_s)))
            gw = int(30 * zoom)
            gh = max(3, int(4 * zoom))
            gx = sx - gw // 2
            gy = sy - fh // 2 - gh - int(10 * zoom)
            pygame.draw.rect(screen, (0, 0, 0), (gx, gy, gw, gh))
            pygame.draw.rect(
                screen,
                (230, 208, 86),
                (gx + 1, gy + 1, max(1, int((gw - 2) * t)), max(1, gh - 2)),
            )

    # ── Helpers ────────────────────────────────────────────────────────────────
    def contains_point(self, wx: float, wy: float) -> bool:
        if self.is_dead:
            return False
        dx = wx - self.world_pos.x
        dy = wy - self.world_pos.y
        return dx * dx + dy * dy <= (self.radius * 1.5) ** 2

    def _set_state(self, state: str) -> None:
        if state not in self._anims:
            state = "idle"
        if state != self._state:
            self._state = state
            self._anims[state].reset()
