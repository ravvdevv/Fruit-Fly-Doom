"""Experimental spatial-contrast wrapper for the upstream FlyEyeProcessor.

The upstream front end adapts each receptor to its own long-term luminance. That
can suppress a stationary object after adaptation. This wrapper preserves the
upstream temporal/motion features but replaces the receptor drive with a local
center-surround contrast signal computed from the current image. It is an
explicit engineering hypothesis, not a claim of measured fly photoreceptor
physiology.
"""
from __future__ import annotations

import numpy as np

from flyscroll.flyvision import FlyEyeFrame, FlyEyeProcessor
from flyscroll.retina import _linearize, _sample

_LUMA = np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)


class SpatialContrastFlyEyeProcessor(FlyEyeProcessor):
    """Retain static local contrast while reusing upstream temporal features."""

    def __init__(self, brain, contrast_gain: float = 0.28):
        super().__init__(brain)
        if not np.isfinite(contrast_gain) or contrast_gain <= 0:
            raise ValueError("contrast_gain must be a positive finite number")
        self.spatial_contrast_gain = float(contrast_gain)

    def process(self, rgb: np.ndarray, brain, dt_seconds: float = 0.05) -> FlyEyeFrame:
        temporal = super().process(rgb, brain, dt_seconds=dt_seconds)
        linear = _linearize(rgb)
        column_rgb = _sample(linear, self.uv)
        luminance = (column_rgb @ _LUMA).astype(np.float32)

        if self.neighbours.shape[1]:
            surround = luminance[self.neighbours]
            local_mean = surround.mean(axis=1)
            local_scale = np.sqrt(
                np.mean((surround - local_mean[:, None]) ** 2, axis=1)
            )
        else:
            local_mean = np.zeros_like(luminance)
            local_scale = np.zeros_like(luminance)

        spatial_contrast = np.clip(
            (luminance - local_mean) / (0.08 + local_scale),
            -3.0,
            3.0,
        )
        receptor_signal = np.clip(
            0.32 + self.spatial_contrast_gain * spatial_contrast,
            0.0,
            1.0,
        )
        receptor_luminance = receptor_signal[self.receptor_to_column].astype(np.float32)

        return FlyEyeFrame(
            luminance=receptor_luminance,
            chromatic=temporal.chromatic,
            features={
                **temporal.features,
                "spatial_contrast": float(np.mean(np.abs(spatial_contrast))),
            },
            feature_vector=np.r_[
                temporal.feature_vector,
                np.asarray([np.mean(np.abs(spatial_contrast))], dtype=np.float32),
            ],
            column_rgb=temporal.column_rgb,
            column_activity=np.maximum(
                temporal.column_activity,
                np.rint(np.clip(np.abs(spatial_contrast), 0.0, 1.0) * 255).astype(np.uint8),
            ),
        )
