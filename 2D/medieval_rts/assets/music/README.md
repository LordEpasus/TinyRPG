# Medieval RTS — Music

All music generated with SoX — 100% original, CC0 / Public Domain.

| File                  | Style              | Duration | Loop |
|-----------------------|--------------------|----------|------|
| medieval_ambient.ogg  | Dark ambient drone | 32s      | Yes  |

## pygame Usage Example
```python
import pygame
pygame.mixer.music.load('assets/music/medieval_ambient.ogg')
pygame.mixer.music.set_volume(0.4)
pygame.mixer.music.play(loops=-1)   # -1 = infinite loop
```
