"""Inference-only adapter for a trained connectome motion readout.

This maps a window of connectome spike counts to a left/right visual-motion
classification. It is an experimentally trained external readout, not a
biological descending-neuron motor circuit.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


class NeuralMotionDecoder:
    def __init__(self, model_path: str | Path, minimum_margin: float = 0.0):
        if not np.isfinite(minimum_margin) or minimum_margin < 0:
            raise ValueError("minimum_margin must be finite and non-negative")
        with np.load(Path(model_path), allow_pickle=False) as model:
            self.feature_indices = model["feature_indices"].astype(np.int32)
            self.mean = model["mean"].astype(np.float32)
            self.scale = model["scale"].astype(np.float32)
            self.weight = model["weight"].astype(np.float32)
            self.bias = float(model["bias"][0])
            self.neuron_count = int(model["neuron_count"][0])
        if not (
            len(self.feature_indices) == len(self.mean) == len(self.scale) == len(self.weight)
            and np.all(self.scale > 0)
            and np.all(np.isfinite(self.weight))
            and np.isfinite(self.bias)
        ):
            raise ValueError("Invalid neural motion readout model")
        self.minimum_margin = float(minimum_margin)

    def decode(self, spike_counts: np.ndarray) -> dict:
        counts = np.asarray(spike_counts, dtype=np.float32)
        if counts.shape != (self.neuron_count,) or not np.all(np.isfinite(counts)) or np.any(counts < 0):
            raise ValueError(f"Expected {self.neuron_count} finite non-negative neuron spike counts")
        features = np.log1p(counts[self.feature_indices])
        standardized = (features - self.mean) / self.scale
        score = float(np.dot(standardized, self.weight) + self.bias)
        if abs(score) < self.minimum_margin:
            return {"direction": "undecided", "action": None, "score": score, "margin": abs(score)}
        direction = "right" if score >= 0 else "left"
        return {
            "direction": direction,
            "action": "TURN_RIGHT" if direction == "right" else "TURN_LEFT",
            "score": score,
            "margin": abs(score),
        }
