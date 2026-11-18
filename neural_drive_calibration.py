"""Calibrate visual-to-connectome drive without modifying the upstream FlyScroll engine.

This is a parameter-sweep experiment. It replaces only the engine's default
retinal/lamina current assignment through Brain.step(enrich_drive=...), keeping
the connectome, synaptic weights, neuron dynamics, and visual front end intact.
The current ranges are exploratory model parameters, not measured fly physiology.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
POPULATIONS = ("R1-R6", "L1", "L2", "L3", "L5", "T1", "C2", "C3", "Mi1", "Mi4", "Mi9", "Tm1", "Tm2", "Tm3", "Tm4", "Tm9", "DNp20", "DNpe017", "DNa02", "DNp09", "MDN", "LC11", "LC18", "LC17", "LPLC2", "LC4", "LC6", "VS", "HSN", "HSE", "HSS")
CONDITIONS = ("baseline", "bar_left_to_right", "bar_right_to_left", "looming")
REGIMES = (
    {"name": "graded_mid", "baseline_current": 8.5, "contrast_gain": 10.0, "lamina_current": 8.5},
    {"name": "graded_high", "baseline_current": 9.5, "contrast_gain": 10.0, "lamina_current": 8.5},
    {"name": "graded_contrast", "baseline_current": 8.5, "contrast_gain": 20.0, "lamina_current": 8.5},
    {"name": "lamina_near_threshold", "baseline_current": 8.5, "contrast_gain": 10.0, "lamina_current": 7.5},
)


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
        frame[:, max(0, center - 32):min(width, center + 32)] = 235
        return frame
    if kind == "looming":
        radius = int(4 + (index / max(1, total - 1)) * 62)
        mask = (xx - width // 2) ** 2 + (yy - height // 2) ** 2 <= radius ** 2
        frame[mask] = (235, 235, 235)
        return frame
    raise ValueError(kind)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep exploratory retinal and lamina current gains.")
    parser.add_argument("--flyscroll-root", type=Path, default=Path(r"D:\Experimental-projects\Fucking-fruitfly\Fruitfly-Doomscroller"))
    parser.add_argument("--scale", choices=("full", "visual"), default="full")
    parser.add_argument("--frames-per-condition", type=int, default=120)
    parser.add_argument("--neural-ms", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=ROOT / "neural_drive_calibration.json")
    args = parser.parse_args()
    if args.frames_per_condition < 2 or args.neural_ms <= 0:
        parser.error("frames-per-condition must be >= 2 and neural-ms must be positive")

    sys.path.insert(0, str(args.flyscroll_root))
    from flyscroll.engine import Brain
    from flyscroll.flyvision import FlyEyeProcessor

    graph = args.flyscroll_root / "outputs" / "flyscroll" / "malecns_v1" / args.scale / "graph.npz"
    manifest = json.loads(graph.with_name("manifest.json").read_text(encoding="utf-8"))
    metadata = Brain(graph)
    cell_types = np.asarray(metadata.cell_type).astype(str)
    superclasses = np.asarray(metadata.superclass).astype(str)
    superclass_names, superclass_inverse = np.unique(superclasses, return_inverse=True)
    population_indices = {name: np.flatnonzero(cell_types == name) for name in POPULATIONS}
    readouts = {}
    for item in manifest.get("readouts", []):
        name = str(item.get("type", ""))
        side = str(item.get("side", "")).upper()
        if name in ("DNa02", "DNp09", "MDN", "DNp20", "DNpe017") and side in ("L", "R"):
            readouts.setdefault(f"{name}_{side}", []).append(int(item["index"]))
    readouts = {key: np.asarray(value, dtype=np.int32) for key, value in readouts.items()}
    del metadata

    results = []
    for regime in REGIMES:
        for condition in CONDITIONS:
            brain = Brain(graph)
            eye = FlyEyeProcessor(brain)
            totals = {name: 0 for name in POPULATIONS}
            side_totals = {name: 0 for name in readouts}
            total_spikes = 0
            superclass_spikes = np.zeros(len(superclass_names), dtype=np.int64)
            retina_spikes = 0
            lamina_spikes = 0
            chromatic_spikes = 0
            feature_totals: dict[str, float] = {}
            drive_samples = []

            def inject_calibrated_drive(network):
                # Centre contrast around the calibrated photoreceptor operating point.
                # This deliberately avoids the original saturating 30*x/(0.02+x)
                # transfer while we measure whether contrast reaches downstream cells.
                delta = network.luminance - np.float32(0.32)
                retinal = regime["baseline_current"] + regime["contrast_gain"] * delta
                network.drive[network.retina] = np.clip(retinal, 0.0, 12.0)
                network.drive[network.lamina] = regime["lamina_current"]
                network.drive[network.chromatic] = 0.0
                drive_samples.append((float(np.min(retinal)), float(np.mean(retinal)), float(np.max(retinal))))
                return {"drive_regime": regime["name"]}

            for frame_index in range(args.frames_per_condition):
                rgb = make_frame(condition, frame_index, args.frames_per_condition)
                eye_frame = eye.process(rgb, brain, dt_seconds=args.neural_ms / 1000.0)
                counts, _, _ = brain.step(
                    eye_frame.luminance,
                    eye_frame.chromatic,
                    duration_ms=args.neural_ms,
                    enrich_drive=inject_calibrated_drive,
                )
                total_spikes += int(counts.sum())
                superclass_spikes += np.bincount(superclass_inverse, weights=counts, minlength=len(superclass_names)).astype(np.int64)
                retina_spikes += int(counts[brain.retina].sum())
                lamina_spikes += int(counts[brain.lamina].sum())
                chromatic_spikes += int(counts[brain.chromatic].sum())
                for key, value in eye_frame.features.items():
                    feature_totals[key] = feature_totals.get(key, 0.0) + float(value)
                for name, indices in population_indices.items():
                    if len(indices):
                        totals[name] += int(counts[indices].sum())
                for name, indices in readouts.items():
                    side_totals[name] += int(counts[indices].sum())

            seconds = args.frames_per_condition * args.neural_ms / 1000.0
            rates = {
                name: round(spikes / max(1, len(population_indices[name])) / seconds, 5)
                for name, spikes in totals.items()
            }
            side_rates = {
                name: round(spikes / max(1, len(readouts[name])) / seconds, 5)
                for name, spikes in side_totals.items()
            }
            asymmetry = {}
            for population in ("DNa02", "DNp09", "MDN", "DNp20", "DNpe017"):
                left = side_rates.get(f"{population}_L", 0.0)
                right = side_rates.get(f"{population}_R", 0.0)
                asymmetry[population] = round((right - left) / (right + left + 1e-9), 5)
            result = {
                "regime": dict(regime),
                "condition": condition,
                "total_spikes": total_spikes,
                "retina_spikes": retina_spikes,
                "lamina_spikes": lamina_spikes,
                "chromatic_spikes": chromatic_spikes,
                "superclass_spikes": {str(name): int(superclass_spikes[i]) for i, name in enumerate(superclass_names) if superclass_spikes[i]},
                "population_hz_per_neuron": rates,
                "readout_hz_per_neuron": side_rates,
                "right_minus_left_normalized": asymmetry,
                "mean_eye_features": {key: round(value / args.frames_per_condition, 6) for key, value in feature_totals.items()},
                "retinal_drive_min_mean_max": [round(float(np.mean([x[i] for x in drive_samples])), 5) for i in range(3)],
            }
            results.append(result)
            print(
                f"[cal] {regime['name']:10s} {condition:20s} spikes={total_spikes:9d} "
                f"DNp20={rates['DNp20']:.3f} DNpe017={rates['DNpe017']:.3f} "
                f"DNa02={rates['DNa02']:.3f} DNp09={rates['DNp09']:.3f} MDN={rates['MDN']:.3f}",
                flush=True,
            )

    payload = {
        "experiment": "retinal_drive_parameter_sweep",
        "dataset": manifest.get("dataset"),
        "scale": args.scale,
        "neurons": manifest.get("neurons"),
        "edges": manifest.get("edges"),
        "frames_per_condition": args.frames_per_condition,
        "neural_ms_per_frame": args.neural_ms,
        "warning": "Drive regimes are exploratory engineering parameters, not physiologically calibrated values.",
        "results": results,
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[cal] wrote {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
