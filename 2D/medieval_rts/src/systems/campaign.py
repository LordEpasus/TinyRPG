from __future__ import annotations

import pygame

from src.entities.building import Building
from src.entities.unit import Unit
from src.systems.tech_tree import AGE_CASTLE


class CampaignTracker:
    def __init__(self, *, enabled: bool, mission_id: int, player_civilization: str) -> None:
        self.enabled = bool(enabled)
        self.mission_id = int(mission_id)
        self.player_civilization = player_civilization
        self.enemy_buildings_destroyed = 0
        self.done = False

    def on_enemy_building_destroyed(self, count: int = 1) -> None:
        if not self.enabled:
            return
        self.enemy_buildings_destroyed += max(0, int(count))

    def _player_units(self, game) -> list[Unit]:
        return [u for u in game.units if (not u.is_dead and u.civilization == self.player_civilization)]

    def _player_buildings(self, game) -> list[Building]:
        return [
            b
            for b in game.buildings
            if (not b.is_dead and b.civilization == self.player_civilization)
        ]

    def update(self, game) -> bool:
        if not self.enabled or self.done:
            return self.done

        p_units = self._player_units(game)
        p_buildings = self._player_buildings(game)

        if self.mission_id == 1:
            has_barracks = any(b.building_type == Building.TYPE_BARRACKS and b.is_complete for b in p_buildings)
            army_count = sum(1 for u in p_units if u.unit_class in (Unit.ROLE_WARRIOR, Unit.ROLE_ARCHER, Unit.ROLE_LANCER))
            if has_barracks and army_count >= 3 and self.enemy_buildings_destroyed >= 1:
                self.done = True
        else:
            age_ok = game.tech_tree.age(game.player_civilization) == AGE_CASTLE
            army_count = sum(1 for u in p_units if u.unit_class in (Unit.ROLE_WARRIOR, Unit.ROLE_ARCHER, Unit.ROLE_LANCER))
            enemy_castles = [
                b
                for b in game.buildings
                if (
                    not b.is_dead
                    and b.civilization in game.enemy_civilizations
                    and b.building_type == Building.TYPE_CASTLE
                )
            ]
            if age_ok and army_count >= 8 and not enemy_castles:
                self.done = True

        return self.done

    def lines(self, game) -> list[str]:
        if not self.enabled:
            return []

        p_units = self._player_units(game)
        p_buildings = self._player_buildings(game)
        if self.mission_id == 1:
            has_barracks = any(b.building_type == Building.TYPE_BARRACKS and b.is_complete for b in p_buildings)
            army_count = sum(1 for u in p_units if u.unit_class in (Unit.ROLE_WARRIOR, Unit.ROLE_ARCHER, Unit.ROLE_LANCER))
            return [
                "Campaign 1: Kurulus",
                f"[{ 'x' if has_barracks else ' '}] Barracks insa et",
                f"[{ 'x' if army_count >= 3 else ' '}] 3 asker uret ({army_count}/3)",
                f"[{ 'x' if self.enemy_buildings_destroyed >= 1 else ' '}] 1 dusman binasi yik ({self.enemy_buildings_destroyed}/1)",
            ]

        age_ok = game.tech_tree.age(game.player_civilization) == AGE_CASTLE
        army_count = sum(1 for u in p_units if u.unit_class in (Unit.ROLE_WARRIOR, Unit.ROLE_ARCHER, Unit.ROLE_LANCER))
        enemy_castles = [
            b
            for b in game.buildings
            if (
                not b.is_dead
                and b.civilization in game.enemy_civilizations
                and b.building_type == Building.TYPE_CASTLE
            )
        ]
        return [
            "Campaign 2: Kusatma",
            f"[{ 'x' if age_ok else ' '}] Kale Cagina yuksel",
            f"[{ 'x' if army_count >= 8 else ' '}] 8 asker hazirla ({army_count}/8)",
            f"[{ 'x' if not enemy_castles else ' '}] Tum dusman kalelerini yok et ({len(enemy_castles)} kaldi)",
        ]

    def draw(self, screen: pygame.Surface, font_sm: pygame.font.Font, lines: list[str]) -> None:
        if not self.enabled or not lines:
            return

        panel_w = 390
        panel_h = 20 + len(lines) * 18
        x = 10
        y = screen.get_height() - panel_h - 14

        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (18, 24, 32, 212), panel.get_rect(), border_radius=10)
        pygame.draw.rect(panel, (98, 132, 170, 236), panel.get_rect(), 1, border_radius=10)
        screen.blit(panel, (x, y))

        for i, line in enumerate(lines):
            color = (236, 222, 146) if i == 0 else (210, 220, 232)
            surf = font_sm.render(line, True, color)
            screen.blit(surf, (x + 10, y + 8 + i * 18))
