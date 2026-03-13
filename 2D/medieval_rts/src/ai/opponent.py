from __future__ import annotations

import random
from typing import TYPE_CHECKING

from settings import TILE_SIZE
from src.entities.building import Building
from src.entities.ship import Ship
from src.entities.unit import Unit
from src.systems.diplomacy import TreatyState

if TYPE_CHECKING:
    from game import Game
    from src.systems.resources import ResourceNode


class AIController:
    STATE_EXPAND = "EXPAND"
    STATE_GATHER = "GATHER"
    STATE_ATTACK = "ATTACK"
    STATE_DEFEND = "DEFEND"
    STATE_STABILIZE = "STABILIZE"
    STATE_NAVAL_LOGISTICS = "NAVAL"
    STATE_CIVIL_WAR_RESPONSE = "CIVIL_WAR"
    STATE_SEEK_TRADE = "TRADE"
    STATE_ENFORCE_TRIBUTE = "TRIBUTE"
    STATE_FALLBACK_REBUILD = "REBUILD"
    _STATE_CYCLE = (STATE_EXPAND, STATE_GATHER, STATE_ATTACK)
    _STATE_DURATION = {
        STATE_EXPAND: 30.0,
        STATE_GATHER: 24.0,
        STATE_ATTACK: 22.0,
    }

    _BUILD_PLAN = (
        (Building.TYPE_HOUSE1, 1),
        (Building.TYPE_BARRACKS, 1),
        (Building.TYPE_HOUSE2, 1),
        (Building.TYPE_ARCHERY, 1),
        (Building.TYPE_HOUSE3, 1),
        (Building.TYPE_TOWER, 1),
        (Building.TYPE_SMITHY, 1),
        (Building.TYPE_CASTLE, 1),
    )

    def __init__(
        self,
        game: "Game",
        *,
        civilization: str = "Red",
        enemy_civilization: str = "Blue",
        seed: int = 2025,
        base_world: tuple[float, float] | None = None,
        asset_color: str | None = None,
    ) -> None:
        self.game = game
        self.civilization = civilization
        self.asset_color = asset_color or civilization
        self.enemy_civilization = enemy_civilization
        self._rng = random.Random(seed + 44041)
        self._base_world_hint = base_world

        # Stronger kingdom economy to better resist chaos and scale military.
        defaults = {
            "gold": 1450,
            "wood": 1400,
            "stone": 1300,
            "food": 220,
            "meat": 120,
        }
        existing = self.game.civilizations.get(self.civilization)
        self.resources = dict(existing.capital_stockpile) if existing is not None else dict(defaults)
        self.capacity = {
            "gold": 3200,
            "wood": 3200,
            "stone": 3000,
            "food": 1200,
            "meat": 1200,
        }

        self._elapsed_s = 0.0
        self._attack_unlock_s = 72.0
        self._state_index = 0
        self._state_timer_s = 0.0
        self._planned_state = self.STATE_EXPAND
        self._planner_timer_s = 0.8
        self._production_timer_s = 1.4
        self._expand_timer_s = 1.9
        self._gather_order_timer_s = 0.85
        self._construction_order_timer_s = 0.55
        self._attack_order_timer_s = 0.95
        self._naval_order_timer_s = 1.0
        self._scan_timer_s = 4.0
        self._defense_hold_s = 0.0
        self._attack_target_refresh_s = 0.0
        self._attack_target = None
        self._suppression_target = None
        self._naval_target_kingdom = ""
        self._path_cache: dict[tuple[tuple[int, int], tuple[int, int]], tuple[bool, float]] = {}
        self._resource_cache: dict[str, tuple[object | None, float]] = {}
        self._rally_radius = TILE_SIZE * 6.5
        self._threat_radius = TILE_SIZE * 13.0

        self._bootstrapped = False
        self._base_tile: tuple[int, int] = (0, 0)
        self._base_world: tuple[float, float] = (0.0, 0.0)
        self._rally_world: tuple[float, float] = (0.0, 0.0)
        self._scan_points: list[tuple[float, float]] = []
        self._scan_index = 0

    @property
    def state(self) -> str:
        if self._defense_hold_s > 0.0:
            return self.STATE_DEFEND
        return self._planned_state

    def bootstrap(self) -> None:
        if self._bootstrapped:
            return

        existing_units = [u for u in self.game.units if u.kingdom_id == self.civilization and not u.is_dead]
        existing_buildings = [b for b in self.game.buildings if b.kingdom_id == self.civilization and not b.is_dead]

        if existing_buildings:
            anchor = existing_buildings[0]
            bwx, bwy = anchor.world_pos.x, anchor.world_pos.y
        elif self._base_world_hint is not None:
            bwx, bwy = self.game._find_spawn_world_near(self._base_world_hint[0], self._base_world_hint[1])
        else:
            corner_tile = self._pick_opposite_corner_tile()
            corner_world = self.game.tilemap.tile_center(corner_tile[0], corner_tile[1])
            bwx, bwy = self.game._find_spawn_world_near(corner_world[0], corner_world[1])
        self._base_world = (bwx, bwy)
        self._base_tile = self.game.tilemap.world_to_tile(bwx, bwy)
        self._rally_world = self.game._find_spawn_world_near(
            self._base_world[0] - TILE_SIZE * 2.2,
            self._base_world[1] + TILE_SIZE * 1.6,
        )
        self._scan_points = self._build_scan_points()
        if not existing_units:
            self._spawn_initial_force()
        self._bootstrapped = True

    def update(self, dt: float) -> None:
        if not self._bootstrapped:
            self.bootstrap()

        self._elapsed_s += dt
        self._state_timer_s += dt
        self._production_timer_s -= dt
        self._expand_timer_s -= dt
        self._gather_order_timer_s -= dt
        self._construction_order_timer_s -= dt
        self._attack_order_timer_s -= dt
        self._naval_order_timer_s -= dt
        self._scan_timer_s -= dt
        self._attack_target_refresh_s -= dt
        self._planner_timer_s -= dt
        self._defense_hold_s = max(0.0, self._defense_hold_s - dt)

        if self._threat_level_near_base() >= 2:
            self._defense_hold_s = max(self._defense_hold_s, 6.0)

        if self._defense_hold_s > 0.0:
            if self._production_timer_s <= 0.0:
                self._production_timer_s = 1.35
                self._queue_production()
            self._run_defend()
            if self._scan_timer_s <= 0.0:
                self._scan_timer_s = 3.2
                self._run_scan()
            return

        if self._planner_timer_s <= 0.0:
            self._planner_timer_s = 2.4
            self._plan_state()

        if self._production_timer_s <= 0.0:
            self._production_timer_s = 1.35 if self.state in (self.STATE_ATTACK, self.STATE_DEFEND) else 1.65
            self._queue_production()

        if self.state == self.STATE_EXPAND:
            self._run_expand()
        elif self.state == self.STATE_GATHER:
            self._run_gather()
        elif self.state == self.STATE_STABILIZE:
            self._run_stabilize()
        elif self.state == self.STATE_NAVAL_LOGISTICS:
            self._run_naval_logistics()
        elif self.state == self.STATE_CIVIL_WAR_RESPONSE:
            self._run_civil_war_response()
        elif self.state == self.STATE_SEEK_TRADE:
            self._run_seek_trade()
        elif self.state == self.STATE_ENFORCE_TRIBUTE:
            self._run_enforce_tribute()
        elif self.state == self.STATE_FALLBACK_REBUILD:
            self._run_fallback_rebuild()
        else:
            self._run_attack()

        if self._scan_timer_s <= 0.0 and self.state != self.STATE_ATTACK:
            self._scan_timer_s = 3.6
            self._run_scan()

    def handle_gather(self, node: "ResourceNode", requested_amount: int) -> int:
        if node is None:
            return 0
        taken = self.game.resource_manager.drain_node(node, requested_amount)
        if taken <= 0:
            return 0
        key = node.resource_type
        if key not in self.resources:
            return 0
        cap_left = max(0, self.capacity.get(key, 999999) - self.resources.get(key, 0))
        if cap_left <= 0:
            return 0
        gained = min(cap_left, taken)
        got = self.game._kingdom_gain(self.civilization, key, gained)
        self.resources = dict(self.game._kingdom(self.civilization).capital_stockpile)
        return got

    def _run_expand(self) -> None:
        if self._expand_timer_s <= 0.0:
            self._expand_timer_s = 3.2
            self._attempt_expand_buildings()
        if self._gather_order_timer_s <= 0.0:
            self._gather_order_timer_s = 1.0
            self._order_workers_to_gather()
        if self._construction_order_timer_s <= 0.0:
            self._construction_order_timer_s = 0.78
            self._assign_idle_workers_to_sites()

    def _run_gather(self) -> None:
        if self._gather_order_timer_s <= 0.0:
            self._gather_order_timer_s = 0.95
            self._order_workers_to_gather()
        if self._construction_order_timer_s <= 0.0:
            self._construction_order_timer_s = 0.70
            self._assign_idle_workers_to_sites()

    def _run_stabilize(self) -> None:
        if self._gather_order_timer_s <= 0.0:
            self._gather_order_timer_s = 0.72
            self._order_workers_to_gather()
        if self._construction_order_timer_s <= 0.0:
            self._construction_order_timer_s = 0.52
            self._assign_idle_workers_to_sites()
        if self._expand_timer_s <= 0.0:
            self._expand_timer_s = 2.4
            self._attempt_expand_buildings()

    def _run_seek_trade(self) -> None:
        self._run_stabilize()
        if self._scan_timer_s <= 0.0:
            self._scan_timer_s = 3.0
            self._run_scan()

    def _run_enforce_tribute(self) -> None:
        self._run_stabilize()
        if self._attack_order_timer_s <= 0.0:
            self._attack_order_timer_s = 0.7
            target = self._select_attack_objective()
            if target is not None:
                for unit in self._attack_group_units():
                    unit.attack_command(
                        target,
                        pathfinder=self.game.pathfinder,
                        blocked_tiles=self.game._building_blocked_tiles,
                    )

    def _run_fallback_rebuild(self) -> None:
        self._run_stabilize()
        if self._expand_timer_s <= 0.0:
            self._expand_timer_s = 2.2
            self._attempt_expand_buildings()

    def _run_civil_war_response(self) -> None:
        self._run_stabilize()
        threats = self._enemy_units_near_base()
        if threats:
            self._defense_hold_s = max(self._defense_hold_s, 4.0)
            self._run_defend()
        rebel_id = self._rebel_target_id()
        if rebel_id:
            self._suppression_target = rebel_id
            if self._attack_order_timer_s <= 0.0:
                self._attack_order_timer_s = 0.72
                if self.game._should_broadcast_kingdom_state(self.civilization):
                    self.game._net_send(
                        {
                            "type": "suppression_order",
                            "civ": self.asset_color,
                            "kingdom_id": self.civilization,
                            "target_kingdom_id": rebel_id,
                        }
                    )
                self._issue_group_attack_on_kingdom(rebel_id, reserve_bias=2)

    def _run_naval_logistics(self) -> None:
        if self._expand_timer_s <= 0.0:
            self._expand_timer_s = 2.8
            if not self._docks():
                site = self._try_place_building(Building.TYPE_TOWER, pay_cost=True, prefer_water=True)
                if site is not None:
                    self._assign_workers_to_construction(site, max_workers=3)
            else:
                self._attempt_expand_buildings()
        if self._gather_order_timer_s <= 0.0:
            self._gather_order_timer_s = 0.9
            self._order_workers_to_gather()
        if self._construction_order_timer_s <= 0.0:
            self._construction_order_timer_s = 0.66
            self._assign_idle_workers_to_sites()
        if self._naval_order_timer_s <= 0.0:
            self._naval_order_timer_s = 1.35
            remote_node = self._remote_resource_node(self._preferred_resource_type())
            if remote_node is not None:
                self._run_resource_shipping(remote_node)
            else:
                self._run_naval_invasion()

    def _plan_state(self) -> None:
        civ = self.game._kingdom(self.civilization)
        food_days, gold_days = self._capital_stock_days(civ)
        reserve_ratio = self._reserve_ratio(civ)
        threat = self._threat_level_near_base()
        dip = self.game.diplomacy.assess_kingdom(self.game, self.civilization)
        war_targets = self.game.diplomacy.war_targets_for(self.civilization)
        scores = {
            self.STATE_EXPAND: 1.8,
            self.STATE_GATHER: 2.2,
            self.STATE_ATTACK: 0.6,
            self.STATE_STABILIZE: 0.0,
            self.STATE_NAVAL_LOGISTICS: 0.0,
            self.STATE_CIVIL_WAR_RESPONSE: 0.0,
            self.STATE_SEEK_TRADE: 0.0,
            self.STATE_ENFORCE_TRIBUTE: 0.0,
            self.STATE_FALLBACK_REBUILD: 0.0,
        }

        scores[self.STATE_GATHER] += max(0.0, 3.0 - min(food_days, gold_days)) * 0.55
        if reserve_ratio < 1.0:
            shortage = 1.0 - reserve_ratio
            scores[self.STATE_GATHER] += 2.8 + shortage * 3.2
            scores[self.STATE_STABILIZE] += 1.9 + shortage * 2.4
            scores[self.STATE_ATTACK] -= 1.6 + shortage * 3.5
        elif reserve_ratio > 1.28:
            scores[self.STATE_EXPAND] += 0.55
            scores[self.STATE_ATTACK] += 0.65
        if food_days < 3.5 or gold_days < 3.0:
            scores[self.STATE_STABILIZE] += 4.4
        if civ.stability < 55.0:
            scores[self.STATE_STABILIZE] += (55.0 - civ.stability) * 0.08
        if civ.stability < 36.0 or civ.loyalty < 42.0:
            scores[self.STATE_CIVIL_WAR_RESPONSE] += 4.8 + max(0.0, 42.0 - civ.loyalty) * 0.05
        if dip.suppress_rebels:
            scores[self.STATE_CIVIL_WAR_RESPONSE] += 4.2 + max(0.0, dip.pressure) * 0.05
        if dip.trade_partner and reserve_ratio < 1.12:
            scores[self.STATE_SEEK_TRADE] += 3.1
        if dip.tribute_target and reserve_ratio > 1.05:
            scores[self.STATE_ENFORCE_TRIBUTE] += 2.4
        if dip.capital_risk > 1.6 or self.game._capital_for_kingdom(self.civilization) is None:
            scores[self.STATE_FALLBACK_REBUILD] += 4.0 + dip.capital_risk * 0.8
        if threat > 0:
            scores[self.STATE_STABILIZE] += threat * 0.35
            if reserve_ratio < 1.1:
                scores[self.STATE_STABILIZE] += 0.8
        if self._needs_naval_logistics() or dip.naval_required:
            scores[self.STATE_NAVAL_LOGISTICS] += 3.2 if reserve_ratio >= 0.92 else 1.1
        if self._can_launch_attack() and war_targets:
            scores[self.STATE_ATTACK] += 2.8 + min(2.2, self._combat_count() * 0.18)
            if food_days >= 4.0 and gold_days >= 4.0:
                scores[self.STATE_ATTACK] += 1.0
        if len(self._workers()) < 4:
            scores[self.STATE_EXPAND] += 0.9
        if not self._docks() and self._needs_naval_logistics():
            scores[self.STATE_EXPAND] += 0.4
        if not war_targets:
            scores[self.STATE_ATTACK] -= 1.4
        scores[self._planned_state] = scores.get(self._planned_state, 0.0) + 0.3

        self._planned_state = max(scores.items(), key=lambda item: (item[1], item[0]))[0]

    def _run_attack(self) -> None:
        if not self._can_launch_attack():
            self._force_state(self.STATE_GATHER)
            return
        if self._attack_order_timer_s > 0.0:
            return
        self._attack_order_timer_s = 0.62

        attackers = self._attack_group_units()
        if len(attackers) < 4:
            self._force_state(self.STATE_GATHER)
            return

        rally_r2 = self._rally_radius * self._rally_radius
        ready = [
            u
            for u in attackers
            if (u.world_pos.x - self._rally_world[0]) ** 2 + (u.world_pos.y - self._rally_world[1]) ** 2 <= rally_r2
        ]
        ready_need = max(3, int(len(attackers) * 0.6))
        if len(ready) < ready_need:
            for unit in attackers:
                d2 = (unit.world_pos.x - self._rally_world[0]) ** 2 + (unit.world_pos.y - self._rally_world[1]) ** 2
                if d2 <= rally_r2:
                    continue
                jitter = ((unit.uid % 7) - 3) * TILE_SIZE * 0.18
                unit.move_to(
                    self._rally_world[0] + jitter,
                    self._rally_world[1] - jitter * 0.45,
                    pathfinder=self.game.pathfinder,
                    blocked_tiles=self.game._building_blocked_tiles,
                )
            return

        target = self._select_attack_objective()
        if target is None:
            self._force_state(self.STATE_GATHER)
            return
        if not self._path_exists(self._rally_world, (target.world_pos.x, target.world_pos.y)):
            self._force_state(self.STATE_NAVAL_LOGISTICS)
            self._run_naval_invasion()
            return

        if isinstance(target, Unit):
            for unit in attackers:
                if unit.attack_target is target and not target.is_dead:
                    continue
                unit.attack_command(
                    target,
                    pathfinder=self.game.pathfinder,
                    blocked_tiles=self.game._building_blocked_tiles,
                )
            return

        tx, ty = target.world_pos.x, target.world_pos.y

        for i, unit in enumerate(attackers):
            off_x = ((i % 3) - 1) * TILE_SIZE * 0.34
            off_y = (i // 3) * TILE_SIZE * 0.28
            unit.move_to(
                tx + off_x,
                ty + off_y,
                pathfinder=self.game.pathfinder,
                blocked_tiles=self.game._building_blocked_tiles,
            )

    def _run_defend(self) -> None:
        if self._gather_order_timer_s <= 0.0:
            self._gather_order_timer_s = 0.72
            self._order_workers_to_gather()
        if self._construction_order_timer_s <= 0.0:
            self._construction_order_timer_s = 0.52
            self._assign_idle_workers_to_sites()

        threats = self._enemy_units_near_base()
        defenders = [
            u
            for u in self.game.units
            if u.kingdom_id == self.civilization and not u.is_dead and u.can_attack and not u.can_gather
        ]

        if threats and defenders and self._attack_order_timer_s <= 0.0:
            self._attack_order_timer_s = 0.46
            target = min(
                threats,
                key=lambda u: (u.world_pos.x - self._base_world[0]) ** 2 + (u.world_pos.y - self._base_world[1]) ** 2,
            )
            for unit in defenders:
                if unit.attack_target is target and not target.is_dead:
                    continue
                unit.attack_command(
                    target,
                    pathfinder=self.game.pathfinder,
                    blocked_tiles=self.game._building_blocked_tiles,
                )

        if self._expand_timer_s <= 0.0:
            self._expand_timer_s = 2.6
            if len(threats) >= 3:
                site = self._try_place_building(Building.TYPE_TOWER, pay_cost=True)
                if site is not None:
                    self._assign_workers_to_construction(site, max_workers=3)
            self._attempt_expand_buildings()

    def _run_scan(self) -> None:
        scouts = [
            u
            for u in self.game.units
            if u.kingdom_id == self.civilization and not u.is_dead and not u.can_gather
        ]
        if not scouts or not self._scan_points:
            return
        point = self._scan_points[self._scan_index % len(self._scan_points)]
        self._scan_index += 1
        scout = min(
            scouts,
            key=lambda u: (u.world_pos.x - point[0]) ** 2 + (u.world_pos.y - point[1]) ** 2,
        )
        scout.move_to(
            point[0],
            point[1],
            pathfinder=self.game.pathfinder,
            blocked_tiles=self.game._building_blocked_tiles,
        )

    def _advance_state_if_ready(self) -> None:
        duration = self._STATE_DURATION[self.state]
        if self._state_timer_s < duration:
            return

        next_index = (self._state_index + 1) % len(self._STATE_CYCLE)
        next_state = self._STATE_CYCLE[next_index]
        if next_state == self.STATE_ATTACK and not self._can_launch_attack():
            next_state = self.STATE_GATHER
            next_index = self._STATE_CYCLE.index(next_state)

        self._state_index = next_index
        self._state_timer_s = 0.0

    def _force_state(self, state: str) -> None:
        if state in (
            self.STATE_STABILIZE,
            self.STATE_NAVAL_LOGISTICS,
            self.STATE_CIVIL_WAR_RESPONSE,
        ):
            self._planned_state = state
            self._state_timer_s = 0.0
            return
        if state not in self._STATE_CYCLE:
            return
        self._state_index = self._STATE_CYCLE.index(state)
        self._planned_state = state
        self._state_timer_s = 0.0

    def _can_launch_attack(self) -> bool:
        if self._elapsed_s < self._attack_unlock_s:
            return False
        if not self.game.diplomacy.war_targets_for(self.civilization):
            return False
        civ = self.game._kingdom(self.civilization)
        food_days, gold_days = self._capital_stock_days(civ)
        reserve_ratio = self._reserve_ratio(civ)
        if civ.stability < 48.0 or civ.loyalty < 45.0:
            return False
        if food_days < 2.6 or gold_days < 2.2:
            return False
        combat_count = self._combat_count()
        if reserve_ratio < 1.05:
            return False
        if combat_count < 5:
            return False
        if combat_count <= self._defender_reserve_target() + 3:
            return False
        has_military = any(
            b.kingdom_id == self.civilization
            and b.is_complete
            and b.building_type in (Building.TYPE_BARRACKS, Building.TYPE_ARCHERY, Building.TYPE_CASTLE)
            for b in self.game.buildings
        )
        return has_military

    def _reserve_targets(self, civ) -> dict[str, int]:
        workers = sum(1 for unit in civ.units if (not unit.is_dead and unit.can_gather))
        combat = sum(1 for unit in civ.units if (not unit.is_dead and unit.can_attack and not unit.can_gather))
        buildings = sum(1 for building in civ.buildings if not building.is_dead)
        time_phase = int(self._elapsed_s // 120.0)
        return {
            "gold": 420 + combat * 48 + workers * 16 + buildings * 12 + time_phase * 90,
            "wood": 360 + workers * 18 + buildings * 22 + time_phase * 80,
            "stone": 240 + buildings * 24 + combat * 8 + time_phase * 50,
            "food": 220 + combat * 22 + workers * 10 + time_phase * 45,
        }

    def _reserve_ratio(self, civ) -> float:
        targets = self._reserve_targets(civ)
        ratios = []
        for key, target in targets.items():
            current = civ.capital_stockpile.get(key, 0)
            if key == "food":
                current += civ.capital_stockpile.get("meat", 0)
            ratios.append(current / max(1, target))
        return min(ratios) if ratios else 1.0

    def _defender_reserve_target(self) -> int:
        combat = self._combat_count()
        if combat <= 0:
            return 0
        threat = self._threat_level_near_base()
        reserve = max(2, threat, combat // 4)
        return min(reserve, max(0, combat - 3))

    def _attack_group_units(self) -> list[Unit]:
        combatants = [
            u
            for u in self.game.units
            if u.kingdom_id == self.civilization and not u.is_dead and u.can_attack and not u.can_gather
        ]
        if not combatants:
            return []
        base_x, base_y = self._capital_world()
        combatants.sort(
            key=lambda u: (u.world_pos.x - base_x) ** 2 + (u.world_pos.y - base_y) ** 2,
            reverse=True,
        )
        reserve = self._defender_reserve_target()
        if reserve <= 0:
            return combatants
        return combatants[: max(0, len(combatants) - reserve)]

    def _capital_stock_days(self, civ) -> tuple[float, float]:
        combat = sum(1 for unit in civ.units if (not unit.is_dead and unit.can_attack and not unit.can_gather))
        food_total = civ.capital_stockpile.get("food", 0) + civ.capital_stockpile.get("meat", 0)
        gold_total = civ.capital_stockpile.get("gold", 0)
        food_days = food_total / max(1.0, combat * 1.2 + 1.0)
        gold_days = gold_total / max(1.0, combat * 2.3 + 1.0)
        return food_days, gold_days

    def _capital_world(self) -> tuple[float, float]:
        capital = self.game._capital_for_kingdom(self.civilization)
        if capital is not None:
            return capital.spawn_anchor()
        return self._base_world

    def _docks(self) -> list[Building]:
        return [
            b
            for b in self.game.buildings
            if (
                b.kingdom_id == self.civilization
                and not b.is_dead
                and b.is_complete
                and b.building_type == Building.TYPE_TOWER
                and b.is_dock
            )
        ]

    def _ships(self) -> list[Ship]:
        return [ship for ship in self.game.ships if ship.kingdom_id == self.civilization]

    def _nearest_enemy_castle(self) -> Building | None:
        war_targets = set(self.game.diplomacy.war_targets_for(self.civilization))
        if not war_targets:
            return None
        castles = [
            b
            for b in self.game.buildings
            if (
                b.kingdom_id in war_targets
                and not b.is_dead
                and b.is_complete
                and b.building_type == Building.TYPE_CASTLE
            )
        ]
        if not castles:
            return None
        return min(
            castles,
            key=lambda b: (b.world_pos.x - self._base_world[0]) ** 2 + (b.world_pos.y - self._base_world[1]) ** 2,
        )

    def _path_exists(self, start: tuple[float, float], target: tuple[float, float]) -> bool:
        sc = self.game.tilemap.world_to_tile(start[0], start[1])
        tc = self.game.tilemap.world_to_tile(target[0], target[1])
        key = (sc, tc)
        cached = self._path_cache.get(key)
        if cached is not None and self._elapsed_s - cached[1] < 6.0:
            return cached[0]
        points = self.game.pathfinder.find_path_world(
            start,
            target,
            blocked=self.game._building_blocked_tiles,
            max_expansions=5200,
        )
        result = bool(points)
        self._path_cache[key] = (result, self._elapsed_s)
        return result

    def _resource_candidates(self, resource_type: str, *, limit: int = 10) -> list[ResourceNode]:
        nodes = [
            node
            for node in self.game.resource_manager.nodes
            if (not node.is_depleted and node.resource_type == resource_type)
        ]
        nodes.sort(key=lambda node: (node.wx - self._base_world[0]) ** 2 + (node.wy - self._base_world[1]) ** 2)
        return nodes[:limit]

    def _remote_resource_node(self, resource_type: str) -> ResourceNode | None:
        cached = self._resource_cache.get(resource_type)
        if cached is not None and self._elapsed_s - cached[1] < 4.0:
            node = cached[0]
            if node is None or getattr(node, "is_depleted", False):
                return None
            return node
        origin = self._capital_world()
        for node in self._resource_candidates(resource_type):
            if self._path_exists(origin, (node.wx, node.wy)):
                continue
            if self.game._nearest_water_world(node.wx, node.wy, max_radius=8) is None:
                continue
            self._resource_cache[resource_type] = (node, self._elapsed_s)
            return node
        self._resource_cache[resource_type] = (None, self._elapsed_s)
        return None

    def _needs_naval_logistics(self) -> bool:
        origin = self._capital_world()
        target_castle = self._nearest_enemy_castle()
        if target_castle is not None and not self._path_exists(origin, (target_castle.world_pos.x, target_castle.world_pos.y)):
            return True
        return self._remote_resource_node(self._preferred_resource_type()) is not None

    def _rebel_target_id(self) -> str:
        assessment = self.game.diplomacy.assess_kingdom(self.game, self.civilization)
        return assessment.rebel_target

    def _tribute_target_id(self) -> str:
        assessment = self.game.diplomacy.assess_kingdom(self.game, self.civilization)
        return assessment.tribute_target

    def _issue_group_attack_on_kingdom(self, kingdom_id: str, *, reserve_bias: int = 0) -> None:
        target = self._target_object_for_kingdom(kingdom_id)
        if target is None:
            return
        attackers = self._attack_group_units()
        if reserve_bias > 0 and len(attackers) > reserve_bias + 2:
            attackers = attackers[:-reserve_bias]
        for unit in attackers:
            unit.attack_command(
                target,
                pathfinder=self.game.pathfinder,
                blocked_tiles=self.game._building_blocked_tiles,
            )

    def _target_object_for_kingdom(self, kingdom_id: str):
        enemy_buildings = [
            b
            for b in self.game.buildings
            if b.kingdom_id == kingdom_id and not b.is_dead and not b.under_construction
        ]
        high_value = [
            b
            for b in enemy_buildings
            if b.building_type in (Building.TYPE_CASTLE, Building.TYPE_BARRACKS, Building.TYPE_ARCHERY)
        ]
        if high_value:
            return min(
                high_value,
                key=lambda b: (b.world_pos.x - self._rally_world[0]) ** 2 + (b.world_pos.y - self._rally_world[1]) ** 2,
            )
        enemy_units = [
            u
            for u in self.game.units
            if u.kingdom_id == kingdom_id and not u.is_dead and u.can_attack
        ]
        if enemy_units:
            return min(
                enemy_units,
                key=lambda u: (u.world_pos.x - self._rally_world[0]) ** 2 + (u.world_pos.y - self._rally_world[1]) ** 2,
            )
        if enemy_buildings:
            return min(
                enemy_buildings,
                key=lambda b: (b.world_pos.x - self._rally_world[0]) ** 2 + (b.world_pos.y - self._rally_world[1]) ** 2,
            )
        return None

    def _run_resource_shipping(self, node: ResourceNode) -> None:
        docks = self._docks()
        ships = self._ships()
        if not docks or not ships:
            return
        home_anchor = self._capital_world()
        home_water = self.game._nearest_water_world(home_anchor[0], home_anchor[1], max_radius=10)
        target_water = self.game._nearest_water_world(node.wx, node.wy, max_radius=8)
        if home_water is None or target_water is None:
            return

        ship = min(
            ships,
            key=lambda s: (
                s.cargo_used == 0,
                (s.world_pos.x - home_water[0]) ** 2 + (s.world_pos.y - home_water[1]) ** 2,
            ),
        )
        remote_workers = [
            worker
            for worker in self._workers()
            if (worker.world_pos.x - node.wx) ** 2 + (worker.world_pos.y - node.wy) ** 2 <= (TILE_SIZE * 8.5) ** 2
        ]

        if ship.cargo_used > 0:
            if ship.passenger_count > 0:
                ship.request_unload(home_anchor[0], home_anchor[1])
            ship.move_to(home_water[0], home_water[1], pathfinder=self.game.pathfinder, blocked_tiles=self.game._building_blocked_tiles)
            return

        if ship.passenger_count > 0 and not ship._boarding_queue:
            ship.move_to(
                target_water[0],
                target_water[1],
                pathfinder=self.game.pathfinder,
                blocked_tiles=self.game._building_blocked_tiles,
            )
            ship.request_unload(node.wx, node.wy)
            return

        if remote_workers and (ship.world_pos.x - target_water[0]) ** 2 + (ship.world_pos.y - target_water[1]) ** 2 <= (TILE_SIZE * 3.2) ** 2:
            return

        if ship.passenger_count == 0 and not ship._boarding_queue:
            if (ship.world_pos.x - home_water[0]) ** 2 + (ship.world_pos.y - home_water[1]) ** 2 > (TILE_SIZE * 2.4) ** 2:
                ship.move_to(
                    home_water[0],
                    home_water[1],
                    pathfinder=self.game.pathfinder,
                    blocked_tiles=self.game._building_blocked_tiles,
                )
                return
            workers = sorted(
                self._workers(),
                key=lambda w: (w.world_pos.x - home_anchor[0]) ** 2 + (w.world_pos.y - home_anchor[1]) ** 2,
            )[:2]
            for worker in workers:
                ship.request_board(
                    worker,
                    pathfinder=self.game.pathfinder,
                    blocked_tiles=self.game._building_blocked_tiles,
                )

    def _run_naval_invasion(self) -> None:
        assessment = self.game.diplomacy.assess_kingdom(self.game, self.civilization)
        target_id = assessment.best_enemy or self._rebel_target_id()
        if not target_id:
            return
        target = self._target_object_for_kingdom(target_id)
        if target is None:
            return
        home_anchor = self._capital_world()
        if self._path_exists(home_anchor, (target.world_pos.x, target.world_pos.y)):
            return
        docks = self._docks()
        ships = self._ships()
        if not docks or not ships:
            return
        home_water = self.game._nearest_water_world(home_anchor[0], home_anchor[1], max_radius=10)
        target_water = self.game._nearest_water_world(target.world_pos.x, target.world_pos.y, max_radius=8)
        if home_water is None or target_water is None:
            return
        attack_group = sorted(
            self._attack_group_units(),
            key=lambda u: (u.world_pos.x - home_anchor[0]) ** 2 + (u.world_pos.y - home_anchor[1]) ** 2,
        )
        ships = sorted(
            ships,
            key=lambda s: (s.world_pos.x - home_water[0]) ** 2 + (s.world_pos.y - home_water[1]) ** 2,
        )
        self._naval_target_kingdom = target_id
        for idx, ship in enumerate(ships[:2]):
            if ship.passenger_count > 0 and not ship._boarding_queue:
                ship.move_to(
                    target_water[0],
                    target_water[1],
                    pathfinder=self.game.pathfinder,
                    blocked_tiles=self.game._building_blocked_tiles,
                )
                ship.request_unload(target.world_pos.x, target.world_pos.y)
                continue
            if ship.passenger_count == 0 and not ship._boarding_queue:
                if (ship.world_pos.x - home_water[0]) ** 2 + (ship.world_pos.y - home_water[1]) ** 2 > (TILE_SIZE * 2.4) ** 2:
                    ship.move_to(
                        home_water[0],
                        home_water[1],
                        pathfinder=self.game.pathfinder,
                        blocked_tiles=self.game._building_blocked_tiles,
                    )
                    continue
                batch = attack_group[idx * Ship.CAPACITY : (idx + 1) * Ship.CAPACITY]
                for attacker in batch:
                    ship.request_board(
                        attacker,
                        pathfinder=self.game.pathfinder,
                        blocked_tiles=self.game._building_blocked_tiles,
                    )
        if self.game._should_broadcast_kingdom_state(self.civilization):
            self.game._net_send(
                {
                    "type": "naval_task",
                    "civ": self.asset_color,
                    "kingdom_id": self.civilization,
                    "target_kingdom_id": target_id,
                    "task": "launch_naval_invasion",
                }
            )

    def _enemy_units_near_base(self) -> list[Unit]:
        radius2 = self._threat_radius * self._threat_radius
        out: list[Unit] = []
        war_targets = set(self.game.diplomacy.war_targets_for(self.civilization))
        for unit in self.game.units:
            if unit.is_dead or unit.kingdom_id == self.civilization:
                continue
            if not unit.asset_color.startswith(("Orc", "Slime")) and unit.kingdom_id not in war_targets:
                continue
            d2 = (unit.world_pos.x - self._base_world[0]) ** 2 + (unit.world_pos.y - self._base_world[1]) ** 2
            if d2 <= radius2:
                out.append(unit)
        return out

    def _threat_level_near_base(self) -> int:
        threats = self._enemy_units_near_base()
        score = 0
        for unit in threats:
            score += 2 if unit.can_attack else 1
        return score

    def _select_attack_objective(self):
        war_targets = set(self.game.diplomacy.war_targets_for(self.civilization))
        if self._attack_target is not None and self._attack_target_refresh_s > 0.0:
            if isinstance(self._attack_target, Unit):
                if (
                    not self._attack_target.is_dead
                    and self._attack_target.kingdom_id != self.civilization
                    and self._attack_target.kingdom_id in war_targets
                ):
                    return self._attack_target
            elif isinstance(self._attack_target, Building):
                if (
                    not self._attack_target.is_dead
                    and self._attack_target.kingdom_id != self.civilization
                    and self._attack_target.kingdom_id in war_targets
                ):
                    return self._attack_target

        self._attack_target_refresh_s = 2.8
        if not war_targets:
            tribute_target = self._tribute_target_id()
            if tribute_target:
                war_targets.add(tribute_target)
        if not war_targets:
            rebel_target = self._rebel_target_id()
            if rebel_target:
                war_targets.add(rebel_target)
        enemy_units = [
            u
            for u in self.game.units
            if u.kingdom_id in war_targets and not u.is_dead
        ]
        enemy_buildings = [
            b
            for b in self.game.buildings
            if b.kingdom_id in war_targets and not b.is_dead and not b.under_construction
        ]

        # Priority: player combat units near front -> production buildings -> castles -> any enemy unit.
        front_x, front_y = self._rally_world
        if enemy_units:
            combat_units = [u for u in enemy_units if u.can_attack]
            if combat_units:
                self._attack_target = min(
                    combat_units,
                    key=lambda u: (u.world_pos.x - front_x) ** 2 + (u.world_pos.y - front_y) ** 2,
                )
                return self._attack_target

        high_value = [
            b
            for b in enemy_buildings
            if b.building_type in (Building.TYPE_BARRACKS, Building.TYPE_ARCHERY, Building.TYPE_CASTLE)
        ]
        if high_value:
            self._attack_target = min(
                high_value,
                key=lambda b: (b.world_pos.x - front_x) ** 2 + (b.world_pos.y - front_y) ** 2,
            )
            return self._attack_target

        if enemy_buildings:
            self._attack_target = min(
                enemy_buildings,
                key=lambda b: (b.world_pos.x - front_x) ** 2 + (b.world_pos.y - front_y) ** 2,
            )
            return self._attack_target

        if enemy_units:
            self._attack_target = min(
                enemy_units,
                key=lambda u: (u.world_pos.x - front_x) ** 2 + (u.world_pos.y - front_y) ** 2,
            )
            return self._attack_target

        self._attack_target = None
        return None

    def _attempt_expand_buildings(self) -> None:
        threat = self._threat_level_near_base()
        combat = self._combat_count()
        workers = len(self._workers())
        elapsed = self._elapsed_s
        civ = self.game._kingdom(self.civilization)
        reserve_ratio = self._reserve_ratio(civ)
        need_naval = self._needs_naval_logistics()
        desired = {
            Building.TYPE_HOUSE1: 2 if workers >= 6 else 1,
            Building.TYPE_HOUSE2: 2 if elapsed > 100 else 1,
            Building.TYPE_HOUSE3: 2 if elapsed > 170 else 1,
            Building.TYPE_BARRACKS: 1 + int(elapsed > 110) + int(combat > 14),
            Building.TYPE_ARCHERY: 1 + int(elapsed > 95) + int(combat > 12),
            Building.TYPE_TOWER: 1 + int(threat >= 2) + int(elapsed > 220) + int(need_naval),
            Building.TYPE_SMITHY: 1 if elapsed > 120 else 0,
            Building.TYPE_CASTLE: 1 if elapsed > 210 else 0,
        }
        if reserve_ratio < 0.95:
            desired[Building.TYPE_ARCHERY] = min(desired[Building.TYPE_ARCHERY], 1)
            desired[Building.TYPE_BARRACKS] = min(desired[Building.TYPE_BARRACKS], 1)
            desired[Building.TYPE_SMITHY] = 0
            desired[Building.TYPE_CASTLE] = 0
        elif reserve_ratio > 1.35:
            desired[Building.TYPE_HOUSE3] += 1
            desired[Building.TYPE_TOWER] += int(need_naval)
        if civ.stability < 52.0:
            desired[Building.TYPE_HOUSE1] = max(desired[Building.TYPE_HOUSE1], 2)
            desired[Building.TYPE_HOUSE2] = max(desired[Building.TYPE_HOUSE2], 1)
        for building_type, _ in self._BUILD_PLAN:
            wanted_count = desired.get(building_type, 1)
            if wanted_count <= 0:
                continue
            have = sum(
                1
                for b in self.game.buildings
                if b.kingdom_id == self.civilization and b.building_type == building_type
            )
            if have >= wanted_count:
                continue
            site = self._try_place_building(
                building_type,
                pay_cost=True,
                prefer_water=(building_type == Building.TYPE_TOWER and need_naval and not self._docks()),
            )
            if site is not None:
                self._assign_workers_to_construction(site, max_workers=4 if threat >= 2 else 3)
            break

    def _queue_production(self) -> None:
        civ = self.game._kingdom(self.civilization)
        reserve_ratio = self._reserve_ratio(civ)
        producers = [
            b
            for b in self.game.buildings
            if b.kingdom_id == self.civilization and b.can_produce and b.is_complete
        ]
        if not producers:
            return

        counts = self._unit_counts()
        enemy_counts = self._enemy_unit_counts()
        for building in producers:
            if (
                reserve_ratio < 0.88
                and self.state not in (self.STATE_DEFEND, self.STATE_ATTACK, self.STATE_CIVIL_WAR_RESPONSE)
                and building.building_type in (Building.TYPE_BARRACKS, Building.TYPE_ARCHERY, Building.TYPE_CASTLE)
                and self._combat_count() >= max(5, self._defender_reserve_target() + 2)
            ):
                continue
            queue_target = building.max_queue - 1 if self.state in (self.STATE_ATTACK, self.STATE_DEFEND) else max(2, building.max_queue - 2)
            if reserve_ratio < 1.0 and building.building_type in (Building.TYPE_BARRACKS, Building.TYPE_ARCHERY, Building.TYPE_CASTLE):
                queue_target = min(queue_target, 1)
            while building.queue_size < queue_target:
                option = self._choose_production_option(building, counts, enemy_counts)
                if option is None:
                    break

                costs = {
                    "gold": int(option.get("gold_cost", 0)),
                    "wood": int(option.get("wood_cost", 0)),
                    "stone": int(option.get("stone_cost", 0)),
                }
                if not self._can_afford(costs):
                    break
                if not building.enqueue_option(option):
                    break
                self._spend(costs)
                unit_class = str(option.get("unit_class", ""))
                if unit_class:
                    counts[unit_class] = counts.get(unit_class, 0) + 1

    def _choose_production_option(
        self,
        building: Building,
        counts: dict[str, int],
        enemy_counts: dict[str, int],
    ) -> dict[str, str | int | float] | None:
        options = building.production_options()
        if not options:
            return None

        our_war = counts.get(Unit.ROLE_WARRIOR, 0)
        our_arc = counts.get(Unit.ROLE_ARCHER, 0)
        our_lan = counts.get(Unit.ROLE_LANCER, 0)
        enemy_melee = (
            enemy_counts.get(Unit.ROLE_WARRIOR, 0)
            + enemy_counts.get(Unit.ROLE_LANCER, 0)
            + enemy_counts.get(Unit.ROLE_HERO, 0)
        )
        enemy_range = enemy_counts.get(Unit.ROLE_ARCHER, 0)
        builders = sum(1 for unit in self.game.units if unit.kingdom_id == self.civilization and not unit.is_dead and unit.can_construct)
        need_naval = self._needs_naval_logistics()

        if building.building_type == Building.TYPE_BARRACKS:
            # If enemy has heavier ranged presence, close-distance lancer pressure is stronger.
            if enemy_range > enemy_melee + 1:
                return self._find_unit_option(options, Unit.ROLE_LANCER) or self._find_unit_option(
                    options, Unit.ROLE_WARRIOR
                )
            # Keep early melee core online to absorb pressure.
            if our_war < 8:
                return self._find_unit_option(options, Unit.ROLE_WARRIOR)
            if self.state in (self.STATE_ATTACK, self.STATE_DEFEND):
                if our_lan < max(6, enemy_range):
                    return self._find_unit_option(options, Unit.ROLE_LANCER) or self._find_unit_option(
                        options, Unit.ROLE_WARRIOR
                    )
            if our_lan < max(4, enemy_range // 2):
                return self._find_unit_option(options, Unit.ROLE_LANCER) or self._find_unit_option(
                    options, Unit.ROLE_WARRIOR
                )
            return self._find_unit_option(options, Unit.ROLE_WARRIOR)

        if building.building_type == Building.TYPE_ARCHERY:
            desired_archers = max(6, enemy_melee + max(0, our_war // 2))
            if self.state in (self.STATE_ATTACK, self.STATE_DEFEND) or our_arc < desired_archers:
                return self._find_unit_option(options, Unit.ROLE_ARCHER)
            return None

        if building.building_type == Building.TYPE_CASTLE:
            if self.state in (self.STATE_ATTACK, self.STATE_DEFEND) or self._combat_count() > 7:
                return self._find_unit_option(options, Unit.ROLE_LANCER)
            return None

        if building.building_type == Building.TYPE_SMITHY:
            if builders < 3 or self.state in (self.STATE_STABILIZE, self.STATE_CIVIL_WAR_RESPONSE):
                return self._find_unit_option(options, Unit.ROLE_MONK)
            return None

        if building.building_type == Building.TYPE_TOWER and building.is_dock:
            if need_naval and len(self._ships()) < max(1, len(self._docks())):
                for option in options:
                    if str(option.get("kind", "")) == "ship":
                        return option
            return None

        return None

    @staticmethod
    def _find_unit_option(
        options: list[dict[str, str | int | float]],
        unit_class: str,
    ) -> dict[str, str | int | float] | None:
        for option in options:
            if str(option.get("kind", "unit")) != "unit":
                continue
            if str(option.get("unit_class", "")) == unit_class:
                return option
        return None

    def _order_workers_to_gather(self) -> None:
        workers = self._workers()
        if not workers:
            return

        priorities = self._resource_priority_list()
        for idx, worker in enumerate(workers):
            if worker.build_target is not None and not worker.build_target.is_complete:
                continue
            if worker.gather_target is not None and not worker.gather_target.is_depleted:
                continue
            node = None
            # Spread workers across first 2 priorities to avoid single-resource lock.
            ordered = priorities[:]
            if len(ordered) >= 2 and idx % 2 == 1:
                ordered[0], ordered[1] = ordered[1], ordered[0]
            for preferred in ordered:
                node = self._nearest_reachable_resource(preferred, worker.world_pos.x, worker.world_pos.y)
                if node is not None:
                    break
            if node is None:
                node = self._nearest_any_resource(worker.world_pos.x, worker.world_pos.y)
            if node is None:
                continue
            worker.gather(
                node,
                pathfinder=self.game.pathfinder,
                blocked_tiles=self.game._building_blocked_tiles,
            )

    def _preferred_resource_type(self) -> str:
        return self._resource_priority_list(include_naval_bias=False)[0]

    def _resource_priority_list(self, *, include_naval_bias: bool = True) -> list[str]:
        targets = self._reserve_targets(self.game._kingdom(self.civilization))
        if not any(
            b.kingdom_id == self.civilization and b.building_type == Building.TYPE_BARRACKS
            for b in self.game.buildings
        ):
            targets["wood"] += 240
            targets["stone"] += 120
        if self.state in (self.STATE_STABILIZE, self.STATE_CIVIL_WAR_RESPONSE):
            targets["food"] += 120
            targets["gold"] += 110
        if include_naval_bias and self._needs_naval_logistics():
            targets["wood"] += 140
            targets["stone"] += 80
        scored: list[tuple[float, str]] = []
        for key, target in targets.items():
            have = self.resources.get(key, 0)
            if key == "food":
                have += self.resources.get("meat", 0)
            score = have / max(1, target)
            scored.append((score, key))
        scored.sort(key=lambda x: x[0])
        return [key for _, key in scored]

    def _nearest_reachable_resource(self, resource_type: str, wx: float, wy: float) -> ResourceNode | None:
        nodes = [
            node
            for node in self.game.resource_manager.nodes
            if (not node.is_depleted and node.resource_type == resource_type)
        ]
        nodes.sort(key=lambda node: (node.wx - wx) ** 2 + (node.wy - wy) ** 2)
        for node in nodes[:8]:
            if self._path_exists((wx, wy), (node.wx, node.wy)):
                return node
        return None

    def _nearest_any_resource(self, wx: float, wy: float) -> ResourceNode | None:
        best = None
        best_d2 = 10e12
        for node in self.game.resource_manager.nodes:
            if node.is_depleted:
                continue
            if node.resource_type not in ("gold", "wood", "stone", "food", "meat"):
                continue
            if not self._path_exists((wx, wy), (node.wx, node.wy)):
                continue
            dx = node.wx - wx
            dy = node.wy - wy
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best = node
                best_d2 = d2
        return best

    def _try_place_building(self, building_type: str, *, pay_cost: bool, prefer_water: bool = False) -> Building | None:
        costs = Building.build_cost(building_type)
        if pay_cost and not self._can_afford(costs):
            return None

        anchor = self._find_anchor_for_building(building_type, prefer_water=prefer_water)
        if anchor is None:
            return None

        if pay_cost:
            self._spend(costs)

        bx, by = self.game.tilemap.tile_center(anchor[0], anchor[1])
        b = Building(
            bx,
            by,
            building_type=building_type,
            civilization=self.asset_color,
            kingdom_id=self.civilization,
            max_hp=self.game._max_hp_for_building(building_type),
            start_progress=0.05,
        )
        if b.building_type == Building.TYPE_TOWER:
            b.is_dock = self.game._building_touches_water(b.footprint_tiles(self.game.tilemap))
        self.game.buildings.append(b)
        self.game._refresh_building_masks()
        return b

    def _find_anchor_for_building(self, building_type: str, *, prefer_water: bool = False) -> tuple[int, int] | None:
        bc, br = self._base_tile
        max_radius = 34 if prefer_water else 22
        for radius in range(2, max_radius):
            ring: list[tuple[int, int]] = []
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if abs(dc) != radius and abs(dr) != radius:
                        continue
                    c = bc + dc
                    r = br + dr
                    if not (0 <= c < self.game.tilemap.cols and 0 <= r < self.game.tilemap.rows):
                        continue
                    ring.append((c, r))
            self._rng.shuffle(ring)
            for anchor in ring:
                footprint = self.game._candidate_footprint(anchor, building_type)
                if not self.game._is_placement_valid(footprint):
                    continue
                if prefer_water and not self.game._building_touches_water(footprint):
                    continue
                return anchor
        return None

    def _assign_idle_workers_to_sites(self) -> None:
        sites = [
            b
            for b in self.game.buildings
            if b.kingdom_id == self.civilization and b.under_construction
        ]
        if not sites:
            return
        sites.sort(key=lambda s: s.build_progress)
        workers = [
            w
            for w in self._builders()
            if (w.build_target is None or w.build_target.is_complete)
        ]
        if not workers:
            return
        self._assign_workers_to_construction(sites[0], max_workers=min(5, len(workers)))

    def _assign_workers_to_construction(self, building: Building, *, max_workers: int) -> None:
        if building.is_complete or max_workers <= 0:
            return
        workers = [
            w
            for w in self._builders()
            if (
                w.build_target is None
                or w.build_target.is_complete
                or w.build_target is building
            )
        ]
        if not workers:
            return
        workers.sort(
            key=lambda w: (w.world_pos.x - building.world_pos.x) ** 2 + (w.world_pos.y - building.world_pos.y) ** 2
        )
        points = self.game._construction_positions(building)
        if not points:
            points = [building.spawn_anchor()]
        assigned = 0
        for worker in workers:
            if assigned >= max_workers:
                break
            if worker.build_target is building:
                assigned += 1
                continue
            i = assigned
            px, py = points[i % len(points)]
            worker.construct(
                building,
                approach_pos=(px, py),
                pathfinder=self.game.pathfinder,
                blocked_tiles=self.game._building_blocked_tiles,
            )
            assigned += 1

    def _spawn_initial_force(self) -> None:
        bx, by = self._base_world
        self.game.units.append(
            Unit(bx, by - 16, civilization=self.asset_color, kingdom_id=self.civilization, unit_class=Unit.ROLE_HERO)
        )
        mx, my = self.game._find_spawn_world_near(bx + 38, by + 64)
        self.game.units.append(
            Unit(mx, my, civilization=self.asset_color, kingdom_id=self.civilization, unit_class=Unit.ROLE_MONK)
        )
        formation = [
            (92, 0),
            (-92, 0),
            (0, 94),
            (0, -94),
            (74, 74),
            (-74, 74),
            (74, -74),
        ]
        for dx, dy in formation:
            wx, wy = self.game._find_spawn_world_near(bx + dx, by + dy + 22)
            self.game.units.append(
                Unit(
                    wx,
                    wy,
                    civilization=self.asset_color,
                    kingdom_id=self.civilization,
                    unit_class=Unit.ROLE_WORKER,
                )
            )

    def _workers(self) -> list[Unit]:
        return [
            u
            for u in self.game.units
            if u.kingdom_id == self.civilization and not u.is_dead and u.can_gather
        ]

    def _builders(self) -> list[Unit]:
        return [
            u
            for u in self.game.units
            if u.kingdom_id == self.civilization and not u.is_dead and u.can_construct
        ]

    def _pick_opposite_corner_tile(self) -> tuple[int, int]:
        corners = [
            (2, 2),
            (self.game.tilemap.cols - 3, 2),
            (2, self.game.tilemap.rows - 3),
            (self.game.tilemap.cols - 3, self.game.tilemap.rows - 3),
        ]
        sx, sy = self.game._spawn_world
        best = corners[0]
        best_d2 = -1.0
        for c, r in corners:
            wx, wy = self.game.tilemap.tile_center(c, r)
            d2 = (wx - sx) * (wx - sx) + (wy - sy) * (wy - sy)
            if d2 > best_d2:
                best_d2 = d2
                best = (c, r)
        return best

    def _build_scan_points(self) -> list[tuple[float, float]]:
        cols = self.game.tilemap.cols
        rows = self.game.tilemap.rows
        tile_points = [
            (2, 2),
            (cols // 2, 2),
            (cols - 3, 2),
            (cols - 3, rows // 2),
            (cols - 3, rows - 3),
            (cols // 2, rows - 3),
            (2, rows - 3),
            (2, rows // 2),
            (cols // 2, rows // 2),
        ]
        points: list[tuple[float, float]] = []
        for c, r in tile_points:
            c = max(0, min(cols - 1, c))
            r = max(0, min(rows - 1, r))
            points.append(self.game.tilemap.tile_center(c, r))
        return points

    def _combat_count(self) -> int:
        return sum(
            1
            for u in self.game.units
            if u.kingdom_id == self.civilization and not u.is_dead and u.can_attack and not u.can_gather
        )

    def _unit_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for unit in self.game.units:
            if unit.kingdom_id != self.civilization or unit.is_dead:
                continue
            out[unit.unit_class] = out.get(unit.unit_class, 0) + 1
        return out

    def _enemy_unit_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for unit in self.game.units:
            if unit.kingdom_id == self.civilization or unit.is_dead:
                continue
            out[unit.unit_class] = out.get(unit.unit_class, 0) + 1
        return out

    def _nearest_enemy_unit_to(self, wx: float, wy: float) -> Unit | None:
        best = None
        best_d2 = 10e12
        for unit in self.game.units:
            if unit.is_dead:
                continue
            if unit.kingdom_id == self.civilization:
                continue
            dx = unit.world_pos.x - wx
            dy = unit.world_pos.y - wy
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best = unit
                best_d2 = d2
        return best

    def _can_afford(self, costs: dict[str, int]) -> bool:
        return self.game._kingdom_can_afford(self.civilization, costs)

    def _spend(self, costs: dict[str, int]) -> None:
        self.game._kingdom_spend(self.civilization, costs)
        self.resources = dict(self.game._kingdom(self.civilization).capital_stockpile)
