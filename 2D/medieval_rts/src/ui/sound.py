"""
SoundManager — oyun ses efektleri ve arka plan müziği.

Öncelik sırası:
  1. assets/sounds/ klasöründeki gerçek OGG dosyaları (isim eşleşmesi)
  2. mystic_woods_free_2/ içindeki WAV/OGG dosyaları (anahtar kelime tarama)
  3. SoX ile üretilmiş sentetik beep sesi (yedek)

Arka plan müziği:
  assets/music/ klasörüne OGG koydun mu? Otomatik döngüde çalar.
"""
from __future__ import annotations

import math
import os
from array import array

import pygame

from settings import GAME_MUSIC, GAME_SOUNDS, MYSTIC_WOODS


class SoundManager:
    # ── Sentetik yedek sesler (sıklık, süre, hacim) ───────────────────────────
    _EVENT_TONES: dict[str, tuple[float, float, float]] = {
        "select": (700.0, 0.06, 0.35),
        "move":   (520.0, 0.08, 0.34),
        "attack": (320.0, 0.10, 0.40),
        "build":  (460.0, 0.14, 0.30),
        "death":  (180.0, 0.18, 0.45),
        "alert":  (600.0, 0.12, 0.38),
        "error":  (200.0, 0.10, 0.30),
        "gold":   (880.0, 0.10, 0.28),
        "train":  (540.0, 0.16, 0.32),
    }

    # Tekrar çalma bekleme süreleri (ms)
    _COOLDOWNS_MS: dict[str, int] = {
        "select": 60,
        "move":   120,
        "attack": 80,
        "build":  200,
        "death":  110,
        "alert":  300,
        "error":  400,
        "gold":   250,
        "train":  500,
    }

    def __init__(self, *, music_volume: float = 0.35, sfx_volume: float = 0.70) -> None:
        self.enabled = False
        self._music_volume = max(0.0, min(1.0, music_volume))
        self._sfx_volume   = max(0.0, min(1.0, sfx_volume))
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._last_play_ms: dict[str, int] = {}
        self._sample_rate = 22050
        self._music_playing = False
        self._init_mixer()

    # ── Başlatma ─────────────────────────────────────────────────────────────

    def _init_mixer(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(
                    frequency=self._sample_rate,
                    size=-16,
                    channels=2,
                    buffer=512,
                )
            # Ses efektlerini yükle (önce gerçek dosyalar, sonra sentetik)
            self._load_game_sounds()
            self._load_mystic_woods_sounds()
            for key, (freq, dur, vol) in self._EVENT_TONES.items():
                if key not in self._sounds:
                    self._sounds[key] = self._make_tone(freq, dur, vol * self._sfx_volume)
            # Yüklenen seslerin ses seviyesini ayarla
            for snd in self._sounds.values():
                snd.set_volume(self._sfx_volume)
            self.enabled = True
            # Arka plan müziği başlat
            self._start_music()
        except pygame.error:
            self.enabled = False
            self._sounds.clear()

    # Dosya adı → event adı eşleştirmesi (indirilen freesound dosyaları için)
    _FILE_ALIASES: dict[str, str] = {
        "sword_clash":  "attack",
        "sword_draw":   "attack",
        "hammer":       "build",
        "coin_pickup":  "gold",
        "footstep":     "move",
        "arrow_shoot":  "attack",
        "horn_war":     "alert",
        "fanfare":      "train",
        "ui_click2":    "select",
    }

    def _load_game_sounds(self) -> None:
        """assets/sounds/ klasöründeki OGG/MP3 dosyalarını yükle."""
        if not os.path.isdir(GAME_SOUNDS):
            return
        for fname in sorted(os.listdir(GAME_SOUNDS)):
            if not fname.lower().endswith((".ogg", ".wav", ".mp3")):
                continue
            base = os.path.splitext(fname)[0].lower()
            # Önce tam isim eşleşmesi (attack.ogg → "attack")
            key = base if base in self._EVENT_TONES else self._FILE_ALIASES.get(base)
            if key is None:
                continue
            if key in self._sounds:
                continue  # zaten yüklendi (ilk bulunan kazanır)
            try:
                snd = pygame.mixer.Sound(os.path.join(GAME_SOUNDS, fname))
                snd.set_volume(self._sfx_volume)
                self._sounds[key] = snd
            except pygame.error:
                pass

    def _load_mystic_woods_sounds(self) -> None:
        """mystic_woods_free_2/ içindeki sesleri anahtar kelimeyle eşleştir."""
        if not os.path.isdir(MYSTIC_WOODS):
            return
        keywords: dict[str, tuple[str, ...]] = {
            "select": ("select", "click", "ui"),
            "move":   ("move", "step", "walk", "footstep"),
            "attack": ("attack", "hit", "slash", "swing", "sword"),
            "build":  ("build", "hammer", "craft", "construct"),
            "death":  ("death", "die", "fall", "scream"),
            "alert":  ("alert", "alarm", "warn"),
        }
        for root, _, files in os.walk(MYSTIC_WOODS):
            for name in files:
                lower = name.lower()
                if not lower.endswith((".wav", ".ogg", ".mp3")):
                    continue
                full = os.path.join(root, name)
                for event_name, kws in keywords.items():
                    if event_name in self._sounds:
                        continue  # zaten assets/sounds'dan yüklendi
                    if any(kw in lower for kw in kws):
                        try:
                            snd = pygame.mixer.Sound(full)
                            snd.set_volume(self._sfx_volume)
                            self._sounds[event_name] = snd
                        except pygame.error:
                            pass

    def _start_music(self) -> None:
        """assets/music/ içindeki ilk OGG'u döngüde çal."""
        if not os.path.isdir(GAME_MUSIC):
            return
        candidates = sorted(
            f for f in os.listdir(GAME_MUSIC)
            if f.lower().endswith((".ogg", ".mp3", ".wav"))
            and not f.startswith("README")
        )
        if not candidates:
            return
        music_path = os.path.join(GAME_MUSIC, candidates[0])
        try:
            pygame.mixer.music.load(music_path)
            pygame.mixer.music.set_volume(self._music_volume)
            pygame.mixer.music.play(loops=-1, fade_ms=1500)
            self._music_playing = True
        except pygame.error:
            pass

    # ── Yardımcı: sentetik ses üretimi ───────────────────────────────────────

    def _make_tone(self, frequency: float, duration_s: float, volume: float) -> pygame.mixer.Sound:
        sample_count = max(1, int(self._sample_rate * max(0.02, duration_s)))
        buf = array("h")
        fade_out = int(sample_count * 0.22)
        for i in range(sample_count):
            t = i / self._sample_rate
            amp = math.sin(2.0 * math.pi * frequency * t)
            if i >= sample_count - fade_out:
                k = (sample_count - i) / max(1, fade_out)
                amp *= max(0.0, min(1.0, k))
            val = int(32767 * volume * amp)
            buf.append(val)
        return pygame.mixer.Sound(buffer=buf.tobytes())

    # ── Genel API ─────────────────────────────────────────────────────────────

    def play(self, event_name: str) -> None:
        """Belirtilen sesi cooldown'a bakarak çal."""
        if not self.enabled:
            return
        snd = self._sounds.get(event_name)
        if snd is None:
            return
        now = pygame.time.get_ticks()
        cooldown = self._COOLDOWNS_MS.get(event_name, 0)
        prev = self._last_play_ms.get(event_name, -999999)
        if now - prev < cooldown:
            return
        self._last_play_ms[event_name] = now
        snd.play()

    def set_sfx_volume(self, vol: float) -> None:
        self._sfx_volume = max(0.0, min(1.0, vol))
        for snd in self._sounds.values():
            snd.set_volume(self._sfx_volume)

    def set_music_volume(self, vol: float) -> None:
        self._music_volume = max(0.0, min(1.0, vol))
        if pygame.mixer.get_init():
            pygame.mixer.music.set_volume(self._music_volume)

    def pause_music(self) -> None:
        if pygame.mixer.get_init():
            pygame.mixer.music.pause()

    def resume_music(self) -> None:
        if pygame.mixer.get_init():
            pygame.mixer.music.unpause()

    @property
    def loaded_sounds(self) -> list[str]:
        """Yüklü ses efekti adları listesi."""
        return list(self._sounds.keys())
