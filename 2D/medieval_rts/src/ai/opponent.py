from __future__ import annotations

import random
from typing import TYPE_CHECKING

from settings import TILE_SIZE
from src.entities.building import Building
from src.entities.unit import Unit

if TYPE_CHECKING:
    from game import Game
    from src.systems.resources import ResourceNode


class AIController:
    STATE_EXPAND = "EXPAND"
    STATE_GATHER = "GATHER"
    STATE_ATTACK = "ATTACK"
    STATE_DEFEND = "DEFEND"
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
    ) -> None:
        self.game = game
        self.civilization = civilization
        self.enemy_civilization = enemy_civilization
        self._rng = random.Random(seed + 44041)
        self._base_world_hint = base_world

        # Stronger kingdom economy to better resist chaos and scale military.
        self.resources = {
            "gold": 1450,
            "wood": 1400,
            "stone": 1300,
            "food": 0,
            "meat": 0,
        }
        self.capacity = {
            "gold": 3200,
            "wood": 3200,
            "stone": 3000,
            "food": 1200,
            "meat": 1200,
        }

        self._elapsed_s = 0.0
        self._attack_unlock_s = 54.0
        self._state_index = 0
        self._state_timer_s = 0.0
        self._production_timer_s = 1.4
        self._expand_timer_s = 1.9
        self._gather_order_timer_s = 0.85
        self._construction_order_timer_s = 0.55
        self._attack_order_timer_s = 0.95
        self._scan_timer_s = 4.0
        self._defense_hold_s = 0.0
        self._attack_target_refresh_s = 0.0
        self._attack_target = None
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
        return self._STATE_CYCLE[self._state_index]

    def bootstrap(self) -> None:
        if self._bootstrapped:
            return

        if self._base_world_hint is not None:
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
        self._scan_timer_s -= dt
        self._attack_target_refresh_s -= dt
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

        if self.state == self.STATE_ATTACK and not self._can_launch_attack():
            self._force_state(self.STATE_GATHER)

        self._advance_state_if_ready()

        if self._production_timer_s <= 0.0:
            self._production_timer_s = 1.45 if self.state == self.STATE_ATTACK else 1.65
            self._queue_production()

        if self.state == self.STATE_EXPAND:
            self._run_expand()
        elif self.state == self.STATE_GATHER:
            self._run_gather()
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
        self.resources[key] = self.resources.get(key, 0) + gained
        return gained

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

    def _run_attack(self) -> None:
        if not self._can_launch_attack():
            self._force_state(self.STATE_GATHER)
            return
        if self._attack_order_timer_s > 0.0:
            return
        self._attack_order_timer_s = 0.62

        attackers = [
            u
            for u in self.game.units
            if u.civilization == self.civilization and not u.is_dead and u.can_attack and not u.can_gather
        ]
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
            if u.civilization == self.civilization and not u.is_dead and u.can_attack and not u.can_gather
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
            if u.civilization == self.civilization and not u.is_dead and not u.can_gather
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
        if state not in self._STATE_CYCLE:
            return
        self._state_index = self._STATE_CYCLE.index(state)
        self._state_timer_s = 0.0

    def _can_launch_attack(self) -> bool:
        if self._elapsed_s < self._attack_unlock_s:
            return False
        if self._combat_count() < 4:
            return False
        has_military = any(
            b.civilization == self.civilization
            and b.is_complete
            and b.building_type in (Building.TYPE_BARRACKS, Building.TYPE_ARCHERY, Building.TYPE_CASTLE)
            for b in self.game.buildings
        )
        return has_military

    def _enemy_units_near_base(self) -> list[Unit]:
        radius2 = self._threat_radius * self._threat_radius
        out: list[Unit] = []
        for unit in self.game.units:
            if unit.is_dead or unit.civilization == self.civilization:
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
        if self._attack_target is not None and self._attack_target_refresh_s > 0.0:
            if isinstance(self._attack_target, Unit):
                if not self._attack_target.is_dead and self._attack_target.civilization != self.civilization:
                    return self._attack_target
            elif isinstance(self._attack_target, Building):
                if not self._attack_target.is_dead and self._attack_target.civilization != self.civilization:
                    return self._attack_target

        self._attack_target_refresh_s = 2.8
        enemy_units = [
            u
            for u in self.game.units
            if u.civilization != self.civilization and not u.is_dead
        ]
        enemy_buildings = [
            b
            for b in self.game.buildings
            if b.civilization != self.civilization and not b.is_dead and not b.under_construction
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
        desired = {
            Building.TYPE_HOUSE1: 2 if workers >= 6 else 1,
            Building.TYPE_HOUSE2: 2 if elapsed > 100 else 1,
            Building.TYPE_HOUSE3: 2 if elapsed > 170 else 1,
            Building.TYPE_BARRACKS: 1 + int(elapsed > 110) + int(combat > 14),
            Building.TYPE_ARCHERY: 1 + int(elapsed > 95) + int(combat > 12),
            Building.TYPE_TOWER: 1 + int(threat >= 2) + int(elapsed > 220),
            Building.TYPE_SMITHY: 1 if elapsed > 120 else 0,
            Building.TYPE_CASTLE: 1 if elapsed > 210 else 0,
        }
        for building_type, _ in self._BUILD_PLAN:
            wanted_count = desired.get(building_type, 1)
            if wanted_count <= 0:
                continue
            have = sum(
                1
                for b in self.game.buildings
                if b.civilization == self.civilization and b.building_type == building_type
            )
            if have >= wanted_count:
                continue
            site = self._try_place_building(building_type, pay_cost=True)
            if site is not None:
                self._assign_workers_to_construction(site, max_workers=4 if threat >= 2 else 3)
            break

    def _queue_production(self) -> None:
        producers = [
            b
            for b in self.game.buildings
            if b.civilization == self.civilization and b.can_produce and b.is_complete
        ]
        if not producers:
            return

        counts = self._unit_counts()
        enemy_counts = self._enemy_unit_counts()
        for building in producers:
            queue_target = building.max_queue - 1 if self.state in (self.STATE_ATTACK, self.STATE_DEFEND) else max(
                2, building.max_queue - 2
            )
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
                node = self.game.resource_manager.nearest_node(preferred, worker.world_pos.x, worker.world_pos.y)
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
        return self._resource_priority_list()[0]

    def _resource_priority_list(self) -> list[str]:
        targets = {
            "gold": 650,
            "wood": 760,
            "stone": 600,
            "food": 200,
        }
        if not any(
            b.civilization == self.civilization and b.building_type == Building.TYPE_BARRACKS
            for b in self.game.buildings
        ):
            targets["wood"] += 240
            targets["stone"] += 120
        scored: list[tuple[float, str]] = []
        for key, target in targets.items():
            have = self.resources.get(key, 0)
            score = have / max(1, target)
            scored.append((score, key))
        scored.sort(key=lambda x: x[0])
        return [key for _, key in scored]

    def _nearest_any_resource(self, wx: float, wy: float) -> ResourceNode | None:
        best = None
        best_d2 = 10e12
        for node in self.game.resource_manager.nodes:
            if node.is_depleted:
                continue
            if node.resource_type not in ("gold", "wood", "stone", "food", "meat"):
                continue
            dx = node.wx - wx
            dy = node.wy - wy
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best = node
                best_d2 = d2
        return best

    def _try_place_building(self, building_type: str, *, pay_cost: bool) -> Building | None:
        costs = Building.build_cost(building_type)
        if pay_cost and not self._can_afford(costs):
            return None

        anchor = self._find_anchor_for_building(building_type)
        if anchor is None:
            return None

        if pay_cost:
            self._spend(costs)

        bx, by = self.game.tilemap.tile_center(anchor[0], anchor[1])
        b = Building(
            bx,
            by,
            building_type=building_type,
            civilization=self.civilization,
            max_hp=self.game._max_hp_for_building(building_type),
            start_progress=0.05,
        )
        if b.building_type == Building.TYPE_TOWER:
            b.is_dock = self.game._building_touches_water(b.footprint_tiles(self.game.tilemap))
        self.game.buildings.append(b)
        self.game._refresh_building_masks()
        return b

    def _find_anchor_for_building(self, building_type: str) -> tuple[int, int] | None:
        bc, br = self._base_tile
        for radius in range(2, 22):
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
                if self.game._is_placement_valid(footprint):
                    return anchor
        return None

    def _assign_idle_workers_to_sites(self) -> None:
        sites = [
            b
            for b in self.game.buildings
            if b.civilization == self.civilization and b.under_construction
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
        self.game.units.append(Unit(bx, by - 16, civilization=self.civilization, unit_class=Unit.ROLE_HERO))
        mx, my = self.game._find_spawn_world_near(bx + 38, by + 64)
        self.game.units.append(Unit(mx, my, civilization=self.civilization, unit_class=Unit.ROLE_MONK))
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
                    civilization=self.civilization,
                    unit_class=Unit.ROLE_WORKER,
                )
            )

    def _workers(self) -> list[Unit]:
        return [
            u
            for u in self.game.units
            if u.civilization == self.civilization and not u.is_dead and u.can_gather
        ]

    def _builders(self) -> list[Unit]:
        return [
            u
            for u in self.game.units
            if u.civilization == self.civilization and not u.is_dead and u.can_construct
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
            if u.civilization == self.civilization and not u.is_dead and u.can_attack and not u.can_gather
        )

    def _unit_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for unit in self.game.units:
            if unit.civilization != self.civilization or unit.is_dead:
                continue
            out[unit.unit_class] = out.get(unit.unit_class, 0) + 1
        return out

    def _enemy_unit_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for unit in self.game.units:
            if unit.civilization == self.civilization or unit.is_dead:
                continue
            out[unit.unit_class] = out.get(unit.unit_class, 0) + 1
        return out

    def _nearest_enemy_unit_to(self, wx: float, wy: float) -> Unit | None:
        best = None
        best_d2 = 10e12
        for unit in self.game.units:
            if unit.is_dead:
                continue
            if unit.civilization == self.civilization:
                continue
            dx = unit.world_pos.x - wx
            dy = unit.world_pos.y - wy
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best = unit
                best_d2 = d2
        return best

    def _can_afford(self, costs: dict[str, int]) -> bool:
        for key, amount in costs.items():
            if int(amount) <= 0:
                continue
            if self.resources.get(key, 0) < int(amount):
                return False
        return True

    def _spend(self, costs: dict[str, int]) -> None:
        for key, amount in costs.items():
            val = int(amount)
            if val <= 0:
                continue
            self.resources[key] = max(0, self.resources.get(key, 0) - val)
