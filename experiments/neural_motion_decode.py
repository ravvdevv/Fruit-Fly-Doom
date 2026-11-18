"""Test whether full-connectome activity contains decodable visual motion direction.

A held-out-trial linear readout is trained on neural spike-count vectors. The
FlyEye feature vector is measured separately as a front-end sanity check but is
never injected into the connectome. This is an information-decoding experiment,
not a motor decoder or proof of biological behavior.
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_FLYSCROLL = ROOT.parent / "Fruitfly-Doomscroller"


def make_frame(direction: int, frame_index: int, total: int, bar_width: int, speed: float) -> np.ndarray:
    height, width = 180, 320
    frame = np.full((height, width, 3), 88, dtype=np.uint8)
    travel = max(1.0, width - bar_width)
    progress = min(1.0, frame_index * speed / travel)
    if direction < 0:
        progress = 1.0 - progress
    left = int(round(progress * travel))
    frame[:, left:left + bar_width] = 235
    return frame


def grouped_linear_readout(samples: np.ndarray, labels: np.ndarray, groups: np.ndarray) -> dict:
    predictions = np.zeros(len(labels), dtype=np.int8)
    scores = np.zeros(len(labels), dtype=np.float64)
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
        fold_scores = z_test @ weight + bias
        fold_predictions = np.where(fold_scores >= 0, 1, -1)
        predictions[test] = fold_predictions
        scores[test] = fold_scores
        folds.append({
            "trial": int(held_out),
            "accuracy": round(float(np.mean(fold_predictions == labels[test])), 4),
            "active_features": int(active.sum()),
        })
    return {
        "accuracy": round(float(np.mean(predictions == labels)), 4),
        "predictions": predictions.tolist(),
        "scores": np.round(scores, 5).tolist(),
        "folds": folds,
    }


def exact_group_permutation_test(samples: np.ndarray, groups: np.ndarray, observed_accuracy: float) -> dict:
    unique_groups = np.unique(groups)
    if len(unique_groups) > 12 or len(unique_groups) % 2:
        return {"p_value": None, "permutations": 0, "reason": "Exact balanced permutation test requires an even number of <=12 trials."}
    scores = []
    half = len(unique_groups) // 2
    for left_groups in combinations(unique_groups.tolist(), half):
        permuted_labels = np.where(np.isin(groups, left_groups), -1, 1)
        scores.append(grouped_linear_readout(samples, permuted_labels, groups)["accuracy"])
    exceed = sum(score >= observed_accuracy for score in scores)
    return {
        "p_value": round(exceed / len(scores), 5),
        "permutations": len(scores),
        "null_accuracy_mean": round(float(np.mean(scores)), 5),
        "null_accuracy_95th_percentile": round(float(np.quantile(scores, 0.95)), 5),
        "observed_accuracy": round(float(observed_accuracy), 5),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode motion direction from connectome spike activity.")
    parser.add_argument("--flyscroll-root", type=Path, default=DEFAULT_FLYSCROLL)
    parser.add_argument("--scale", choices=("full", "visual"), default="full")
    parser.add_argument("--trials-per-direction", type=int, default=3)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--window-frames", type=int, default=10)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--retinal-baseline-current", type=float, default=8.5)
    parser.add_argument("--retinal-contrast-gain", type=float, default=20.0)
    parser.add_argument("--lamina-current", type=float, default=8.5)
    parser.add_argument("--frontend", choices=("original", "spatial"), default="spatial")
    parser.add_argument("--model-output", type=Path, default=ROOT / "neural_motion_readout.npz")
    parser.add_argument("--samples-output", type=Path, default=ROOT / "neural_motion_samples.npz")
    parser.add_argument("--output", type=Path, default=ROOT / "experiments" / "results" / "latest" / "neural_motion_decode.json")
    args = parser.parse_args()
    if args.trials_per_direction < 2 or args.frames < args.window_frames or args.window_frames < 1:
        parser.error("Need >=2 trials per direction and frames >= window-frames >= 1.")

    sys.path.insert(0, str(args.flyscroll_root))
    from flyscroll.engine import Brain
    from flyscroll.flyvision import FlyEyeProcessor
    from calibrated_flyvision import SpatialContrastFlyEyeProcessor

    graph = args.flyscroll_root / "outputs" / "flyscroll" / "malecns_v1" / args.scale / "graph.npz"
    manifest = json.loads(graph.with_name("manifest.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(args.seed)
    neural_samples, neural_counts, eye_samples, labels, groups = [], [], [], [], []
    trial_summaries = []
    trial_count = args.trials_per_direction * 2

    for trial in range(trial_count):
        direction = -1 if trial < args.trials_per_direction else 1
        trial_in_class = trial % args.trials_per_direction
        bar_width = int(rng.integers(40, 89))
        speed = float(rng.uniform(1.4, 3.4))
        brain = Brain(graph)
        eye_class = SpatialContrastFlyEyeProcessor if args.frontend == "spatial" else FlyEyeProcessor
        eye = eye_class(brain)
        window_spikes = np.zeros(brain.n, dtype=np.float32)
        window_eye = np.zeros(len(eye.FEATURE_NAMES) + (1 if args.frontend == "spatial" else 0), dtype=np.float32)
        frames_in_window = 0
        total_spikes = 0

        def calibrated_drive(network):
            delta = network.luminance - np.float32(0.32)
            network.drive[network.retina] = np.clip(
                args.retinal_baseline_current + args.retinal_contrast_gain * delta, 0.0, 30.0
            )
            network.drive[network.lamina] = args.lamina_current
            network.drive[network.chromatic] = 0.0
            return None

        for frame_index in range(args.frames):
            rgb = make_frame(direction, frame_index, args.frames, bar_width, speed)
            eye_frame = eye.process(rgb, brain, dt_seconds=0.002)
            counts, _, _ = brain.step(
                eye_frame.luminance,
                eye_frame.chromatic,
                duration_ms=2.0,
                enrich_drive=calibrated_drive,
            )
            window_spikes += counts
            window_eye += eye_frame.feature_vector
            total_spikes += int(counts.sum())
            frames_in_window += 1
            if frames_in_window == args.window_frames or frame_index == args.frames - 1:
                neural_counts.append(window_spikes.copy())
                neural_samples.append(np.log1p(window_spikes))
                eye_samples.append(window_eye / frames_in_window)
                labels.append(direction)
                groups.append(trial)
                window_spikes.fill(0)
                window_eye.fill(0)
                frames_in_window = 0

        trial_summaries.append({
            "trial": trial,
            "direction": "right" if direction > 0 else "left",
            "bar_width_px": bar_width,
            "speed_px_per_frame": round(speed, 4),
            "total_spikes": total_spikes,
        })
        print(
            f"[decode] trial {trial + 1}/{trial_count} direction={'right' if direction > 0 else 'left'} "
            f"width={bar_width}px speed={speed:.2f}px/frame spikes={total_spikes}",
            flush=True,
        )

    neural_matrix = np.asarray(neural_samples)
    eye_matrix = np.asarray(eye_samples)
    label_array = np.asarray(labels)
    group_array = np.asarray(groups)
    neural = grouped_linear_readout(neural_matrix, label_array, group_array)
    eye = grouped_linear_readout(eye_matrix, label_array, group_array)
    neural["exact_trial_permutation_test"] = exact_group_permutation_test(
        neural_matrix, group_array, neural["accuracy"]
    )
    eye["exact_trial_permutation_test"] = exact_group_permutation_test(
        eye_matrix, group_array, eye["accuracy"]
    )

    # Fit the final linear readout on all calibration trials for later inference.
    model_mean = neural_matrix.mean(axis=0)
    model_scale = neural_matrix.std(axis=0)
    model_active = model_scale > 1e-6
    model_z = (neural_matrix[:, model_active] - model_mean[model_active]) / model_scale[model_active]
    model_left = model_z[label_array < 0].mean(axis=0)
    model_right = model_z[label_array > 0].mean(axis=0)
    model_weight = model_right - model_left
    model_bias = -0.5 * float(np.dot(model_right + model_left, model_weight))
    np.savez_compressed(
        args.model_output,
        feature_indices=np.flatnonzero(model_active).astype(np.int32),
        mean=model_mean[model_active].astype(np.float32),
        scale=model_scale[model_active].astype(np.float32),
        weight=model_weight.astype(np.float32),
        bias=np.asarray([model_bias], dtype=np.float32),
        neuron_count=np.asarray([neural_matrix.shape[1]], dtype=np.int32),
    )
    np.savez_compressed(
        args.samples_output,
        spike_counts=np.asarray(neural_counts, dtype=np.float32),
        labels=label_array.astype(np.int8),
        groups=group_array.astype(np.int16),
    )
    payload = {
        "experiment": "held_out_trial_visual_motion_direction_decode",
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
        "trials_per_direction": args.trials_per_direction,
        "frontend": args.frontend,
        "frames_per_trial": args.frames,
        "window_frames": args.window_frames,
        "trial_summaries": trial_summaries,
        "model_output": str(args.model_output),
        "samples_output": str(args.samples_output),
        "neural_population_readout": neural,
        "eye_feature_sanity_check": eye,
        "interpretation": (
            "Held-out-trial decoding measures whether the simulated neural population contains "
            "direction information under this stimulus and drive regime. It does not validate "
            "a motor mapping, biological accuracy, or autonomous control."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"[decode] neural accuracy={neural['accuracy']:.3f}; "
        f"eye-feature accuracy={eye['accuracy']:.3f}; model={args.model_output}; wrote {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
