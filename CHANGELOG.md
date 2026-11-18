# Changelog

## 2026-11-18

### Repository cleanup and layout
- Grouped research scripts and committed reference outputs under `experiments/`.
- Moved the standalone browser raycaster into `prototypes/browser-raycaster/` to distinguish it from the real game bridge.
- Removed one-off test/debug scripts, the old input-test launcher, local logs, and temporary diagnostic files.
- Replaced machine-specific FlyScroll paths with a neighboring-checkout default and `FLYSCROLL_ROOT` override.
- Updated experiment output paths so new runs do not overwrite committed reference results.
- Rewrote the README with a beginner-friendly project explanation and repository map.

### Neural-control calibration and readout experiments
- Added an opt-in `--motion-decoder` path to `connectome_doom.py`. It requires the full 166,700-neuron graph, applies the same exploratory drive regime as the trained readout, accumulates calibrated 20-frame spike windows, and emits one-frame left/right turn pulses. The existing legacy decoder remains the default. This mode is experimental and must be evaluated in dry-run against real Doom footage before live control.
- Added `neural_drive_calibration.py` to sweep retinal and lamina current through the existing `Brain.step(enrich_drive=...)` hook without modifying the upstream FlyScroll engine.
- Identified that the default retinal transfer is near saturation at the front end's baseline receptor luminance (~0.32), while the default lamina current is constant and scene-independent.
- Added `neural_motion_decode.py`, a held-out-trial linear readout over full-connectome spike-count windows. Across 10 trials (5 per direction), the neural population decoded left/right motion at 78.3%; exact balanced trial-label permutation p=0.00794. This is evidence of motion information, not a biological motor mapping.
- Added `neural_motor_decoder.py` and saved a trained `neural_motion_readout.npz` artifact. It converts a calibrated 20-frame neural spike window into an experimental left/right motion-following command. An opt-in Doom bridge now consumes the trained readout, but gameplay generalization and static target localization remain unvalidated.
- Added `calibrated_flyvision.py` with an experimental local center-surround contrast wrapper; upstream FlyScroll files remain unchanged.
- Added `neural_target_decode.py` to test static left/right target localization. Initial full-connectome neural accuracy was 53.1% over 8 trials (permutation p=0.2), so target localization remains unproven.
- No neural-only Doom controller enabled. Motion readout requires further generalization tests; static spatial decoding and a validated motor mapping remain blockers.

## 2026-11-17

### Neural pathway calibration foundation
- Added `neural_pathway_probe.py`, a controlled-stimulus experiment for the full or visual FlyScroll graph.
- Probes baseline, static left/right objects, left/right motion, and looming while recording population rates, bilateral descending readouts, and FlyEye feature responses.
- Uses a fresh brain instance per condition to avoid cross-condition neural-state contamination.
- Full-connectome probes up to 300 frames per condition confirm that FlyEye motion features distinguish opposite bar directions, but DNa02, DNp09, and MDN remain silent while DNp20/DNpe017 show little stimulus-specific change.
- Directed graph reachability confirms the candidate descending populations are structurally reachable from retinal input; the remaining issue is dynamic propagation / stimulus encoding, not absent graph paths.
- No neural-only controller was enabled: motor decoding is gated on measured, repeatable pathway responses rather than guessed mappings.

### Autonomous pilot navigation and recovery fix
- Corrected waypoint bearing calculations to match Doom's angle convention (0° east, increasing counter-clockwise); the old formula steered toward rotated/misdirected headings and caused route oscillation.
- Added an explicit reverse + strafe + turn escape maneuver after 14 decisions without meaningful position change.
- Clear the locked target and temporarily exclude the unreachable goal sector so navigation does not immediately retry the same blocked route.
- Detect doorway oscillation even when coordinates keep changing: if the agent spends 80 decisions in the same map sector while targeting another sector, it abandons that goal and replans.
- Added deterministic test coverage for the stuck-state transition.

### Dashboard UI refresh
- Rebuilt the dashboard hierarchy with a clearer editorial-style experiment header, compact telemetry metrics, and consistent panel headers.
- Refined the dark visual system with restrained cyan/blue accents, quieter borders, stronger typography, and more deliberate spacing.
- Improved the live Doom viewport, model stage, neural activity panel, sensory telemetry, and decision card.
- Added mobile/tablet layouts, reduced-motion support, clearer loading states, health-critical emphasis, and a one-click 3D camera reset.
- Preserved existing API element IDs and simulation behavior.

### Added
- Replaced the dashboard's illustrated fly with the research-derived NeuroMechFly v2 anatomical model.
- Loads the model rig metadata and 39 unique STL meshes from the upstream fly-svg-maker asset mirror (Apache-2.0 model assets).
- Added interactive pointer-drag orbit and mouse-wheel zoom.
- Connected Doom controller actions to the model's wing, leg, head, and body pose animation.
- Added loading/error status and visible model attribution in the dashboard.

### Notes
- Three.js and the research model assets are loaded from jsDelivr at runtime; the dashboard needs an internet connection for the 3D model.
- The model is a visual rig driven by Doom action telemetry, not a full physics-based insect simulation or proof that the connectome independently controls each joint.
- The original FlyScroll-Doomscroller project was not modified.
