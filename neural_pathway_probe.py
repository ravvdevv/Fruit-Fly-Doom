"""Controlled visual-stimulus probe for FlyScroll descending pathways.

This is a calibration experiment, not a Doom controller. It presents repeatable
synthetic visual stimuli to the existing FlyEye -> MaleCNS pipeline and reports
per-population spike rates plus bilateral readout asymmetry. No game-state labels,
enemy metadata, or handcrafted navigation signals enter the brain.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DEFAULT_FLYSCROLL = Path(r"D:\Experimental-projects\Fucking-fruitfly\Fruitfly-Doomscroller")
POPULATIONS = ("DNa02", "DNp09", "MDN", "DNp20", "DNpe017", "LC11", "LC18", "LC17", "LPLC2", "LC4", "LC6", "VS", "HSN", "HSE", "HSS")


def make_frame(kind: str, index: int, total: int, width: int = 320, height: int = 180) -> np.ndarray:
    frame = np.full((height, width, 3), 88, dtype=np.uint8)
    yy, xx = np.ogrid[:height, :width]
    if kind == "baseline":
        return frame
    if kind in ("bar_left_to_right", "bar_right_to_left"):
        progress = index / max(1, total - 1)
        if kind == "bar_right_to_left":
            progress = 1.0 - progress
        center = int(18 + progress * (width - 36))
        frame[:, max(0, center - 12):min(width, center + 12)] = 235
        return frame
    if kind == "looming":
        radius = int(4 + (index / max(1, total - 1)) * 62)
        mask = (xx - width // 2) ** 2 + (yy - height // 2) ** 2 <= radius ** 2
        frame[mask] = (235, 235, 235)
        return frame
    if kind == "bar_left":
        if index >= total // 4:
            frame[:, 35:59] = 235
        return frame
    if kind == "bar_right":
        if index >= total // 4:
            frame[:, width - 59:width - 35] = 235
        return frame
    raise ValueError(f"Unknown stimulus: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe connectome responses to controlled visual stimuli.")
    parser.add_argument("--flyscroll-root", type=Path, default=Path(r"D:\Experimental-projects\Fucking-fruitfly\Fruitfly-Doomscroller"))
    parser.add_argument("--scale", choices=("full", "visual"), default="full")
    parser.add_argument("--neural-ms", type=float, default=2.0)
    parser.add_argument("--frames-per-condition", type=int, default=120)
    parser.add_argument("--output", type=Path, default=ROOT / "neural_pathway_probe.json")
    args = parser.parse_args()

    if args.neural_ms <= 0 or args.frames_per_condition < 2:
        parser.error("neural-ms must be positive and frames-per-condition must be at least 2.")

    sys.path.insert(0, str(args.flyscroll_root))
    from flyscroll.engine import Brain
    from flyscroll.flyvision import FlyEyeProcessor

    graph = args.flyscroll_root / "outputs" / "flyscroll" / "malecns_v1" / args.scale / "graph.npz"
    manifest_path = graph.with_name("manifest.json")
    if not graph.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"Prepared {args.scale} graph or manifest is missing: {graph}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(
        f"[probe] Loading {manifest['neurons']:,} neurons / {manifest['edges']:,} edges "
        f"({args.scale} graph).",
        flush=True,
    )
    metadata_brain = Brain(graph)
    cell_types = np.asarray(metadata_brain.cell_type).astype(str)
    indices = {name: np.flatnonzero(cell_types == name) for name in POPULATIONS}
    del metadata_brain

    sided = {}
    for item in manifest.get("readouts", []):
        name = str(item.get("type", ""))
        side = str(item.get("side", "")).upper()
        if name in ("DNa02", "DNp09", "MDN", "DNp20", "DNpe017") and side in ("L", "R"):
            sided.setdefault(f"{name}_{side}", []).append(int(item["index"]))
    sided = {key: np.asarray(value, dtype=np.int32) for key, value in sided.items()}

    conditions = ("baseline", "bar_left", "bar_right", "bar_left_to_right", "bar_right_to_left", "looming")
    results = []
    simulated_seconds = args.neural_ms / 1000.0
    for condition in conditions:
        # A fresh network per condition prevents previous stimuli from contaminating
        # the response measured for the next condition.
        brain = Brain(graph)
        eye = FlyEyeProcessor(brain)
        totals = {name: 0 for name in POPULATIONS}
        side_totals = {name: 0 for name in sided}
        total_spikes = 0
        kernel_seconds = 0.0
        feature_totals = {}
        for frame_index in range(args.frames_per_condition):
            rgb = make_frame(condition, frame_index, args.frames_per_condition)
            eye_frame = eye.process(rgb, brain, dt_seconds=simulated_seconds)
            counts, elapsed, _ = brain.step(
                eye_frame.luminance,
                eye_frame.chromatic,
                duration_ms=args.neural_ms,
            )
            kernel_seconds += elapsed
            total_spikes += int(counts.sum())
            for name, value in eye_frame.features.items():
                feature_totals[name] = feature_totals.get(name, 0.0) + float(value)
            for name, population_indices in indices.items():
                if len(population_indices):
                    totals[name] += int(counts[population_indices].sum())
            for name, population_indices in sided.items():
                side_totals[name] += int(counts[population_indices].sum())
        duration = simulated_seconds * args.frames_per_condition
        rates = {
            name: round(spikes / max(1, len(indices[name])) / duration, 5)
            for name, spikes in totals.items()
        }
        side_rates = {
            name: round(spikes / max(1, len(sided[name])) / duration, 5)
            for name, spikes in side_totals.items()
        }
        asymmetry = {}
        for population in ("DNa02", "DNp09", "MDN", "DNp20", "DNpe017"):
            left = side_rates.get(f"{population}_L", 0.0)
            right = side_rates.get(f"{population}_R", 0.0)
            asymmetry[population] = round((right - left) / (right + left + 1e-9), 5)
        row = {
            "condition": condition,
            "frames": args.frames_per_condition,
            "simulated_ms": round(duration * 1000.0, 3),
            "total_spikes": total_spikes,
            "population_hz_per_neuron": rates,
            "readout_hz_per_neuron": side_rates,
            "mean_eye_features": {name: round(value / args.frames_per_condition, 5) for name, value in feature_totals.items()},
            "right_minus_left_normalized": asymmetry,
            "kernel_seconds": round(kernel_seconds, 4),
        }
        results.append(row)
        print(
            f"[probe] {condition:20s} spikes={total_spikes:8d} "
            f"DNa02={rates['DNa02']:.3f} DNp09={rates['DNp09']:.3f} "
            f"MDN={rates['MDN']:.3f} DNp20={rates['DNp20']:.3f} "
            f"DNpe017={rates['DNpe017']:.3f} kernel={kernel_seconds:.2f}s",
            flush=True,
        )

    payload = {
        "experiment": "controlled_visual_stimulus_probe",
        "dataset": manifest.get("dataset"),
        "scale": args.scale,
        "neurons": manifest.get("neurons"),
        "edges": manifest.get("edges"),
        "neural_ms_per_frame": args.neural_ms,
        "frames_per_condition": args.frames_per_condition,
        "conditions": results,
        "interpretation": (
            "Rates are observed responses to synthetic stimuli. A response does not by itself "
            "validate a motor mapping; use left/right contrasts and repeat trials before decoding."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[probe] Wrote {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
