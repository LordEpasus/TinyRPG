from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.entities.building import Building
    from src.entities.unit import Unit


@dataclass
class Civilization:
    color: str
    resources: dict[str, int] = field(default_factory=lambda: {"gold": 0, "wood": 0, "stone": 0})
    units: list["Unit"] = field(default_factory=list)
    buildings: list["Building"] = field(default_factory=list)

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

    def can_afford(self, costs: dict[str, int]) -> bool:
        for key, amount in costs.items():
            val = int(amount)
            if val <= 0:
                continue
            if self.resources.get(key, 0) < val:
                return False
        return True

    def spend(self, costs: dict[str, int]) -> bool:
        if not self.can_afford(costs):
            return False
        for key, amount in costs.items():
            val = int(amount)
            if val > 0:
                self.resources[key] = max(0, self.resources.get(key, 0) - val)
        return True

    def gain(self, resource_type: str, amount: int) -> int:
        if amount <= 0:
            return 0
        self.resources[resource_type] = self.resources.get(resource_type, 0) + int(amount)
        return int(amount)
