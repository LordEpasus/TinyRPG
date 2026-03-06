from __future__ import annotations

from dataclasses import dataclass


AGE_DARK = "dark"
AGE_FEUDAL = "feudal"
AGE_CASTLE = "castle"

AGE_ORDER = (AGE_DARK, AGE_FEUDAL, AGE_CASTLE)
AGE_LABELS = {
    AGE_DARK: "Karanlik Cag",
    AGE_FEUDAL: "Feodal Cag",
    AGE_CASTLE: "Kale Cagi",
}

AGE_UP_COSTS: dict[str, dict[str, int]] = {
    AGE_FEUDAL: {"gold": 260, "wood": 180, "stone": 120},
    AGE_CASTLE: {"gold": 420, "wood": 260, "stone": 280},
}

AGE_UP_DURATION_S: dict[str, float] = {
    AGE_FEUDAL: 12.0,
    AGE_CASTLE: 18.0,
}

AGE_COMBAT_MULT = {
    AGE_DARK: 1.00,
    AGE_FEUDAL: 1.08,
    AGE_CASTLE: 1.18,
}


@dataclass(slots=True)
class CivTechState:
    age_index: int = 0
    researching_target: str | None = None
    researching_remaining_s: float = 0.0
    researching_total_s: float = 0.0

    @property
    def age(self) -> str:
        return AGE_ORDER[max(0, min(len(AGE_ORDER) - 1, self.age_index))]


class TechTree:
    def __init__(self, civilizations: list[str] | tuple[str, ...] | None = None) -> None:
        self._states: dict[str, CivTechState] = {}
        for civ in civilizations or []:
            self.register_civilization(civ)

    def register_civilization(self, civ: str) -> None:
        if civ not in self._states:
            self._states[civ] = CivTechState()

    def state(self, civ: str) -> CivTechState:
        self.register_civilization(civ)
        return self._states[civ]

    def age(self, civ: str) -> str:
        return self.state(civ).age

    def age_label(self, civ: str) -> str:
        return AGE_LABELS.get(self.age(civ), self.age(civ).title())

    def age_multiplier(self, civ: str) -> float:
        return float(AGE_COMBAT_MULT.get(self.age(civ), 1.0))

    def next_age(self, civ: str) -> str | None:
        st = self.state(civ)
        nxt = st.age_index + 1
        if nxt >= len(AGE_ORDER):
            return None
        return AGE_ORDER[nxt]

    def next_age_cost(self, civ: str) -> dict[str, int] | None:
        nxt = self.next_age(civ)
        if nxt is None:
            return None
        return dict(AGE_UP_COSTS.get(nxt, {}))

    def can_start_age_up(self, civ: str) -> bool:
        st = self.state(civ)
        return st.researching_target is None and self.next_age(civ) is not None

    def start_age_up(self, civ: str) -> bool:
        st = self.state(civ)
        if st.researching_target is not None:
            return False
        nxt = self.next_age(civ)
        if nxt is None:
            return False
        total = float(AGE_UP_DURATION_S.get(nxt, 10.0))
        st.researching_target = nxt
        st.researching_total_s = total
        st.researching_remaining_s = total
        return True

    def research_progress(self, civ: str) -> float:
        st = self.state(civ)
        if st.researching_target is None:
            return 0.0
        total = max(0.001, st.researching_total_s)
        return max(0.0, min(1.0, 1.0 - st.researching_remaining_s / total))

    def update(self, dt: float) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        step = max(0.0, float(dt))
        if step <= 0.0:
            return out
        for civ, st in self._states.items():
            if st.researching_target is None:
                continue
            st.researching_remaining_s -= step
            if st.researching_remaining_s > 0.0:
                continue
            st.age_index = min(len(AGE_ORDER) - 1, st.age_index + 1)
            new_age = st.age
            st.researching_target = None
            st.researching_remaining_s = 0.0
            st.researching_total_s = 0.0
            out.append((civ, new_age))
        return out

    def serialize(self) -> dict[str, dict[str, object]]:
        out: dict[str, dict[str, object]] = {}
        for civ, st in self._states.items():
            out[civ] = {
                "age_index": int(st.age_index),
                "researching_target": st.researching_target,
                "researching_remaining_s": float(st.researching_remaining_s),
                "researching_total_s": float(st.researching_total_s),
            }
        return out

    def apply_serialized(self, payload: dict[str, dict[str, object]]) -> None:
        for civ, data in payload.items():
            self.register_civilization(civ)
            st = self._states[civ]
            st.age_index = max(0, min(len(AGE_ORDER) - 1, int(data.get("age_index", 0))))
            tgt = data.get("researching_target")
            st.researching_target = str(tgt) if isinstance(tgt, str) and tgt else None
            st.researching_remaining_s = max(0.0, float(data.get("researching_remaining_s", 0.0)))
            st.researching_total_s = max(0.0, float(data.get("researching_total_s", 0.0)))
