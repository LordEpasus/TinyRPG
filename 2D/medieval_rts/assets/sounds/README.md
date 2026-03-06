# Medieval RTS — Sound Effects

All sounds generated with SoX (Sound eXchange) — 100% original, CC0 / Public Domain.
Sample rate: 44100 Hz, Mono, OGG Vorbis.

| File        | Use                              | Duration |
|-------------|----------------------------------|----------|
| select.ogg  | Unit selected (metallic ping)    | 0.15s    |
| move.ogg    | Move order issued (footstep)     | 0.20s    |
| attack.ogg  | Sword clash (sharp + ring)       | 0.40s    |
| build.ogg   | Construction hit (hammer thud)   | 0.25s    |
| death.ogg   | Unit death (impact + low tone)   | 0.60s    |
| alert.ogg   | Enemy spotted / event            | 0.24s    |
| error.ogg   | Invalid action denial            | 0.20s    |
| gold.ogg    | Resource/gold collected          | 0.24s    |
| train.ogg   | Unit training complete           | 0.50s    |

## pygame Usage Example
```python
import pygame
pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

sounds = {
    'select': pygame.mixer.Sound('assets/sounds/select.ogg'),
    'move':   pygame.mixer.Sound('assets/sounds/move.ogg'),
    'attack': pygame.mixer.Sound('assets/sounds/attack.ogg'),
    'build':  pygame.mixer.Sound('assets/sounds/build.ogg'),
    'death':  pygame.mixer.Sound('assets/sounds/death.ogg'),
    'alert':  pygame.mixer.Sound('assets/sounds/alert.ogg'),
    'error':  pygame.mixer.Sound('assets/sounds/error.ogg'),
    'gold':   pygame.mixer.Sound('assets/sounds/gold.ogg'),
    'train':  pygame.mixer.Sound('assets/sounds/train.ogg'),
}

sounds['select'].set_volume(0.7)
sounds['select'].play()
```

## Music
See assets/music/README.md
