from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.entities.building import Building
    from src.entities.unit import Unit


@dataclass
class Civilization:
    kingdom_id: str
    asset_color: str
    display_name: str = ""
    parent_kingdom_id: str | None = None
    ruler_unit_id: int | None = None
    capital_building_id: int | None = None
    stability: float = 78.0
    loyalty: float = 82.0
    capital_stockpile: dict[str, int] = field(
        default_factory=lambda: {"gold": 0, "wood": 0, "stone": 0, "food": 0, "meat": 0}
    )
    resources: dict[str, int] = field(
        default_factory=lambda: {"gold": 0, "wood": 0, "stone": 0, "food": 0, "meat": 0}
    )
    upkeep_pressure: float = 0.0
    food_upkeep_progress: float = 0.0
    gold_upkeep_progress: float = 0.0
    split_cooldown: float = 0.0
    is_major: bool = True
    crest: str = ""
    display_color: tuple[int, int, int] = (200, 200, 200)
    units: list["Unit"] = field(default_factory=list)
    buildings: list["Building"] = field(default_factory=list)

    @property
    def color(self) -> str:
        return self.asset_color

    def add_unit(self, unit: "Unit") -> None:
        if unit not in self.units:
            self.units.append(unit)

    def remove_unit(self, unit: "Unit") -> None:
        if unit in self.units:
            self.units.remove(unit)

    def add_building(self, building: "Building") -> None:
        if building not in self.buildings:
            self.buildings.append(building)

    def remove_building(self, building: "Building") -> None:
        if building in self.buildings:
            self.buildings.remove(building)

    def cleanup(self) -> None:
        self.units = [u for u in self.units if not getattr(u, "is_dead", False)]
        self.buildings = [b for b in self.buildings if not getattr(b, "is_dead", False)]
        self.split_cooldown = max(0.0, float(self.split_cooldown))

    def can_afford(self, costs: dict[str, int]) -> bool:
        for key, amount in costs.items():
            val = int(amount)
            if val <= 0:
                continue
            if self.capital_stockpile.get(key, 0) < val:
                return False
        return True

    def spend(self, costs: dict[str, int]) -> bool:
        if not self.can_afford(costs):
            return False
        for key, amount in costs.items():
            val = int(amount)
            if val > 0:
                self.capital_stockpile[key] = max(0, self.capital_stockpile.get(key, 0) - val)
                self.resources[key] = self.capital_stockpile[key]
        return True

    def gain(self, resource_type: str, amount: int) -> int:
        if amount <= 0:
            return 0
        self.capital_stockpile[resource_type] = self.capital_stockpile.get(resource_type, 0) + int(amount)
        self.resources[resource_type] = self.capital_stockpile[resource_type]
        return int(amount)

    def set_stockpile(self, payload: dict[str, int]) -> None:
        for key in ("gold", "wood", "stone", "food", "meat"):
            self.capital_stockpile[key] = int(payload.get(key, self.capital_stockpile.get(key, 0)))
            self.resources[key] = self.capital_stockpile[key]

    def consume_food(self, amount: int = 1) -> bool:
        need = max(1, int(amount))
        if self.capital_stockpile.get("food", 0) >= need:
            self.capital_stockpile["food"] -= need
            self.resources["food"] = self.capital_stockpile["food"]
            return True
        if self.capital_stockpile.get("meat", 0) >= need:
            self.capital_stockpile["meat"] -= need
            self.resources["meat"] = self.capital_stockpile["meat"]
            return True
        return False
