"""Run the existing FlyScroll MaleCNS visual brain inside ViZDoom.

This is an experimental, hand-decoded controller, not a trained Doom policy.
Run from this directory:
    .venv\\Scripts\\python.exe play_flyscroll_vizdoom.py
Stop at any time with Ctrl+C.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import numpy as np
from PIL import Image
import vizdoom as vzd

ROOT = Path(__file__).resolve().parent
DEFAULT_FLYSCROLL = ROOT.parent / "Fruitfly-Doomscroller"
WAD = ROOT / "freedoom-0.13.0" / "freedoom1.wad"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Let the existing FlyScroll connectome control Freedoom through ViZDoom."
    )
    parser.add_argument(
        "--flyscroll-root",
        type=Path,
        default=Path(os.environ.get("FLYSCROLL_ROOT", DEFAULT_FLYSCROLL)),
    )
    parser.add_argument("--scale", choices=("visual", "full"), default="visual")
    parser.add_argument("--fps", type=float, default=5.0,
                        help="Neural decision updates per second (default: 5).")
    parser.add_argument("--neural-ms", type=float, default=2.0)
    parser.add_argument("--threshold", type=float, default=0.01)
    parser.add_argument("--tics-per-action", type=int, default=4,
                        help="Doom simulation tics per neural decision (default: 4).")
    parser.add_argument("--frames", type=int, default=0,
                        help="Stop after N decisions; 0 runs until Ctrl+C.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run brain and perception without applying its actions.")
    parser.add_argument("--enable-experimental-turning", action="store_true",
                        help="Enable untrained bilateral-DN steering (may cause continuous spinning).")
    parser.add_argument("--visible", action="store_true", default=True,
                        help="Show the ViZDoom window (default).")
    parser.add_argument("--viz-server", type=str, default="http://127.0.0.1:8765",
                        help="Neural visualization server URL (default: http://127.0.0.1:8765)")
    parser.add_argument("--no-viz", action="store_true",
                        help="Disable sending data to neural visualization server")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.fps <= 0 or args.neural_ms <= 0 or args.threshold < 0:
        raise SystemExit("fps/neural-ms must be positive and threshold cannot be negative.")
    if args.tics_per_action < 1:
        raise SystemExit("--tics-per-action must be at least 1.")
    if not WAD.is_file():
        raise FileNotFoundError(f"Freedoom IWAD not found: {WAD}")

    # Neural visualization server posting
    viz_enabled = not args.no_viz
    viz_url = args.viz_server.rstrip('/') + '/api/neural'
    last_viz_post = 0.0
    viz_post_interval = 0.1

    def post_to_viz_server(data: dict):
        nonlocal last_viz_post
        if not viz_enabled:
            return
        now = time.monotonic()
        if now - last_viz_post < viz_post_interval:
            return
        last_viz_post = now
        try:
            req = urllib.request.Request(
                viz_url,
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            urllib.request.urlopen(req, timeout=0.05)
        except Exception:
            pass

    # Reuse the already-audited FlyScroll adapter and experimental decoder.
    sys.path.insert(0, str(ROOT))
    from connectome_doom import ConnectomePilot

    print(f"[game] ViZDoom {vzd.__version__}; loading {WAD.name}", flush=True)
    game = vzd.DoomGame()
    game.set_doom_game_path(str(WAD))
    game.set_doom_map("E1M1")
    game.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
    game.set_screen_format(vzd.ScreenFormat.RGB24)
    game.set_window_visible(args.visible)
    game.set_episode_timeout(0)
    game.set_episode_start_time(10)

    buttons = [
        vzd.Button.MOVE_FORWARD,
        vzd.Button.MOVE_BACKWARD,
        vzd.Button.TURN_LEFT,
        vzd.Button.TURN_RIGHT,
        vzd.Button.ATTACK,
    ]
    for button in buttons:
        game.add_available_button(button)

    pilot = None
    decisions = 0
    total_spikes = 0
    started = time.monotonic()
    last_report = started
    try:
        print("[game] Initializing Freedoom E1M1...", flush=True)
        game.init()
        print("[game] Ready. Initializing the FlyScroll connectome...", flush=True)

        pilot = ConnectomePilot(args.flyscroll_root, args.scale, args.neural_ms)
        print(
            "[pilot] LIVE CONTROL" if not args.dry_run else "[pilot] DRY RUN",
            "| Ctrl+C to stop.",
            flush=True,
        )
        print(
            "[pilot] Default controls: forward/attack only; steering is disabled until calibrated. "
            "Use --enable-experimental-turning to test raw bilateral-DN steering.",
            flush=True,
        )

        while not game.is_episode_finished():
            tick = time.monotonic()
            state = game.get_state()
            if state is None or state.screen_buffer is None:
                raise RuntimeError("ViZDoom returned no screen buffer.")

            # ViZDoom returns HxWx3 RGB24; FlyEyeProcessor was previously
            # exercised at 320x180, so preserve that input geometry.
            rgb = np.asarray(
                Image.fromarray(state.screen_buffer).convert("RGB").resize(
                    (320, 180), Image.Resampling.BILINEAR
                ),
                dtype=np.uint8,
            )

            rates, features, sim_elapsed, spikes = pilot.step(rgb)
            total_spikes += spikes
            actions, turn_delta, visual_dn = pilot.decode(
                rates, args.threshold, enable_turning=args.enable_experimental_turning
            )

            forward = "forward" in actions and "reverse" not in actions
            backward = "reverse" in actions and not forward
            left = "left" in actions and "right" not in actions
            right = "right" in actions and not left
            attack = "fire" in actions

            action_vector = [forward, backward, left, right, attack]
            if args.dry_run:
                action_vector = [False] * len(buttons)

            reward = game.make_action(action_vector, args.tics_per_action)
            decisions += 1

            now = time.monotonic()

            # Prepare data for visualization server
            viz_data = {
                "frame": decisions,
                "fps_actual": args.fps,
                "spikes": spikes,
                "spike_total": total_spikes,
                "simulation_ms": round(float(pilot.brain.sim_ms), 2),
                "kernel_ms": round(sim_elapsed * 1000, 2),
                "turn_delta": round(turn_delta, 4),
                "visual_dn": round(visual_dn, 4),
                "rates": {k: round(v, 3) for k, v in rates.items()},
                "frame_luma_mean": round(float(rgb.mean()), 2),
                "frame_luma_std": round(float(rgb.std()), 2),
                "decoded_actions": sorted(actions),
                "actions": sorted(actions) if not args.dry_run else [],
                "mode": "dry-run" if args.dry_run else "live-control",
            }

            # Post to visualization server
            post_to_viz_server(viz_data)

            if now - last_report >= 1.0 or decisions == 1:
                current = game.get_state()
                print(json.dumps({
                    "decision": decisions,
                    "elapsed_s": round(now - started, 2),
                    "game_tic": game.get_episode_time(),
                    "reward": round(float(reward), 3),
                    "neural_spikes": spikes,
                    "total_spikes": total_spikes,
                    "neural_sim_ms": round(float(pilot.brain.sim_ms), 2),
                    "kernel_ms": round(sim_elapsed * 1000, 2),
                    "visual_dn": round(visual_dn, 4),
                    "turn_delta": round(turn_delta, 4),
                    "rates": {k: round(v, 3) for k, v in rates.items()},
                    "decoded_actions": sorted(actions),
                    "applied_buttons": [
                        button.name for button, active in zip(buttons, action_vector) if active
                    ],
                    "screen_mean": round(float(rgb.mean()), 2),
                    "screen_std": round(float(rgb.std()), 2),
                    "dry_run": args.dry_run,
                    "episode_finished": game.is_episode_finished(),
                }), flush=True)
                last_report = now

            if args.frames and decisions >= args.frames:
                break

            delay = (1.0 / args.fps) - (time.monotonic() - tick)
            if delay > 0:
                time.sleep(delay)

        print(
            f"[done] decisions={decisions}, total_spikes={total_spikes}, "
            f"episode_finished={game.is_episode_finished()}",
            flush=True,
        )
        return 0
    except KeyboardInterrupt:
        print("\n[pilot] Stop requested.", flush=True)
        return 0
    finally:
        game.close()
        print("[game] ViZDoom closed.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
