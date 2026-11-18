"""Held-out-trial decoder for left/right visual target location.

A uniform baseline is shown before a static high-contrast target appears on one
side. Only connectome spike counts are used for the neural readout. This tests
whether the current visual-to-connectome pipeline preserves coarse target-side
information; it is not yet a motor decoder.
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DEFAULT_FLYSCROLL = Path(r"D:\Experimental-projects\Fucking-fruitfly\Fruitfly-Doomscroller")


def make_frame(side: int, onset: bool, x: int, y: int, width: int, height: int) -> np.ndarray:
    frame = np.full((180, 320, 3), 88, dtype=np.uint8)
    if onset:
        frame[y:y + height, x:x + width] = 235
    return frame


def grouped_readout(samples: np.ndarray, labels: np.ndarray, groups: np.ndarray) -> dict:
    predictions = np.zeros(len(labels), dtype=np.int8)
    folds = []
    for held_out in np.unique(groups):
        train = groups != held_out
        test = ~train
        x_train = samples[train].astype(np.float64)
        x_test = samples[test].astype(np.float64)
        y_train = labels[train]
        mean = x_train.mean(axis=0)
        scale = x_train.std(axis=0)
        active = scale > 1e-6
        if not np.any(active):
            folds.append({"trial": int(held_out), "accuracy": 0.5, "active_features": 0})
            continue
        z_train = (x_train[:, active] - mean[active]) / scale[active]
        z_test = (x_test[:, active] - mean[active]) / scale[active]
        left = z_train[y_train < 0].mean(axis=0)
        right = z_train[y_train > 0].mean(axis=0)
        weight = right - left
        bias = -0.5 * float(np.dot(right + left, weight))
        predicted = np.where(z_test @ weight + bias >= 0, 1, -1)
        predictions[test] = predicted
        folds.append({"trial": int(held_out), "accuracy": round(float(np.mean(predicted == labels[test])), 4), "active_features": int(active.sum())})
    return {"accuracy": round(float(np.mean(predictions == labels)), 4), "predictions": predictions.tolist(), "folds": folds}


def permutation_test(samples: np.ndarray, groups: np.ndarray, observed: float) -> dict:
    unique = np.unique(groups)
    if len(unique) > 12 or len(unique) % 2:
        return {"p_value": None, "permutations": 0}
    scores = []
    for left in combinations(unique.tolist(), len(unique) // 2):
        labels = np.where(np.isin(groups, left), -1, 1)
        scores.append(grouped_readout(samples, labels, groups)["accuracy"])
    return {
        "p_value": round(sum(score >= observed for score in scores) / len(scores), 5),
        "permutations": len(scores),
        "null_accuracy_mean": round(float(np.mean(scores)), 5),
        "null_accuracy_95th_percentile": round(float(np.quantile(scores, 0.95)), 5),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode left/right target location from connectome activity.")
    parser.add_argument("--flyscroll-root", type=Path, default=DEFAULT_FLYSCROLL)
    parser.add_argument("--scale", choices=("full", "visual"), default="full")
    parser.add_argument("--trials-per-side", type=int, default=5)
    parser.add_argument("--baseline-frames", type=int, default=20)
    parser.add_argument("--target-frames", type=int, default=60)
    parser.add_argument("--window-frames", type=int, default=5)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--frontend", choices=("original", "spatial"), default="spatial")
    parser.add_argument("--retinal-baseline-current", type=float, default=8.5)
    parser.add_argument("--retinal-contrast-gain", type=float, default=20.0)
    parser.add_argument("--lamina-current", type=float, default=7.5)
    parser.add_argument("--output", type=Path, default=ROOT / "neural_target_decode.json")
    args = parser.parse_args()
    if args.trials_per_side < 2 or args.baseline_frames < 1 or args.target_frames < args.window_frames:
        parser.error("Need >=2 trials per side, baseline-frames >=1 and target-frames >= window-frames.")

    sys.path.insert(0, str(args.flyscroll_root))
    from flyscroll.engine import Brain
    from flyscroll.flyvision import FlyEyeProcessor
    from calibrated_flyvision import SpatialContrastFlyEyeProcessor

    graph = args.flyscroll_root / "outputs" / "flyscroll" / "malecns_v1" / args.scale / "graph.npz"
    manifest = json.loads(graph.with_name("manifest.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(args.seed)
    neural_samples, eye_samples, labels, groups = [], [], [], []
    trials = []

    for trial in range(args.trials_per_side * 2):
        side = -1 if trial < args.trials_per_side else 1
        if side < 0:
            x = int(rng.integers(35, 115))
        else:
            x = int(rng.integers(205, 285))
        width = int(rng.integers(36, 65))
        height = int(rng.integers(70, 145))
        y = int(rng.integers(10, 180 - height))
        brain = Brain(graph)
        eye_class = SpatialContrastFlyEyeProcessor if args.frontend == "spatial" else FlyEyeProcessor
        eye = eye_class(brain)
        window_spikes = np.zeros(brain.n, dtype=np.float32)
        window_eye = np.zeros(len(eye.FEATURE_NAMES) + (1 if args.frontend == "spatial" else 0), dtype=np.float32)
        window_count = 0
        total_spikes = 0
        retina_left_spikes = 0
        retina_right_spikes = 0
        retina_left_mask = brain.uv[:, 0] < float(np.median(brain.uv[:, 0]))

        def calibrated_drive(network):
            delta = network.luminance - np.float32(0.32)
            network.drive[network.retina] = np.clip(
                args.retinal_baseline_current + args.retinal_contrast_gain * delta, 0.0, 30.0
            )
            network.drive[network.lamina] = args.lamina_current
            network.drive[network.chromatic] = 0.0
            return None

        total_frames = args.baseline_frames + args.target_frames
        for frame_index in range(total_frames):
            visible = frame_index >= args.baseline_frames
            rgb = make_frame(side, visible, x, y, width, height)
            eye_frame = eye.process(rgb, brain, dt_seconds=0.002)
            counts, _, _ = brain.step(
                eye_frame.luminance,
                eye_frame.chromatic,
                duration_ms=2.0,
                enrich_drive=calibrated_drive,
            )
            if visible:
                window_spikes += counts
                window_eye += eye_frame.feature_vector
                window_count += 1
                total_spikes += int(counts.sum())
                retina_counts = counts[brain.retina]
                retina_left_spikes += int(retina_counts[retina_left_mask].sum())
                retina_right_spikes += int(retina_counts[~retina_left_mask].sum())
                if window_count == args.window_frames or frame_index == total_frames - 1:
                    neural_samples.append(np.log1p(window_spikes))
                    eye_samples.append(window_eye / window_count)
                    labels.append(side)
                    groups.append(trial)
                    window_spikes.fill(0)
                    window_eye.fill(0)
                    window_count = 0

        trials.append({
            "trial": trial,
            "target_side": "right" if side > 0 else "left",
            "target_rect": [x, y, width, height],
            "target_period_spikes": total_spikes,
            "retina_left_spikes": retina_left_spikes,
            "retina_right_spikes": retina_right_spikes,
        })
        print(
            f"[target] trial {trial + 1}/{args.trials_per_side * 2} "
            f"side={'right' if side > 0 else 'left'} spikes={total_spikes}",
            flush=True,
        )

    neural_matrix = np.asarray(neural_samples)
    eye_matrix = np.asarray(eye_samples)
    labels_array = np.asarray(labels)
    groups_array = np.asarray(groups)
    neural = grouped_readout(neural_matrix, labels_array, groups_array)
    eye = grouped_readout(eye_matrix, labels_array, groups_array)
    neural["exact_trial_permutation_test"] = permutation_test(neural_matrix, groups_array, neural["accuracy"])
    eye["exact_trial_permutation_test"] = permutation_test(eye_matrix, groups_array, eye["accuracy"])
    payload = {
        "experiment": "held_out_trial_static_target_side_decode",
        "dataset": manifest.get("dataset"),
        "scale": args.scale,
        "neurons": manifest.get("neurons"),
        "edges": manifest.get("edges"),
        "input_drive": {
            "retinal_baseline_current": args.retinal_baseline_current,
            "retinal_contrast_gain": args.retinal_contrast_gain,
            "lamina_current": args.lamina_current,
            "warning": "Exploratory model parameters, not physiologically calibrated values.",
        },
        "frontend": args.frontend,
        "baseline_frames": args.baseline_frames,
        "target_frames": args.target_frames,
        "window_frames": args.window_frames,
        "trials": trials,
        "neural_population_readout": neural,
        "eye_feature_sanity_check": eye,
        "interpretation": (
            "This tests whether simulated neural population activity contains coarse target-side "
            "information under the chosen stimulus and input regime. It does not validate a biological "
            "motor mapping or autonomous gameplay."
        ),
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"[target] neural accuracy={neural['accuracy']:.3f}; eye accuracy={eye['accuracy']:.3f}; "
        f"wrote {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
