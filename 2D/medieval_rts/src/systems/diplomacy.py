from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game import Game


class TreatyState:
    WAR = "WAR"
    TRUCE = "TRUCE"
    NEUTRAL = "NEUTRAL"
    TRADE = "TRADE"
    VASSAL_TRIBUTE = "VASSAL_TRIBUTE"

    ALL = (WAR, TRUCE, NEUTRAL, TRADE, VASSAL_TRIBUTE)


@dataclass(slots=True)
class RelationState:
    pair: tuple[str, str]
    state: str = TreatyState.NEUTRAL
    score: float = 0.0
    tension: float = 0.0
    war_exhaustion: float = 0.0
    tribute_from: str = ""
    tribute_to: str = ""
    truce_until_s: float = 0.0
    trade_bias: float = 0.0
    last_reason: str = ""
    last_change_tick: int = 0
    last_tribute_s: float = 0.0


@dataclass(slots=True)
class ThreatAssessment:
    kingdom_id: str
    best_enemy: str = ""
    rebel_target: str = ""
    pressure: float = 0.0
    naval_required: bool = False
    capital_risk: float = 0.0
    trade_partner: str = ""
    tribute_target: str = ""
    suppress_rebels: bool = False
    notes: list[str] = field(default_factory=list)


class DiplomacyManager:
    def __init__(self, seed: int) -> None:
        self._seed = int(seed)
        self._time_s = 0.0
        self._relations: dict[tuple[str, str], RelationState] = {}
        self._path_cache: dict[tuple[str, str], tuple[bool, float]] = {}
        self._recent_changes: list[dict[str, object]] = []
        self._recent_tributes: list[dict[str, object]] = []
        self._last_ledger_lines: list[str] = []

    @staticmethod
    def _pair_key(left: str, right: str) -> tuple[str, str]:
        return (left, right) if left <= right else (right, left)

    def ensure_roster(self, kingdom_ids: list[str]) -> None:
        roster = sorted({str(kid) for kid in kingdom_ids if kid})
        for idx, left in enumerate(roster):
            for right in roster[idx + 1 :]:
                key = self._pair_key(left, right)
                if key not in self._relations:
                    self._relations[key] = RelationState(pair=key)

    def relation(self, left: str, right: str) -> RelationState:
        key = self._pair_key(left, right)
        rel = self._relations.get(key)
        if rel is None:
            rel = RelationState(pair=key)
            self._relations[key] = rel
        return rel

    def treaty_between(self, left: str, right: str) -> str:
        if not left or not right or left == right:
            return TreatyState.NEUTRAL
        return self.relation(left, right).state

    def is_hostile(self, left: str, right: str) -> bool:
        if not left or not right or left == right:
            return False
        return self.relation(left, right).state == TreatyState.WAR

    def trade_partners_for(self, kingdom_id: str) -> list[str]:
        out: list[str] = []
        for rel in self._relations.values():
            if kingdom_id not in rel.pair:
                continue
            if rel.state == TreatyState.TRADE:
                out.append(rel.pair[0] if rel.pair[1] == kingdom_id else rel.pair[1])
        return out

    def war_targets_for(self, kingdom_id: str) -> list[str]:
        out: list[str] = []
        for rel in self._relations.values():
            if kingdom_id not in rel.pair:
                continue
            if rel.state == TreatyState.WAR:
                out.append(rel.pair[0] if rel.pair[1] == kingdom_id else rel.pair[1])
        return out

    def tributary_info_for(self, kingdom_id: str) -> tuple[str, str] | None:
        for rel in self._relations.values():
            if rel.state != TreatyState.VASSAL_TRIBUTE:
                continue
            if rel.tribute_from == kingdom_id or rel.tribute_to == kingdom_id:
                return rel.tribute_from, rel.tribute_to
        return None

    def note_split(self, parent_id: str, child_id: str, *, tick: int, duration_s: float) -> None:
        rel = self.relation(parent_id, child_id)
        rel.state = TreatyState.TRUCE
        rel.truce_until_s = self._time_s + max(3.0, float(duration_s))
        rel.last_reason = "split_truce"
        rel.last_change_tick = int(tick)
        rel.tension = max(rel.tension, 0.65)
        rel.trade_bias = 0.0
        rel.tribute_from = ""
        rel.tribute_to = ""
        self._recent_changes.append(
            {
                "left": parent_id,
                "right": child_id,
                "state": rel.state,
                "reason": rel.last_reason,
                "tick": int(tick),
                "truce_until_s": float(rel.truce_until_s),
            }
        )

    def declare_war(self, left: str, right: str, *, tick: int, reason: str = "manual") -> None:
        rel = self.relation(left, right)
        if rel.state == TreatyState.WAR:
            return
        rel.state = TreatyState.WAR
        rel.last_reason = str(reason)
        rel.last_change_tick = int(tick)
        rel.truce_until_s = 0.0
        rel.tribute_from = ""
        rel.tribute_to = ""
        rel.trade_bias = 0.0
        rel.tension = max(rel.tension, 0.82)
        self._recent_changes.append(
            {
                "left": left,
                "right": right,
                "state": rel.state,
                "reason": rel.last_reason,
                "tick": int(tick),
                "truce_until_s": float(rel.truce_until_s),
            }
        )

    def consume_recent_changes(self) -> list[dict[str, object]]:
        out = list(self._recent_changes)
        self._recent_changes.clear()
        return out

    def consume_recent_tributes(self) -> list[dict[str, object]]:
        out = list(self._recent_tributes)
        self._recent_tributes.clear()
        return out

    def serialize(self) -> dict[str, object]:
        pairs: list[dict[str, object]] = []
        for key in sorted(self._relations):
            rel = self._relations[key]
            pairs.append(
                {
                    "left": rel.pair[0],
                    "right": rel.pair[1],
                    "state": rel.state,
                    "score": round(float(rel.score), 3),
                    "tension": round(float(rel.tension), 3),
                    "war_exhaustion": round(float(rel.war_exhaustion), 3),
                    "tribute_from": rel.tribute_from,
                    "tribute_to": rel.tribute_to,
                    "truce_until_s": round(float(rel.truce_until_s), 3),
                    "trade_bias": round(float(rel.trade_bias), 3),
                    "last_reason": rel.last_reason,
                    "last_change_tick": int(rel.last_change_tick),
                    "last_tribute_s": round(float(rel.last_tribute_s), 3),
                }
            )
        return {"time_s": round(float(self._time_s), 3), "pairs": pairs}

    def apply_serialized(self, payload: dict[str, object]) -> None:
        self._time_s = float(payload.get("time_s", self._time_s))
        raw_pairs = payload.get("pairs", [])
        if not isinstance(raw_pairs, list):
            return
        for item in raw_pairs:
            if not isinstance(item, dict):
                continue
            left = str(item.get("left", ""))
            right = str(item.get("right", ""))
            if not left or not right or left == right:
                continue
            rel = self.relation(left, right)
            rel.state = str(item.get("state", rel.state))
            if rel.state not in TreatyState.ALL:
                rel.state = TreatyState.NEUTRAL
            rel.score = float(item.get("score", rel.score))
            rel.tension = float(item.get("tension", rel.tension))
            rel.war_exhaustion = float(item.get("war_exhaustion", rel.war_exhaustion))
            rel.tribute_from = str(item.get("tribute_from", rel.tribute_from))
            rel.tribute_to = str(item.get("tribute_to", rel.tribute_to))
            rel.truce_until_s = float(item.get("truce_until_s", rel.truce_until_s))
            rel.trade_bias = float(item.get("trade_bias", rel.trade_bias))
            rel.last_reason = str(item.get("last_reason", rel.last_reason))
            rel.last_change_tick = int(item.get("last_change_tick", rel.last_change_tick))
            rel.last_tribute_s = float(item.get("last_tribute_s", rel.last_tribute_s))

    def update(self, game: "Game", dt: float, *, tick: int, min_duration_s: float, tribute_interval_s: float, war_exhaustion_max: float) -> None:
        self._time_s += max(0.0, float(dt))
        roster = [kid for kid in game._active_civilized_kingdom_ids() if not game._is_chaos_civ(game._kingdom(kid).asset_color)]
        self.ensure_roster(roster)
        self._last_ledger_lines = []
        pair_notes: list[tuple[str, float]] = []

        for idx, left in enumerate(sorted(roster)):
            civ_left = game._kingdom(left)
            for right in sorted(roster)[idx + 1 :]:
                civ_right = game._kingdom(right)
                rel = self.relation(left, right)
                rel.war_exhaustion = max(0.0, min(float(war_exhaustion_max), rel.war_exhaustion))
                score = self._pair_score(game, left, right, civ_left, civ_right, rel)
                rel.score = score
                rel.tension = max(0.0, min(1.0, rel.tension * 0.82 + max(0.0, score) * 0.18))
                desired_state, reason, tribute_from, tribute_to = self._decide_state(
                    game,
                    left,
                    right,
                    civ_left,
                    civ_right,
                    rel,
                    score,
                )
                if rel.state == TreatyState.TRUCE and self._time_s < rel.truce_until_s and desired_state != TreatyState.WAR:
                    desired_state = TreatyState.TRUCE
                    reason = rel.last_reason or "truce_hold"
                elif rel.state == TreatyState.TRUCE and self._time_s >= rel.truce_until_s and desired_state == TreatyState.TRUCE:
                    desired_state = TreatyState.NEUTRAL
                    reason = "truce_expired"

                if desired_state != rel.state:
                    rel.state = desired_state
                    rel.last_reason = reason
                    rel.last_change_tick = int(tick)
                    rel.trade_bias = 0.22 if desired_state == TreatyState.TRADE else 0.0
                    rel.truce_until_s = self._time_s + min_duration_s if desired_state == TreatyState.TRUCE else rel.truce_until_s
                    if desired_state != TreatyState.VASSAL_TRIBUTE:
                        rel.tribute_from = ""
                        rel.tribute_to = ""
                    else:
                        rel.tribute_from = tribute_from
                        rel.tribute_to = tribute_to
                    if desired_state != TreatyState.WAR:
                        rel.war_exhaustion = max(0.0, rel.war_exhaustion * 0.72)
                    self._recent_changes.append(
                        {
                            "left": left,
                            "right": right,
                            "state": desired_state,
                            "reason": reason,
                            "tick": int(tick),
                            "tribute_from": rel.tribute_from,
                            "tribute_to": rel.tribute_to,
                            "truce_until_s": float(rel.truce_until_s),
                        }
                    )
                else:
                    rel.last_reason = reason or rel.last_reason
                    if rel.state == TreatyState.VASSAL_TRIBUTE:
                        rel.tribute_from = tribute_from
                        rel.tribute_to = tribute_to

                if rel.state == TreatyState.WAR:
                    rel.war_exhaustion = min(float(war_exhaustion_max), rel.war_exhaustion + 0.18)
                else:
                    rel.war_exhaustion = max(0.0, rel.war_exhaustion - 0.07)

                if rel.state == TreatyState.VASSAL_TRIBUTE and rel.tribute_from and rel.tribute_to:
                    self._apply_tribute(game, rel, interval_s=tribute_interval_s, tick=tick)

                pair_notes.append((self._relation_label(game, left, right, rel), abs(score)))

        self._sync_civilization_views(game)
        pair_notes.sort(key=lambda item: item[1], reverse=True)
        self._last_ledger_lines = [label for label, _ in pair_notes[:5]]

    def assess_kingdom(self, game: "Game", kingdom_id: str) -> ThreatAssessment:
        civ = game._kingdom(kingdom_id)
        major_enemies = self.war_targets_for(kingdom_id)
        rebel_targets = [kid for kid in major_enemies if game._kingdom(kid).parent_kingdom_id == kingdom_id or civ.parent_kingdom_id == kid]
        best_enemy = ""
        best_score = -1.0
        for enemy_id in major_enemies:
            enemy = game._kingdom(enemy_id)
            score = self._military_power(enemy) + max(0.0, 60.0 - enemy.stability) * 0.3
            if score > best_score:
                best_enemy = enemy_id
                best_score = score
        trade_partner = ""
        trades = self.trade_partners_for(kingdom_id)
        if trades:
            trade_partner = trades[0]
        tribute_target = ""
        tributary = self.tributary_info_for(kingdom_id)
        if tributary is not None:
            tribute_target = tributary[1] if tributary[0] == kingdom_id else tributary[0]
        food_days, gold_days = self._stock_days(game, civ)
        capital_risk = max(0.0, (3.4 - food_days)) + max(0.0, (3.0 - gold_days)) + max(0.0, (45.0 - civ.stability) / 22.0)
        naval_required = False
        if best_enemy:
            naval_required = not self._can_capitals_meet(game, kingdom_id, best_enemy)
        notes: list[str] = []
        if rebel_targets:
            notes.append("isyan")
        if trade_partner:
            notes.append("ticaret")
        if tribute_target:
            notes.append("haraç")
        if naval_required:
            notes.append("deniz")
        return ThreatAssessment(
            kingdom_id=kingdom_id,
            best_enemy=best_enemy,
            rebel_target=rebel_targets[0] if rebel_targets else "",
            pressure=max(0.0, best_score),
            naval_required=naval_required,
            capital_risk=capital_risk,
            trade_partner=trade_partner,
            tribute_target=tribute_target,
            suppress_rebels=bool(rebel_targets),
            notes=notes,
        )

    def ledger_lines(self, game: "Game", viewer_id: str, *, limit: int = 5) -> list[str]:
        lines = list(self._last_ledger_lines)
        if not lines:
            for key in sorted(self._relations):
                rel = self._relations[key]
                if viewer_id not in rel.pair and rel.state == TreatyState.NEUTRAL:
                    continue
                lines.append(self._relation_label(game, key[0], key[1], rel))
                if len(lines) >= limit:
                    break
        return lines[: max(0, int(limit))]

    def _sync_civilization_views(self, game: "Game") -> None:
        for civ in game.civilizations.values():
            civ.relations.clear()
            civ.war_exhaustion = 0.0
            civ.tribute_balance = 0.0
            civ.suppression_priority = 0.0
            civ.naval_intent = 0.0
            civ.stance_bias = "steady"
            civ.capital_risk = 0.0
        for rel in self._relations.values():
            left, right = rel.pair
            if left not in game.civilizations or right not in game.civilizations:
                continue
            civ_left = game._kingdom(left)
            civ_right = game._kingdom(right)
            civ_left.relations[right] = rel.state
            civ_right.relations[left] = rel.state
            if rel.state == TreatyState.WAR:
                civ_left.war_exhaustion = max(civ_left.war_exhaustion, rel.war_exhaustion)
                civ_right.war_exhaustion = max(civ_right.war_exhaustion, rel.war_exhaustion)
                civ_left.stance_bias = civ_right.stance_bias = "martial"
            elif rel.state == TreatyState.TRADE:
                civ_left.stance_bias = civ_right.stance_bias = "mercantile"
            elif rel.state == TreatyState.VASSAL_TRIBUTE:
                if rel.tribute_from == left:
                    civ_left.tribute_balance -= 1.0
                    civ_right.tribute_balance += 1.0
                elif rel.tribute_from == right:
                    civ_right.tribute_balance -= 1.0
                    civ_left.tribute_balance += 1.0
            if rel.state in (TreatyState.WAR, TreatyState.TRUCE) and (civ_right.parent_kingdom_id == left or civ_left.parent_kingdom_id == right):
                civ_left.suppression_priority = max(civ_left.suppression_priority, 1.0)
                civ_right.suppression_priority = max(civ_right.suppression_priority, 1.0)

        for kid, civ in game.civilizations.items():
            food_days, gold_days = self._stock_days(game, civ)
            civ.capital_risk = max(0.0, (3.2 - food_days)) + max(0.0, (2.8 - gold_days)) + max(0.0, (50.0 - civ.stability) / 25.0)
            assessment = self.assess_kingdom(game, kid)
            civ.naval_intent = 1.0 if assessment.naval_required else 0.0
            civ.diplomatic_memory["pressure"] = round(float(assessment.pressure), 3)
            civ.diplomatic_memory["capital_risk"] = round(float(assessment.capital_risk), 3)
            civ.diplomatic_memory["war_targets"] = float(len(self.war_targets_for(kid)))
            civ.diplomatic_memory["trade_links"] = float(len(self.trade_partners_for(kid)))

    def _pair_score(self, game: "Game", left: str, right: str, civ_left, civ_right, rel: RelationState) -> float:
        power_left = self._military_power(civ_left)
        power_right = self._military_power(civ_right)
        power_delta = (power_left - power_right) / max(40.0, power_left + power_right)
        capital_left = game._capital_for_kingdom(left)
        capital_right = game._capital_for_kingdom(right)
        distance_term = 0.0
        if capital_left is not None and capital_right is not None:
            dx = capital_left.world_pos.x - capital_right.world_pos.x
            dy = capital_left.world_pos.y - capital_right.world_pos.y
            distance_term = max(0.0, 1.25 - math.sqrt(dx * dx + dy * dy) / (game.tilemap.cols * 0.8 * 64.0))
        food_left, gold_left = self._stock_days(game, civ_left)
        food_right, gold_right = self._stock_days(game, civ_right)
        reserve_left = min(food_left / 4.2, gold_left / 3.8)
        reserve_right = min(food_right / 4.2, gold_right / 3.8)
        shortage_pull = max(0.0, 1.0 - reserve_left) - max(0.0, 1.0 - reserve_right)
        split_pressure = 0.0
        if civ_right.parent_kingdom_id == left or civ_left.parent_kingdom_id == right:
            split_pressure = 0.74
        naval_penalty = 0.12 if not self._can_capitals_meet(game, left, right) else 0.0
        score = distance_term * 0.58 + power_delta * 0.92 + shortage_pull * 0.65 + split_pressure - naval_penalty
        score += rel.tension * 0.45
        return score

    def _decide_state(self, game: "Game", left: str, right: str, civ_left, civ_right, rel: RelationState, score: float) -> tuple[str, str, str, str]:
        power_left = self._military_power(civ_left)
        power_right = self._military_power(civ_right)
        ratio_lr = power_left / max(1.0, power_right)
        ratio_rl = power_right / max(1.0, power_left)
        food_left, gold_left = self._stock_days(game, civ_left)
        food_right, gold_right = self._stock_days(game, civ_right)
        weak_left = civ_left.stability < 42.0 or min(food_left, gold_left) < 1.7
        weak_right = civ_right.stability < 42.0 or min(food_right, gold_right) < 1.7
        parent_child = civ_right.parent_kingdom_id == left or civ_left.parent_kingdom_id == right

        tribute_from = ""
        tribute_to = ""
        if parent_child and self._time_s < rel.truce_until_s:
            return TreatyState.TRUCE, "split_truce", tribute_from, tribute_to

        if parent_child:
            if ratio_lr >= 1.22 and civ_right.parent_kingdom_id == left:
                return TreatyState.WAR, "suppression_war", tribute_from, tribute_to
            if ratio_rl >= 1.22 and civ_left.parent_kingdom_id == right:
                return TreatyState.WAR, "independence_war", tribute_from, tribute_to
            return TreatyState.TRUCE, "tense_border", tribute_from, tribute_to

        if rel.state == TreatyState.WAR and rel.war_exhaustion > 3.8 and (weak_left or weak_right):
            return TreatyState.TRUCE, "war_exhaustion", tribute_from, tribute_to

        if weak_left and weak_right:
            return TreatyState.TRADE, "mutual_shortage", tribute_from, tribute_to

        if ratio_lr >= 1.62 and weak_right and civ_right.loyalty < 46.0:
            tribute_from, tribute_to = right, left
            return TreatyState.VASSAL_TRIBUTE, "tribute_pressure", tribute_from, tribute_to
        if ratio_rl >= 1.62 and weak_left and civ_left.loyalty < 46.0:
            tribute_from, tribute_to = left, right
            return TreatyState.VASSAL_TRIBUTE, "tribute_pressure", tribute_from, tribute_to

        if score >= 0.72 and not weak_left:
            return TreatyState.WAR, "threat_window", tribute_from, tribute_to
        if score <= -0.72 and not weak_right:
            return TreatyState.WAR, "threat_window", tribute_from, tribute_to
        if abs(score) < 0.22 and (min(food_left, gold_left) < 3.5 or min(food_right, gold_right) < 3.5):
            return TreatyState.TRADE, "buffer_trade", tribute_from, tribute_to
        return TreatyState.NEUTRAL, "watchful_neutral", tribute_from, tribute_to

    def _apply_tribute(self, game: "Game", rel: RelationState, *, interval_s: float, tick: int) -> None:
        if self._time_s - rel.last_tribute_s < max(1.0, float(interval_s)):
            return
        payer = game._kingdom(rel.tribute_from)
        receiver = game._kingdom(rel.tribute_to)
        gold = min(24, max(0, payer.capital_stockpile.get("gold", 0) // 12))
        food = min(18, max(0, (payer.capital_stockpile.get("food", 0) + payer.capital_stockpile.get("meat", 0)) // 14))
        if gold <= 0 and food <= 0:
            payer.loyalty = max(0.0, payer.loyalty - 1.4)
            payer.stability = max(0.0, payer.stability - 0.9)
            rel.last_tribute_s = self._time_s
            return
        if gold > 0:
            payer.capital_stockpile["gold"] = max(0, payer.capital_stockpile.get("gold", 0) - gold)
            payer.resources["gold"] = payer.capital_stockpile["gold"]
            receiver.capital_stockpile["gold"] = receiver.capital_stockpile.get("gold", 0) + gold
            receiver.resources["gold"] = receiver.capital_stockpile["gold"]
        if food > 0:
            from_food = min(food, payer.capital_stockpile.get("food", 0))
            payer.capital_stockpile["food"] = max(0, payer.capital_stockpile.get("food", 0) - from_food)
            left = food - from_food
            if left > 0:
                payer.capital_stockpile["meat"] = max(0, payer.capital_stockpile.get("meat", 0) - left)
            payer.resources["food"] = payer.capital_stockpile.get("food", 0)
            payer.resources["meat"] = payer.capital_stockpile.get("meat", 0)
            receiver.capital_stockpile["food"] = receiver.capital_stockpile.get("food", 0) + food
            receiver.resources["food"] = receiver.capital_stockpile["food"]
        payer.tribute_balance -= 1.0
        receiver.tribute_balance += 1.0
        rel.last_tribute_s = self._time_s
        self._recent_tributes.append(
            {
                "from": rel.tribute_from,
                "to": rel.tribute_to,
                "gold": int(gold),
                "food": int(food),
                "tick": int(tick),
            }
        )

    def _relation_label(self, game: "Game", left: str, right: str, rel: RelationState) -> str:
        left_name = game._kingdom_display_name(left)
        right_name = game._kingdom_display_name(right)
        if rel.state == TreatyState.WAR:
            tag = "Savas"
        elif rel.state == TreatyState.TRUCE:
            tag = "Ateskes"
        elif rel.state == TreatyState.TRADE:
            tag = "Ticaret"
        elif rel.state == TreatyState.VASSAL_TRIBUTE:
            tag = f"Harac {game._kingdom_display_name(rel.tribute_from)}"
        else:
            tag = "Notr"
        return f"{left_name} - {right_name}: {tag}"

    def _military_power(self, civ) -> float:
        combat = sum(float(getattr(unit, "attack", 0.0)) + float(getattr(unit, "hp", 0.0)) * 0.18 for unit in civ.units if not unit.is_dead and unit.can_attack)
        buildings = sum(55.0 for building in civ.buildings if not building.is_dead and building.is_complete and building.building_type in ("tower", "castle", "barracks", "archery"))
        stock = civ.capital_stockpile.get("gold", 0) * 0.06 + civ.capital_stockpile.get("food", 0) * 0.03 + civ.capital_stockpile.get("meat", 0) * 0.02
        return combat + buildings + stock + max(0.0, civ.stability * 0.4)

    def _stock_days(self, game: "Game", civ) -> tuple[float, float]:
        food_rate, gold_rate = game._kingdom_upkeep_rates(civ)
        food_total = civ.capital_stockpile.get("food", 0) + civ.capital_stockpile.get("meat", 0)
        gold_total = civ.capital_stockpile.get("gold", 0)
        food_days = food_total / max(0.3, food_rate * 60.0)
        gold_days = gold_total / max(0.3, gold_rate * 60.0)
        return food_days, gold_days

    def _can_capitals_meet(self, game: "Game", left: str, right: str) -> bool:
        key = self._pair_key(left, right)
        cached = self._path_cache.get(key)
        if cached is not None and self._time_s - cached[1] < 5.0:
            return cached[0]
        a = game._capital_for_kingdom(left)
        b = game._capital_for_kingdom(right)
        if a is None or b is None:
            result = False
        else:
            points = game.pathfinder.find_path_world(
                a.spawn_anchor(),
                b.spawn_anchor(),
                blocked=game._building_blocked_tiles,
                max_expansions=6000,
            )
            result = bool(points)
        self._path_cache[key] = (result, self._time_s)
        return result
