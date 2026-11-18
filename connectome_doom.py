from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

ROOT = Path(__file__).resolve().parent
DEFAULT_FLYSCROLL = ROOT.parent / "Fruitfly-Doomscroller"


def find_game_window(fragment: str):
    user32 = ctypes.windll.user32
    matches = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        if fragment.casefold() in title.value.casefold():
            matches.append((hwnd, title.value))
        return True

    user32.EnumWindows(callback, 0)
    return matches[0] if matches else (None, None)


def capture_client(hwnd, size):
    user32 = ctypes.windll.user32
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Could not read the GZDoom client rectangle.")
    origin = wintypes.POINT()
    origin.x, origin.y = 0, 0
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise RuntimeError("Could not locate the GZDoom client on screen.")
    box = (origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)
    if box[2] <= box[0] or box[3] <= box[1]:
        raise RuntimeError("GZDoom window is minimized or has no drawable area.")
    image = ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")
    image = image.resize(size, Image.Resampling.BILINEAR)
    return np.asarray(image, dtype=np.uint8)


# Send scan-code keyboard events rather than legacy virtual-key events.
# SDL/GZDoom may ignore keybd_event-style virtual-key injection in some setups.
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


def set_key(vk: int, down: bool):
    # Declare Win32 signatures explicitly. Without argtypes, ctypes can marshal
    # pointer-sized parameters incorrectly on 64-bit Windows.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    scan = user32.MapVirtualKeyW(vk, 0)
    if not scan:
        raise RuntimeError(f"Windows could not map virtual key 0x{vk:02X} to a scan code.")
    flags = KEYEVENTF_SCANCODE
    if vk in (0x25, 0x26, 0x27, 0x28):
        flags |= KEYEVENTF_EXTENDEDKEY
    if not down:
        flags |= KEYEVENTF_KEYUP
    event = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0),
    )
    ctypes.set_last_error(0)
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        error = ctypes.get_last_error()
        raise OSError(
            error,
            f"SendInput inserted {sent}/1 events for VK 0x{vk:02X} "
            f"(scan 0x{scan:02X}); INPUT size={ctypes.sizeof(INPUT)} bytes. "
            "If the error remains zero, Windows may be blocking injection across "
            "an integrity-level boundary (for example, elevated GZDoom)."
        )


# GZDoom's classic defaults: Up/Down move, Left/Right turn, Ctrl fires.
# WASD is not enabled by every Doom configuration.
KEYS = {"forward": 0x26, "reverse": 0x28, "left": 0x25,
        "right": 0x27, "fire": 0x11}


class ConnectomePilot:
    """Experimental readout decoder. These motor mappings are hypotheses."""

    def __init__(self, flyscroll_root: Path, scale: str, neural_ms: float,
                 calibrated_drive: bool = False):
        sys.path.insert(0, str(flyscroll_root))
        from flyscroll.engine import Brain
        from flyscroll.flyvision import FlyEyeProcessor

        graph = flyscroll_root / "outputs" / "flyscroll" / "malecns_v1" / scale / "graph.npz"
        manifest_path = graph.with_name("manifest.json")
        if not graph.is_file() or not manifest_path.is_file():
            raise FileNotFoundError(
                f"Prepared FlyScroll graph not found: {graph}. "
                f"Prepare the '{scale}' graph in the original FlyScroll project first."
            )
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"[brain] Loading {self.manifest['neurons']:,} neurons / "
              f"{self.manifest['edges']:,} edges ({scale} graph)...", flush=True)
        self.brain = Brain(graph)
        self.eye = FlyEyeProcessor(self.brain)
        self.neural_ms = neural_ms
        self.calibrated_drive = bool(calibrated_drive)
        self.last_counts = np.zeros(self.brain.n, dtype=np.float32)
        types = np.asarray(self.brain.cell_type).astype(str)
        readouts = self.manifest.get("readouts", [])
        self.indices = {}
        for name in ("DNa02", "DNp09", "MDN", "DNp20", "DNpe017",
                     "LC11", "LC18", "LC17", "LPLC2", "LC4", "LC6"):
            self.indices[name] = np.flatnonzero(types == name).astype(np.int32)
        self.sides = {}
        for item in readouts:
            name = str(item.get("type", ""))
            side = str(item.get("side", "")).upper()
            if name in ("DNa02", "DNp09", "MDN", "DNp20", "DNpe017") and side in ("L", "R"):
                self.sides.setdefault(f"{name}_{side}", []).append(int(item["index"]))
        self.sides = {k: np.asarray(v, dtype=np.int32) for k, v in self.sides.items()}
        self.smoothed = {k: 0.0 for k in self.indices}
        self.smoothed.update({k: 0.0 for k in self.sides})
        self.alpha = 1.0 - np.exp(-(neural_ms / 1000.0) / 0.20)
        self.steps = 0
        self.total_spikes = 0
        print("[brain] Loaded. Readout population sizes: " +
              ", ".join(f"{k}={len(v)}" for k, v in self.indices.items()), flush=True)

    def step(self, rgb):
        dt = self.neural_ms / 1000.0
        eye_frame = self.eye.process(rgb, self.brain, dt_seconds=dt)
        def apply_calibrated_drive(network):
            delta = network.luminance - np.float32(0.32)
            network.drive[network.retina] = np.clip(8.5 + 20.0 * delta, 0.0, 30.0)
            network.drive[network.lamina] = 7.5
            network.drive[network.chromatic] = 0.0
            return None

        counts, elapsed, _ = self.brain.step(
            eye_frame.luminance,
            eye_frame.chromatic,
            duration_ms=self.neural_ms,
            enrich_drive=apply_calibrated_drive if self.calibrated_drive else None,
        )
        self.last_counts = counts.astype(np.float32, copy=True)
        rates = {}
        for name, indices in self.indices.items():
            rate = float(counts[indices].sum() / max(1, len(indices)) / dt) if len(indices) else 0.0
            self.smoothed[name] += self.alpha * (rate - self.smoothed[name])
            rates[name] = self.smoothed[name]
        for key, indices in self.sides.items():
            rate = float(counts[indices].sum() / max(1, len(indices)) / dt) if len(indices) else 0.0
            self.smoothed[key] += self.alpha * (rate - self.smoothed[key])
            rates[key] = self.smoothed[key]
        rates["visual_L"] = rates.get("DNp20_L", 0.0) + rates.get("DNpe017_L", 0.0)
        rates["visual_R"] = rates.get("DNp20_R", 0.0) + rates.get("DNpe017_R", 0.0)
        rates["visual_total"] = rates["visual_L"] + rates["visual_R"]
        rates["object_detector"] = sum(rates.get(k, 0.0) for k in ("LC11", "LC18", "LC17"))
        rates["looming_detector"] = sum(rates.get(k, 0.0) for k in ("LPLC2", "LC4", "LC6"))
        self.steps += 1
        spikes = int(counts.sum())
        self.total_spikes += spikes
        return rates, eye_frame.features, elapsed, spikes

    @staticmethod
    def decode(rates, threshold: float, enable_turning: bool = False):
        # The direction / action assignments are experimental hypotheses,
        # not validated claims about natural Drosophila motor behavior.
        visual_left = rates.get("visual_L", 0.0)
        visual_right = rates.get("visual_R", 0.0)
        visual = visual_left + visual_right
        # DNp20 / DNpe017 are the connectome's visual descending readouts.
        # Their bilateral difference is an experimental steering signal.
        turn = visual_right - visual_left
        actions = set()
        # Bilateral visual activity is not yet calibrated as a motor command.
        # Keep steering disabled by default; raw asymmetry caused continuous spins.
        if enable_turning and abs(turn) > max(threshold, visual * 0.18):
            actions.add("right" if turn > 0 else "left")
        # Forward/reverse assignments remain separate experimental hypotheses.
        if rates.get("DNp09", 0.0) > threshold:
            actions.add("forward")
        elif visual > threshold * 4:
            actions.add("forward")
        if rates.get("MDN", 0.0) > threshold:
            actions.add("reverse")
        # LC11/LC18/LC17 are small-object visual readouts; firing is a game-only
        # action mapping, not a claim that these neurons encode weapon use.
        if rates.get("looming_detector", 0.0) > max(2.0, threshold * 0.3):
            actions.add("fire")
        return actions, turn, visual


def main():
    parser = argparse.ArgumentParser(description="Drive Freedoom from FlyScroll MaleCNS activity.")
    parser.add_argument("--flyscroll-root", type=Path,
                        default=Path(os.environ.get("FLYSCROLL_ROOT", DEFAULT_FLYSCROLL)))
    parser.add_argument("--window-title", default="Freedoom")
    parser.add_argument("--scale", choices=("visual", "full"), default="visual")
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--neural-ms", type=float, default=2.0)
    parser.add_argument("--threshold", type=float, default=10.0,
                        help="Experimental smoothed spike-rate threshold.")
    parser.add_argument("--motion-decoder", action="store_true",
                        help="Use the trained full-connectome motion readout in experimental pulse mode.")
    parser.add_argument("--motion-model", type=Path, default=ROOT / "neural_motion_readout.npz",
                        help="Trained neural motion readout artifact.")
    parser.add_argument("--motion-window-frames", type=int, default=20,
                        help="Spike-count accumulation window for the trained readout.")
    parser.add_argument("--motion-minimum-margin", type=float, default=0.0,
                        help="Minimum absolute readout score required to emit a turn pulse.")
    parser.add_argument("--allow-experimental-live-control", action="store_true",
                        help="Explicitly allow the unvalidated motion readout to send turn inputs to GZDoom.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run perception and neural simulation but do not send game inputs.")
    parser.add_argument("--input-test", action="store_true",
                        help="Test the game's Up Arrow input for a few seconds, measure the framebuffer change, then exit.")
    parser.add_argument("--input-test-seconds", type=float, default=2.5,
                        help="Duration of the isolated forward-key test (default: 2.5 seconds).")
    parser.add_argument("--frames", type=int, default=0,
                        help="Stop after this many frames; 0 means run until Ctrl+C.")
    parser.add_argument("--viz-server", type=str, default="http://127.0.0.1:8765",
                        help="Neural visualization server URL (default: http://127.0.0.1:8765)")
    parser.add_argument("--no-viz", action="store_true",
                        help="Disable sending data to neural visualization server")
    args = parser.parse_args()

    if args.fps <= 0 or args.neural_ms <= 0 or args.threshold < 0:
        parser.error("fps and neural-ms must be positive; threshold cannot be negative.")
    if args.motion_window_frames < 1 or args.motion_minimum_margin < 0:
        parser.error("motion-window-frames must be positive and motion-minimum-margin non-negative.")
    if args.motion_decoder and args.scale != "full":
        parser.error("--motion-decoder requires --scale full; the trained model expects 166700 neurons.")
    if args.motion_decoder and args.neural_ms != 2.0:
        parser.error("--motion-decoder was calibrated at 2 ms per captured frame; use --neural-ms 2.")
    if args.motion_decoder and not args.dry_run and not args.allow_experimental_live_control:
        parser.error("The motion readout is unvalidated on Doom footage. Start with --dry-run; live input additionally requires --allow-experimental-live-control.")
    if args.input_test_seconds <= 0:
        parser.error("input-test-seconds must be positive.")

    # Neural visualization server posting
    viz_enabled = not args.no_viz
    viz_url = args.viz_server.rstrip('/') + '/api/neural'
    last_viz_post = 0.0
    viz_post_interval = 0.1  # Post at most 10 Hz to avoid overwhelming the server

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
            # Non-blocking with short timeout
            urllib.request.urlopen(req, timeout=0.05)
        except Exception:
            pass  # Silently ignore viz server errors

    hwnd, title = find_game_window(args.window_title)
    if not hwnd:
        raise SystemExit(f"No visible window containing {args.window_title!r} was found. Launch Freedoom first.")
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    foreground = user32.GetForegroundWindow()
    current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
    game_thread = user32.GetWindowThreadProcessId(hwnd, None)
    attached = []
    for thread_id in {foreground_thread, game_thread}:
        if thread_id and thread_id != current_thread:
            if user32.AttachThreadInput(current_thread, thread_id, True):
                attached.append(thread_id)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
        time.sleep(0.5)
    finally:
        for thread_id in attached:
            user32.AttachThreadInput(current_thread, thread_id, False)
    foreground = user32.GetForegroundWindow()
    foreground_length = user32.GetWindowTextLengthW(foreground)
    foreground_title = ctypes.create_unicode_buffer(foreground_length + 1)
    user32.GetWindowTextW(foreground, foreground_title, foreground_length + 1)
    game_pid = ctypes.c_ulong()
    foreground_pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(game_pid))
    user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
    print(f"[game] Connected to: {title}", flush=True)
    print(f"[game] Foreground window: {foreground_title.value or '<untitled>'}", flush=True)
    print(f"[game] Window process IDs: target={game_pid.value}, foreground={foreground_pid.value}", flush=True)
    # GZDoom can expose a child/render window as the foreground HWND. In that
    # case the handle differs from the enumerated top-level window but the PID
    # is still GZDoom, so comparing HWNDs alone incorrectly rejects valid focus.
    if foreground_pid.value != game_pid.value:
        print("[game] GZDoom did not take focus. Click inside the game window now...", flush=True)
        time.sleep(5.0)
        foreground = user32.GetForegroundWindow()
        foreground_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
        if foreground_pid.value != game_pid.value:
            raise RuntimeError(
                "GZDoom is not focused. Click inside the active game view, then rerun this test."
            )
        print("[game] Focus confirmed by matching GZDoom process ID.", flush=True)
    else:
        print("[game] Focus confirmed by matching GZDoom process ID.", flush=True)

    if args.input_test:
        print("[test] Capturing baseline game frame...", flush=True)
        before = capture_client(hwnd, (320, 180))
        print(f"[test] Holding Up Arrow for {args.input_test_seconds:.1f}s...", flush=True)
        set_key(KEYS["forward"], True)
        try:
            time.sleep(args.input_test_seconds)
        finally:
            set_key(KEYS["forward"], False)
        time.sleep(0.35)
        after = capture_client(hwnd, (320, 180))
        difference = np.abs(after.astype(np.int16) - before.astype(np.int16))
        changed_fraction = float(np.mean(np.max(difference, axis=2) > 8))
        mean_difference = float(difference.mean())
        print(json.dumps({
            "input_test": "completed",
            "key": "UP",
            "hold_seconds": args.input_test_seconds,
            "frame_mean_absolute_difference": round(mean_difference, 4),
            "changed_pixel_fraction": round(changed_fraction, 4),
            "visual_change_detected": changed_fraction > 0.01 and mean_difference > 0.5,
            "note": "A positive frame change is evidence of movement/animation, not proof that the key alone caused it."
        }, indent=2), flush=True)
        print("[test] Input test finished. No connectome was loaded.", flush=True)
        return

    pilot = ConnectomePilot(
        args.flyscroll_root, args.scale, args.neural_ms,
        calibrated_drive=args.motion_decoder,
    )
    motion_decoder = None
    motion_window = np.zeros(pilot.brain.n, dtype=np.float32)
    motion_window_count = 0
    motion_result = {"direction": "warming_up", "action": None, "score": 0.0, "margin": 0.0}
    if args.motion_decoder:
        from neural_motor_decoder import NeuralMotionDecoder
        if not args.motion_model.is_file():
            raise FileNotFoundError(f"Motion model not found: {args.motion_model}")
        motion_decoder = NeuralMotionDecoder(args.motion_model, args.motion_minimum_margin)
        if motion_decoder.neuron_count != pilot.brain.n:
            raise RuntimeError(
                f"Motion model expects {motion_decoder.neuron_count} neurons, but loaded brain has {pilot.brain.n}."
            )
        print("[decoder] Trained motion readout enabled. Experimental direction pulses only; no target or combat intelligence.", flush=True)
        if args.allow_experimental_live_control and not args.dry_run:
            print("[warning] EXPERIMENTAL LIVE INPUT ENABLED. The readout has not been validated on Doom gameplay.", flush=True)
    active_keys = set()
    frame_count = 0
    started = time.monotonic()
    last_log = 0.0
    print("[pilot] Connectome loop running. Ctrl+C stops it and releases all keys.", flush=True)
    if motion_decoder is None:
        print("[pilot] Experimental decoder: bilateral visual DNs=steer/forward, DNp09=forward, MDN=reverse, looming DNs=fire.", flush=True)
    else:
        print(f"[pilot] Neural motion readout: {args.motion_window_frames}-frame windows; each confident result emits one turn pulse.", flush=True)
    print("[pilot] GZDoom keys: Up=forward, Down=reverse, Left/Right=turn, Ctrl=fire.", flush=True)

    try:
        while True:
            tick = time.monotonic()
            rgb = capture_client(hwnd, (320, 180))
            rates, features, sim_elapsed, spikes = pilot.step(rgb)
            actions, turn, visual = pilot.decode(rates, args.threshold)
            if motion_decoder is not None:
                motion_window += pilot.last_counts
                motion_window_count += 1
                actions = set()
                if motion_window_count >= args.motion_window_frames:
                    motion_result = motion_decoder.decode(motion_window)
                    if motion_result["action"] == "TURN_LEFT":
                        actions.add("left")
                    elif motion_result["action"] == "TURN_RIGHT":
                        actions.add("right")
                    motion_window.fill(0.0)
                    motion_window_count = 0
            if not args.dry_run:
                for action, vk in KEYS.items():
                    wanted = action in actions
                    held = action in active_keys
                    if wanted and not held:
                        set_key(vk, True)
                        active_keys.add(action)
                        print(f"[input] KEY DOWN {action}", flush=True)
                    elif held and not wanted:
                        set_key(vk, False)
                        active_keys.discard(action)
                        print(f"[input] KEY UP   {action}", flush=True)

            frame_count += 1
            now = time.monotonic()

            # Prepare data for visualization server
            viz_data = {
                "frame": frame_count,
                "fps_actual": round(frame_count / max(0.001, now - started), 2),
                "spikes": spikes,
                "spike_total": pilot.total_spikes,
                "simulation_ms": round(pilot.brain.sim_ms, 1),
                "kernel_ms": round(sim_elapsed * 1000, 2),
                "turn_delta": round(turn, 4),
                "visual_dn": round(visual, 4),
                "rates": {k: round(v, 4) for k, v in rates.items()},
                "frame_luma_mean": round(float(rgb.mean()), 2),
                "frame_luma_std": round(float(rgb.std()), 2),
                "decoded_actions": sorted(actions),
                "motion_decoder": motion_result if motion_decoder is not None else None,
                "motion_window_progress": motion_window_count if motion_decoder is not None else None,
                "actions": sorted(actions) if not args.dry_run else [],
                "features": {k: round(v, 4) for k, v in features.items()},
                "mode": "dry-run" if args.dry_run else "live-control",
                "controller": "neural-motion-readout" if motion_decoder is not None else "legacy-population-heuristic",
            }

            # Post to visualization server
            post_to_viz_server(viz_data)

            if now - last_log >= 1.0:
                print(json.dumps(viz_data), flush=True)
                last_log = now
            if args.frames and frame_count >= args.frames:
                break
            remaining = (1.0 / args.fps) - (time.monotonic() - tick)
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print("\n[pilot] Stop requested.", flush=True)
    finally:
        for action in list(active_keys):
            set_key(KEYS[action], False)
        print(f"[pilot] Stopped after {frame_count} frames; total neural spikes={pilot.total_spikes}.", flush=True)


if __name__ == "__main__":
    main()
