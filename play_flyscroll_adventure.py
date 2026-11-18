"""Autonomous Freedoom adventure pilot.

Uses ViZDoom's visual label/depth buffers for combat and navigation cues.
The optional FlyScroll connectome processes the same frames and contributes a
bounded exploration bias. This is an assisted game agent, not a trained policy.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import math
import random
import time
from pathlib import Path

import numpy as np
import vizdoom as vzd

ROOT = Path(__file__).resolve().parent
WAD = ROOT / "freedoom-0.13.0" / "freedoom1.wad"

ENEMIES = {
    "Zombieman", "ShotgunGuy", "DoomImp", "Demon", "Spectre",
    "Cacodemon", "LostSoul", "BaronOfHell", "HellKnight",
    "Arachnotron", "Mancubus", "Revenant", "PainElemental",
    "SpiderMastermind", "Cyberdemon", "WolfensteinSS",
}
PICKUP_CATEGORIES = {"Health", "Ammo", "Weapon", "Armor", "Key", "PowerUp"}
VARIABLES = [
    vzd.GameVariable.HEALTH,
    vzd.GameVariable.ARMOR,
    vzd.GameVariable.SELECTED_WEAPON_AMMO,
    vzd.GameVariable.KILLCOUNT,
    vzd.GameVariable.DAMAGECOUNT,
    vzd.GameVariable.DEATHCOUNT,
    vzd.GameVariable.ITEMCOUNT,
    vzd.GameVariable.SECRETCOUNT,
    vzd.GameVariable.POSITION_X,
    vzd.GameVariable.POSITION_Y,
    vzd.GameVariable.ANGLE,
]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def make_game(visible: bool, map_name: str, skill: int, god_mode: bool):
    game = vzd.DoomGame()
    game.set_doom_game_path(str(WAD))
    game.set_doom_map(map_name)
    game.set_doom_skill(skill)
    if god_mode:
        game.add_game_args('+sv_cheats 1 +god')
    game.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
    game.set_screen_format(vzd.ScreenFormat.RGB24)
    game.set_window_visible(visible)
    game.set_labels_buffer_enabled(True)
    game.set_objects_info_enabled(True)
    game.set_sectors_info_enabled(True)
    game.set_depth_buffer_enabled(True)
    game.set_episode_timeout(0)
    game.set_episode_start_time(10)
    game.set_render_hud(True)
    for variable in VARIABLES:
        game.add_available_game_variable(variable)
    for button in (
        vzd.Button.MOVE_FORWARD,
        vzd.Button.MOVE_BACKWARD,
        vzd.Button.MOVE_LEFT,
        vzd.Button.MOVE_RIGHT,
        vzd.Button.TURN_LEFT,
        vzd.Button.TURN_RIGHT,
        vzd.Button.ATTACK,
        vzd.Button.USE,
        vzd.Button.SPEED,
        vzd.Button.JUMP,
        vzd.Button.SELECT_NEXT_WEAPON,
        vzd.Button.SELECT_WEAPON0,
    ):
        game.add_available_button(button)
    return game


class AdventurePilot:
    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self.decision = 0
        self.explore_direction = 1
        self.explore_until = 0
        self.next_use = 0
        self.last_kills = 0
        self.last_damage = 0
        self.last_report = 0.0
        self.last_target = "exploring"
        self.strafe_direction = 1
        self.last_player_position = None
        self.last_player_sector = None
        self.sector_stall_count = 0
        self.stuck_count = 0
        self.recovery_until = 0
        self.recovery_direction = 1
        self.nav_suppressed_until = 0
        self.next_weapon_decision = 0
        self.navigator = None
        self.visited_sectors = set()
        self.blocked_sectors = set()
        self.last_goal_sector = None
        self.locked_target_id = None
        self.locked_target_steps = 0
        self.locked_target_best_route = None
        self.locked_target_best_distance = None

    def _visible_targets(self, state):
        enemies = []
        pickups = []
        for label in state.labels or []:
            name = str(label.object_name)
            category = str(label.object_category)
            center_x = float(label.x) + float(label.width) / 2.0
            if name in ENEMIES or category == "Monster":
                enemies.append((label, center_x))
            elif category in PICKUP_CATEGORIES:
                pickups.append((label, center_x))
        return enemies, pickups

    def _wall_avoidance(self, depth):
        if depth is None:
            return 0
        # Compare the center corridor with the two sides. A lower depth value
        # means a nearer surface in ViZDoom's normalized depth buffer.
        band = depth[85:190, :]
        left = float(np.median(band[:, 35:105]))
        center = float(np.median(band[:, 125:195]))
        right = float(np.median(band[:, 215:285]))
        if center + 4 < min(left, right) * 0.78:
            return -1 if left > right else 1
        return 0

    def _build_navigator(self, sectors):
        # ViZDoom exposes each sector's boundary lines. Shared non-blocking
        # lines form a traversable sector graph, which gives us real wall-aware
        # routes instead of blindly walking toward an enemy through walls.
        line_owners = defaultdict(list)
        for sector in sectors:
            for line in sector.lines:
                a = (round(float(line.x1), 2), round(float(line.y1), 2))
                b = (round(float(line.x2), 2), round(float(line.y2), 2))
                key = tuple(sorted((a, b)))
                line_owners[key].append((int(sector.id), bool(line.is_blocking), a, b))

        graph = defaultdict(list)
        for owners in line_owners.values():
            if len(owners) < 2 or any(blocked for _, blocked, _, _ in owners):
                continue
            for i, (sector_a, _, ax, ay) in enumerate(owners):
                for sector_b, _, _, _ in owners[i + 1:]:
                    midpoint = ((ax[0] + ay[0]) / 2.0, (ax[1] + ay[1]) / 2.0)
                    graph[sector_a].append((sector_b, midpoint))
                    graph[sector_b].append((sector_a, midpoint))
        return graph

    def _route(self, start_sector, goal_sector):
        if start_sector == goal_sector:
            return 0, None
        queue = deque([start_sector])
        parent = {start_sector: None}
        distances = {start_sector: 0}
        while queue:
            current = queue.popleft()
            for neighbor, waypoint in self.navigator.get(current, []):
                if neighbor in parent:
                    continue
                parent[neighbor] = (current, waypoint)
                distances[neighbor] = distances[current] + 1
                if neighbor == goal_sector:
                    node = goal_sector
                    while parent[node][0] != start_sector:
                        node = parent[node][0]
                    return distances[goal_sector], parent[node][1]
                queue.append(neighbor)
        return None, None

    def _next_unvisited_sector(self, start_sector):
        queue = deque([start_sector])
        parent = {start_sector: None}
        distances = {start_sector: 0}
        while queue:
            current = queue.popleft()
            for neighbor, waypoint in self.navigator.get(current, []):
                if neighbor in parent or neighbor in self.blocked_sectors:
                    continue
                parent[neighbor] = (current, waypoint)
                distances[neighbor] = distances[current] + 1
                if neighbor not in self.visited_sectors:
                    node = neighbor
                    while parent[node][0] != start_sector:
                        node = parent[node][0]
                    self.last_goal_sector = neighbor
                    return neighbor, parent[node][1], distances[neighbor]
                queue.append(neighbor)
        return None

    def _world_target(self, state, player_x, player_y, health):
        if self.navigator is None:
            self.navigator = self._build_navigator(state.sectors or [])
        player = next((o for o in (state.objects or []) if o.name == "DoomPlayer"), None)
        if player is None:
            return None
        start_sector = int(player.sector_id)
        self.visited_sectors.add(start_sector)
        if self.last_goal_sector == start_sector:
            self.last_goal_sector = None
        objects = list(state.objects or [])
        locked = next(
            (o for o in objects if self.locked_target_id is not None and int(o.id) == self.locked_target_id),
            None,
        )
        if locked is not None and (
            (str(locked.name) not in ENEMIES and str(locked.category) not in PICKUP_CATEGORIES)
            or int(locked.sector_id) in self.blocked_sectors
            or (health < 70 and str(locked.name) in ENEMIES)
            or (health < 45 and str(locked.category) not in {"Health", "Armor"})
        ):
            locked = None
            self.locked_target_id = None
            self.locked_target_steps = 0
            self.locked_target_best_route = None
            self.locked_target_best_distance = None
        if locked is not None:
            current_route, _ = self._route(start_sector, int(locked.sector_id))
            current_distance = math.hypot(float(locked.position_x) - player_x, float(locked.position_y) - player_y)
            if self.locked_target_best_route is None or current_route < self.locked_target_best_route or (
                current_route == self.locked_target_best_route
                and (self.locked_target_best_distance is None or current_distance < self.locked_target_best_distance - 48.0)
            ):
                self.locked_target_best_route = current_route
                self.locked_target_best_distance = current_distance
                self.locked_target_steps = 0
            else:
                self.locked_target_steps += 1
            if self.locked_target_steps > 120:
                if current_route and current_route > 0:
                    self.blocked_sectors.add(int(locked.sector_id))
                locked = None
                self.locked_target_id = None
                self.locked_target_steps = 0
                self.locked_target_best_route = None
                self.locked_target_best_distance = None
        candidates = [locked] if locked is not None else [
            o for o in objects
            if (str(o.name) in ENEMIES or str(o.category) in PICKUP_CATEGORIES)
            and int(o.sector_id) not in self.blocked_sectors
            and not (health < 45 and str(o.name) in ENEMIES)
            and not (health < 45 and str(o.category) not in {"Health", "Armor"})
        ]
        ranked = []
        for obj in candidates:
            route_steps, waypoint = self._route(start_sector, int(obj.sector_id))
            if route_steps is None:
                continue
            distance = math.hypot(float(obj.position_x) - player_x, float(obj.position_y) - player_y)
            # Prefer nearby hostiles, but allow a reachable supply to win when
            # health is low. The caller applies the health preference.
            is_enemy = str(obj.name) in ENEMIES
            supply_penalty = 5200.0 if is_enemy and health < 45 else (0.0 if is_enemy or health < 70 else 2600.0)
            health_bonus = -1800.0 if health < 60 and str(obj.category) == "Health" else 0.0
            score = route_steps * 420.0 + distance + supply_penalty + health_bonus
            ranked.append((score, is_enemy, obj, waypoint, route_steps))
        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0])
        chosen = ranked[0][1:]
        chosen_id = int(chosen[1].id)
        if chosen_id != self.locked_target_id:
            self.locked_target_steps = 0
            self.locked_target_best_route = chosen[3]
            self.locked_target_best_distance = math.hypot(float(chosen[1].position_x) - player_x, float(chosen[1].position_y) - player_y)
        self.locked_target_id = chosen_id
        self.last_goal_sector = int(chosen[1].sector_id)
        return chosen

    def decide(self, state, variables, connectome_rates=None):
        self.decision += 1
        health, armor, ammo, kills, damage, deaths, items, secrets = variables[:8]
        player_x, player_y, player_angle = variables[8:11]
        position = (player_x, player_y)
        player_object = next((o for o in (state.objects or []) if o.name == "DoomPlayer"), None)
        current_sector = int(player_object.sector_id) if player_object is not None else None
        if current_sector is not None:
            self.sector_stall_count = self.sector_stall_count + 1 if current_sector == self.last_player_sector else 0
            self.last_player_sector = current_sector
        if self.last_player_position is not None:
            moved = math.hypot(position[0] - self.last_player_position[0], position[1] - self.last_player_position[1])
            self.stuck_count = self.stuck_count + 1 if moved < 2.0 else max(0, self.stuck_count - 2)
            if self.stuck_count >= 14 and self.decision >= self.recovery_until:
                # A route can be geometrically reachable but still leave the
                # player pressed against a wall or doorway. Break contact with
                # a short reverse + strafe + turn maneuver before replanning.
                self.recovery_direction = self.rng.choice((-1, 1))
                # Do not immediately select the exact same unreachable goal
                # after backing away; let the planner choose another sector.
                if self.last_goal_sector is not None:
                    self.blocked_sectors.add(self.last_goal_sector)
                self.recovery_until = self.decision + 24
                self.nav_suppressed_until = self.recovery_until
                self.locked_target_id = None
                self.locked_target_steps = 0
                self.locked_target_best_route = None
                self.locked_target_best_distance = None
                self.last_goal_sector = None
                self.stuck_count = 0
        self.last_player_position = position
        if (
            self.sector_stall_count >= 80
            and self.last_goal_sector is not None
            and current_sector is not None
            and self.last_goal_sector != current_sector
            and self.decision >= self.recovery_until
        ):
            # Detect doorway oscillation: position can keep changing while the
            # agent circles inside one sector without reaching its goal sector.
            self.blocked_sectors.add(self.last_goal_sector)
            self.recovery_direction = self.rng.choice((-1, 1))
            self.recovery_until = self.decision + 24
            self.nav_suppressed_until = self.recovery_until
            self.locked_target_id = None
            self.locked_target_steps = 0
            self.locked_target_best_route = None
            self.locked_target_best_distance = None
            self.last_goal_sector = None
            self.sector_stall_count = 0
        enemies, pickups = self._visible_targets(state)
        if health < 45:
            enemies = []
        if self.decision < self.nav_suppressed_until:
            pickups = []
        else:
            pickups = [
                pair for pair in pickups
                if str(pair[0].object_category) != "Health" or health < 80
            ]
        action = {
            "forward": False, "backward": False,
            "strafe_left": False, "strafe_right": False,
            "left": False, "right": False,
            "attack": False, "use": False, "speed": True,
            "jump": False, "next_weapon": False, "fist": False,
        }
        target_name = "exploring"

        if enemies:
            # Prioritize the largest visible hostile, which is usually the
            # closest or most central threat in the player's view.
            label, cx = min(
                enemies,
                key=lambda pair: abs(pair[1] - 160) - min(40, pair[0].width) * 0.15,
            )
            offset = cx - 160.0
            target_name = str(label.object_name)
            if offset < -13:
                action["left"] = True
            elif offset > 13:
                action["right"] = True
            # Aim first, then fire when the target is reasonably centered.
            action["attack"] = abs(offset) < 42
            action["forward"] = abs(offset) < 58
            if abs(offset) < 35:
                action["strafe_left" if self.strafe_direction < 0 else "strafe_right"] = True
                if self.decision % 9 == 0:
                    self.strafe_direction *= -1
            if health < 30:
                action["backward"] = True
                action["forward"] = False

        else:
            # Route through the actual sector graph toward the nearest
            # reachable monster or supply. Shared blocking lines are excluded,
            # so the agent can go around walls instead of oscillating at them.
            target = self._world_target(state, player_x, player_y, health) if self.decision >= self.nav_suppressed_until else None
            if target is not None:
                is_enemy, obj, waypoint, route_steps = target
                tx, ty = waypoint if waypoint is not None else (float(obj.position_x), float(obj.position_y))
                dx, dy = tx - player_x, ty - player_y
                distance = math.hypot(dx, dy)
                # Doom ANGLE uses 0=east and increases counter-clockwise.
                bearing = math.degrees(math.atan2(dy, dx))
                error = (bearing - player_angle + 180.0) % 360.0 - 180.0
                target_name = f"route:{obj.name}/sector+{route_steps}"
                if route_steps > 0 and self.decision % 12 == 0:
                    action["use"] = True
                if abs(error) > 7:
                    action["left" if error > 0 else "right"] = True
                else:
                    action["forward"] = True
                if not is_enemy and str(obj.category) in PICKUP_CATEGORIES:
                    target_name = f"supply:{obj.name}/sector+{route_steps}"

            elif pickups:
                # Move toward visible supplies. Health and keys beat ordinary ammo.
                priority = {"Key": 0, "Health": 1, "Armor": 2, "Weapon": 3, "Ammo": 4, "PowerUp": 5}
                label, cx = min(
                    pickups,
                    key=lambda pair: (
                        priority.get(str(pair[0].object_category), 9)
                        if (health < 75 or str(pair[0].object_category) != "Health")
                        else 8,
                        abs(pair[1] - 160),
                    ),
                )
                target_name = str(label.object_name)
                offset = cx - 160.0
                if offset < -12:
                    action["left"] = True
                elif offset > 12:
                    action["right"] = True
                action["forward"] = abs(offset) < 85
                if not action["forward"]:
                    action["speed"] = False

            else:
                # Explore systematically: choose the next reachable sector
                # that has not been visited, then walk to its shared doorway.
                if self.navigator is None:
                    self.navigator = self._build_navigator(state.sectors or [])
                player = next((o for o in (state.objects or []) if o.name == "DoomPlayer"), None)
                current_sector = int(player.sector_id) if player is not None else None
                if current_sector is not None:
                    self.visited_sectors.add(current_sector)
                next_sector = self._next_unvisited_sector(current_sector) if current_sector is not None else None
                if next_sector is not None:
                    goal_sector, waypoint, route_steps = next_sector
                    tx, ty = waypoint
                    dx, dy = tx - player_x, ty - player_y
                    # Match Doom's map convention: 0=east, 90=north.
                    bearing = math.degrees(math.atan2(dy, dx))
                    error = (bearing - player_angle + 180.0) % 360.0 - 180.0
                    target_name = f"explore-sector:{goal_sector}"
                    if abs(error) > 7:
                        action["left" if error > 0 else "right"] = True
                    else:
                        action["forward"] = True
                    if self.decision % 12 == 0:
                        action["use"] = True
                else:
                    # Fallback patrol if every reachable sector was visited.
                    if self.decision >= self.explore_until:
                        self.explore_direction = self.rng.choice([-1, 1])
                        self.explore_until = self.decision + self.rng.randint(18, 34)
                    action["forward"] = True
                    if self.decision % 28 in (0, 1, 2):
                        action["left" if self.explore_direction < 0 else "right"] = True
                        action["forward"] = False

                # The connectome can provide a bounded exploration bias.
                if connectome_rates and self.decision % 7 == 0:
                    delta = connectome_rates.get("visual_R", 0.0) - connectome_rates.get("visual_L", 0.0)
                    total = connectome_rates.get("visual_total", 0.0)
                    if total > 0 and abs(delta) / total > 0.32:
                        self.explore_direction = 1 if delta > 0 else -1

        # Do not waste the pistol's trigger discipline: attack only when a
        # hostile is actually visible. Keep the player moving at run speed.
        if ammo <= 0:
            action["attack"] = False
            if self.decision >= self.next_weapon_decision:
                action["fist"] = True
                self.next_weapon_decision = self.decision + 10
            if enemies:
                label, cx = min(enemies, key=lambda pair: abs(pair[1] - 160))
                if abs(cx - 160) < 28 and label.width >= 18:
                    action["attack"] = True
        if health < 25 and not enemies:
            action["backward"] = False
            action["forward"] = True

        if self.decision < self.recovery_until:
            # Explicit escape maneuver: stop pushing into the obstacle, back
            # away diagonally, and rotate to expose a different corridor.
            action["forward"] = False
            action["backward"] = True
            action["strafe_left"] = self.recovery_direction < 0
            action["strafe_right"] = self.recovery_direction > 0
            action["left"] = self.recovery_direction < 0
            action["right"] = self.recovery_direction > 0
            action["attack"] = False
            action["use"] = False
            target_name = "unsticking / escape maneuver"

        self.last_target = target_name
        return action

    @staticmethod
    def action_vector(action):
        return [
            action["forward"], action["backward"],
            action["strafe_left"], action["strafe_right"],
            action["left"], action["right"],
            action["attack"], action["use"], action["speed"],
            action["jump"], action["next_weapon"], action["fist"],
        ]


def main():
    parser = argparse.ArgumentParser(description="Let the FlyScroll adventure pilot explore and fight in Freedoom.")
    parser.add_argument("--map", default="E1M1", help="Doom map, default E1M1.")
    parser.add_argument("--skill", type=int, choices=range(0, 6), default=0, help="Doom difficulty (0 is easiest).")
    parser.add_argument("--god-mode", action="store_true", help="Enable god mode so the pilot can keep exploring instead of dying.")
    parser.add_argument("--frames", type=int, default=0, help="Stop after N decisions; 0 runs until the episode ends.")
    parser.add_argument("--tics-per-action", type=int, default=6)
    parser.add_argument("--turn-tics", type=int, default=2, help="Shorter turn bursts prevent oscillation.")
    parser.add_argument("--fps", type=float, default=8.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--hidden", action="store_true", help="Run without showing the game window.")
    parser.add_argument("--connectome", action="store_true", help="Run the FlyScroll connectome each decision.")
    parser.add_argument("--connectome-scale", choices=("visual", "full"), default="visual", help="Use the reduced visual graph or the full prepared connectome.")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable the live browser dashboard.")
    parser.add_argument("--dashboard-port", type=int, default=8765)
    parser.add_argument("--flyscroll-root", type=Path, default=Path(r"D:\Experimental-projects\Fucking-fruitfly\Fruitfly-Doomscroller"))
    args = parser.parse_args()

    if not WAD.is_file():
        raise FileNotFoundError(f"Freedoom IWAD missing: {WAD}")
    if args.tics_per_action < 1 or args.turn_tics < 1 or args.fps <= 0:
        parser.error("tics-per-action, turn-tics and fps must be positive")

    game = make_game(not args.hidden, args.map, args.skill, args.god_mode)
    pilot = AdventurePilot(args.seed)
    brain = None
    dashboard = None
    decisions = 0
    started = time.monotonic()
    total_reward = 0.0
    try:
        print(f"[game] Starting Freedoom {args.map} with the adventure pilot (skill={args.skill}, god_mode={args.god_mode}).", flush=True)
        game.init()
        if args.connectome:
            from connectome_doom import ConnectomePilot
            brain = ConnectomePilot(args.flyscroll_root, args.connectome_scale, 2.0)
            print(f"[brain] FlyScroll {args.connectome_scale} connectome is online; bounded activity biases exploration.", flush=True)

        if not args.no_dashboard:
            from flyscroll_dashboard import FlyScrollDashboard
            dashboard = FlyScrollDashboard(port=args.dashboard_port)

        print("[pilot] Exploring, collecting visible supplies, aiming at hostiles, firing and opening doors. Ctrl+C stops.", flush=True)
        while not game.is_episode_finished():
            tick = time.monotonic()
            state = game.get_state()
            if state is None:
                break
            variables = state.game_variables
            if variables is None:
                raise RuntimeError("ViZDoom did not return the requested game variables.")
            values = [float(v) for v in variables]
            rates = None
            features = {}
            spikes = 0
            kernel_elapsed = 0.0
            if brain is not None and state.screen_buffer is not None:
                frame = np.asarray(state.screen_buffer, dtype=np.uint8)
                from PIL import Image
                rgb = np.asarray(
                    Image.fromarray(frame).resize((320, 180), Image.Resampling.BILINEAR),
                    dtype=np.uint8,
                )
                rates, features, kernel_elapsed, spikes = brain.step(rgb)

            action = pilot.decide(state, values, rates)
            turning = action["left"] or action["right"]
            action_tics = args.turn_tics if turning and not action["forward"] else args.tics_per_action
            reward = float(game.make_action(pilot.action_vector(action), action_tics))
            total_reward += reward
            decisions += 1

            if dashboard is not None:
                dashboard_stats = {
                    "health": values[0], "armor": values[1], "ammo": values[2],
                    "kills": values[3], "items": values[6], "secrets": values[7],
                }
                dashboard_actions = [name for name, active in action.items() if active and name != "speed"]
                from flyscroll_dashboard import publish
                publish(
                    frame=state.screen_buffer,
                    rates=rates or {},
                    features=features,
                    actions=dashboard_actions,
                    stats=dashboard_stats,
                    target=pilot.last_target,
                    brain_connected=brain is not None,
                    spikes=spikes,
                    total_spikes=brain.total_spikes if brain is not None else 0,
                    neural_ms=brain.brain.sim_ms if brain is not None else 0.0,
                    kernel_ms=kernel_elapsed * 1000.0,
                    fps=decisions / max(0.001, time.monotonic() - started),
                    decision=decisions,
                    reward=reward,
                )

            now = time.monotonic()
            if now - pilot.last_report >= 2.0 or decisions == 1:
                after = game.get_state()
                current = after.game_variables if after is not None else None
                stats = [float(v) for v in current] if current is not None else values
                print(
                    f"[pilot] step={decisions} hp={stats[0]:.0f} armor={stats[1]:.0f} "
                    f"ammo={stats[2]:.0f} kills={stats[3]:.0f} damage={stats[4]:.0f} "
                    f"items={stats[6]:.0f} secrets={stats[7]:.0f} "
                    f"pos=({stats[8]:.0f},{stats[9]:.0f}) angle={stats[10]:.1f} "
                    f"target={pilot.last_target} actions={[k for k, v in action.items() if v]} "
                    f"visible={[l.object_name for l in (after.labels or []) if str(l.object_name) in ENEMIES]} "
                    f"reward={total_reward:.1f}",
                    flush=True,
                )
                pilot.last_report = now

            if args.frames and decisions >= args.frames:
                break
            delay = (1.0 / args.fps) - (time.monotonic() - tick)
            if delay > 0:
                time.sleep(delay)

        final_state = game.get_state()
        final_vars = [float(v) for v in final_state.game_variables] if final_state and final_state.game_variables is not None else []
        print(
            f"[done] decisions={decisions} reward={total_reward:.1f} "
            f"final_stats={final_vars} episode_finished={game.is_episode_finished()}",
            flush=True,
        )
        return 0
    except KeyboardInterrupt:
        print("\n[pilot] Stop requested.", flush=True)
        return 0
    finally:
        game.close()
        if dashboard is not None:
            dashboard.close()
        print("[game] Closed cleanly.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
