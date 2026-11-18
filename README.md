# Fruit Fly Doom

**An experimental fruit-fly connectome meets DOOM project.** This repository explores whether neural activity from the FlyScroll *Drosophila* MaleCNS connectome can be driven by visual input from a Doom-like environment and decoded into simple game actions.

The project combines computational neuroscience, connectome simulation, computer vision, neural readouts, and the classic DOOM engine. It is a research prototype, not a claim that a biological fruit fly can independently play DOOM.

> **Research status:** A small controlled moving-bar experiment found motion-direction information in simulated connectome activity. The experimental decoder has an opt-in Doom bridge, but it has **not yet been validated on real Doom gameplay footage**. Reliable target localization and autonomous neural-only gameplay are not demonstrated.

## What is in this repository?

- **FlyScroll connectome bridge** — feeds captured game frames through the FlyEye visual front end and MaleCNS neural simulation.
- **Experimental neural motion readout** — a supervised linear decoder that reads spike-count windows and emits left/right turn predictions.
- **Adventure pilot** — a separate hand-written game policy that uses ViZDoom game metadata for navigation and combat, with connectome activity contributing a bounded exploration bias.
- **Neural experiments** — scripts for stimulus probes, retinal/lamina drive calibration, motion-direction decoding, and target-side decoding.
- **Live dashboards** — browser views for game state, neural population activity, FlyEye features, and an animated fly visualization.
- **Browser prototype** — a small standalone raycaster prototype; it is not the connectome-controlled Freedoom environment.

## Architecture

```text
DOOM / Freedoom framebuffer
          |
          v
   RGB frame capture
          |
          v
 FlyEye visual processing
          |
          v
 FlyScroll MaleCNS connectome
          |
          v
 Neural population spike counts
          |
          v
 Experimental motion readout
          |
          v
 Left / right turn pulse (experimental)
```

The experimental motion decoder currently handles only a narrow motion-direction task. It does not provide robust object recognition, target localization, navigation, aiming, firing, or autonomous level completion.

The separate AdventurePilot is not a neural-only agent: it uses a hand-written policy and ViZDoom's object/sector information. The connectome is an exploration-bias signal, not the sole source of its decisions.

## Research results and limitations

### Motion-direction decoding

An initial experiment used 10 controlled trials (5 per direction), held-out-trial evaluation, and an exact balanced trial-label permutation test:

| Measure | Initial result |
| --- | ---: |
| Connectome population readout accuracy | 78.3% |
| FlyEye feature sanity-check accuracy | 80.0% |
| Exact permutation p-value | 0.00794 |

These are preliminary results from synthetic moving-bar stimuli under one exploratory input-current regime. They are **not** Doom gameplay accuracy, biological validation, or proof of generalization. More independent trials, randomized stimulus parameters, cross-stimulus tests, and appropriate controls are needed.

### Target-side decoding

The initial static left/right target experiment reached 53.1% accuracy across 8 trials, with permutation p = 0.2. That is not convincing evidence of reliable target localization.

### Biological interpretation

The retinal and lamina currents used in calibration are exploratory engineering settings, not measured physiological parameters. The trained motion readout is a supervised external decoder, not a validated descending-neuron-to-motor circuit. The animated fly is a visualization, not a physics-based locomotion simulation.

## Requirements

- Windows 10/11 (the supplied launch scripts are Windows batch files)
- Python 3.11 for the original FlyScroll environment
- A separate checkout of [Fruitfly-Doomscroller](https://github.com/ravvdevv/Fruitfly-Doomscroller), including its prepared MaleCNS graph and Python environment
- GZDoom
- Freedoom Phase 1 (IWAD)
- Python packages listed in `requirements-viz.txt` for the visualization server

The GZDoom engine and Freedoom IWAD are intentionally **not committed** to this repository. Download them from their official project sources and place the extracted files in the expected folders:

- GZDoom: [ZDoom downloads](https://zdoom.org/downloads)
- Freedoom: [Freedoom releases](https://github.com/freedoom/freedoom/releases)

Expected local paths:

```text
gzdoom-4-14-2-windows/
  gzdoom.exe
freedoom-0.13.0/
  freedoom1.wad
```

The connectome bridge also expects the original FlyScroll checkout at:

```text
../Fruitfly-Doomscroller/
```

In particular, its Python 3.11 environment and prepared visual graph must be available. See that project's own setup instructions for preparing them.

## Run

### 1. Launch Freedoom by itself

After installing GZDoom and Freedoom in the expected folders:

```bat
launch-freedoom.bat
```

### 2. Run the existing AdventurePilot

```bat
play-flyscroll-adventure.bat
```

Or run it directly from the original FlyScroll Python environment:

```bat
..\Fruitfly-Doomscroller\.venv\Scripts\python.exe play_flyscroll_adventure.py --connectome --god-mode --skill 0
```

This is a connectome-assisted, hand-written policy. It uses game metadata to identify enemies and navigate.

### 3. Run the experimental neural motion decoder in dry-run mode

Start with observation only. Dry-run mode processes frames and reports predictions without sending keyboard input:

```bat
run-connectome-doom.bat --scale full --motion-decoder --dry-run --frames 200
```

The motion decoder requires the full 166,700-neuron graph and the trained `neural_motion_readout.npz` file. Live keyboard control is deliberately gated behind `--allow-experimental-live-control`, because the readout has not been validated on Doom footage.

Useful options:

| Option | Purpose |
| --- | --- |
| `--motion-decoder` | Enable the experimental trained motion-direction readout |
| `--motion-window-frames 20` | Frames accumulated for each spike-count window |
| `--motion-minimum-margin 0.0` | Optional readout confidence margin |
| `--motion-model PATH` | Use a different trained readout file |
| `--dry-run` | Do not send keyboard input |
| `--frames 200` | Stop after a fixed number of captured frames |
| `--scale full` | Load the full connectome required by the motion readout |
| `--no-viz` | Disable neural visualization telemetry |
| `--allow-experimental-live-control` | Explicitly unlock unvalidated live keyboard control |

### 4. Run the neural visualization dashboard

```bat
launch-neural-viz.bat
```

Open [http://127.0.0.1:8765/viz](http://127.0.0.1:8765/viz).

The dashboard displays simulated neural activity and visual-processing telemetry. It is a visualization of the model and its readouts, not a biological reconstruction of every neuron in 3D.

## Experiment scripts

| Script | Purpose |
| --- | --- |
| `neural_pathway_probe.py` | Controlled baseline, bar, motion, and looming stimulus probes |
| `neural_drive_calibration.py` | Exploratory retinal and lamina input-current sweeps |
| `neural_motion_decode.py` | Held-out-trial motion-direction decoding experiment |
| `neural_target_decode.py` | Static left/right target-side decoding experiment |
| `neural_motor_decoder.py` | Inference adapter for the trained motion readout |
| `calibrated_flyvision.py` | Experimental spatial-contrast FlyEye front end |
| `connectome_doom.py` | GZDoom frame capture and connectome bridge |
| `play_flyscroll_adventure.py` | Separate ViZDoom adventure policy |
| `flyscroll_dashboard.py` | Local dashboard server for the adventure pilot |

The checked-in JSON files preserve selected experiment outputs. The `.npz` files contain the small trained readout and its sample data.

## Project status

- [x] Connectome and FlyEye stimulus probing
- [x] Exploratory retinal/lamina drive calibration
- [x] Initial motion-direction information readout
- [x] Experimental readout-to-Doom bridge
- [x] Dry-run and live-control safety gates
- [ ] Validate the motion readout on recorded Doom frames
- [ ] Demonstrate robust target-side decoding
- [ ] Establish a defensible neural-to-motor mapping
- [ ] Demonstrate reliable neural-only gameplay

## Credits and upstream projects

- [FlyScroll / Fruitfly-Doomscroller](https://github.com/ravvdevv/Fruitfly-Doomscroller) — connectome simulation and visual processing foundation
- [GZDoom](https://zdoom.org/) — Doom engine
- [Freedoom](https://freedoom.github.io/) — free Doom-compatible game assets

Review upstream licenses and attribution requirements when downloading or redistributing third-party components.

## Keywords

Fruit fly connectome, Drosophila melanogaster, DOOM AI, neural network simulation, computational neuroscience, connectomics, FlyScroll, MaleCNS, visual neuroscience, neural decoding, GZDoom, Freedoom, Python, brain-inspired AI.

---

**Status:** Experimental research prototype. Results and limitations are documented above; please do not interpret the current controller as a validated biological fruit-fly brain playing DOOM.
