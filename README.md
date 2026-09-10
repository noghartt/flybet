# Flybet

A local, fake-money slot experiment controlled by a spiking simulation of the **full retained MaleCNS v1.0 connectome**. Watch the reels, the exact RGB input, neural decisions, dopamine-cell activity, contact-weighted delivery traces, and changes to candidate memory connections.

All money is simulated USD ($), stored as integer cents.

The dataset supplies anatomy. Dynamics, vision, reinforcement, and decoding are explicit approximations. This project does not demonstrate biological replication or useful learned gambling behavior.

The **3D anatomy** tab renders 139,662 real MaleCNS cell-body locations. Drag to orbit, scroll to zoom, use the front/side/dorsal camera buttons, or choose a brain/nerve-cord crop. Color by neural activity, annotated cell population, or the selected PAM11/PPL101 dopamine pathways. Click a cell to inspect its exact dataset ID and displayed firing rate. The original **Circuit diagram** remains available.

The 27,038 neurons without soma coordinates remain simulated but are omitted from the point cloud. Population highlights identify annotated cell families; they are not segmented neuropil boundaries. Each point's activity comes from that neuron's spikes with 100 ms smoothing in neural time. The display caps rates at 200 Hz; its population readouts summarize quantized, clipped values for located cells. The separate dopamine chart continues to show its original 10 ms population measurements.

## Run with Nix

```sh
nix develop
python -m flybet prepare
python -m flybet serve
```

Open **http://127.0.0.1:8765**. This checkout already has the verified dataset prepared locally. On a fresh checkout, `prepare` downloads approximately 1.1 GB and compiles the retained graph. Allow several GB of disk space and approximately 16 GB RAM for preparation. Runtime is CPU-based; a GPU is not required.

The flake provides a development shell and a package with a precompiled C++ kernel:

```sh
nix run . -- prepare
nix run . -- serve
nix flake check
```

Apple Silicon macOS and aarch64/x86_64 Linux outputs are defined. Intel macOS is excluded because the pinned Nixpkgs Arrow dependency is marked broken on that platform. Validation performed on this machine is documented in [docs/validation.md](docs/validation.md).

## Run with Python and uv

Python 3.11+ and a C++17 compiler are required. The lockfile captures the Python dependency resolution; Nix captures its own package set.

```sh
uv sync --frozen --extra dev
uv run flybet prepare
uv run flybet serve
```

Without uv, create a virtual environment and install `pip install -e '.[dev]'`. The native kernel compiles on first use outside the Nix package. Set `CXX` if the compiler is not named `c++`.

## Scenarios

Only the **center row** pays. Three identical symbols return **16× the stake**, including the stake. All other combinations return zero. The upper/lower symbols are decorative. These are intentionally simple Tigrinho-inspired rules, not a reproduction of a commercial game's mathematics.

| Scenario | Outcome distribution | Win probability | Theoretical RTP |
| --- | --- | ---: | ---: |
| Totally random | Three independent, uniform four-symbol reels | 6.25% | 100% |
| Fly favored | Winning triples collectively get 10% probability | 10% | 160% |
| House favored | Winning triples collectively get 2.5% probability | 2.5% | 40% |

Biased modes uniformly select within the four winning or sixty losing combinations. Outcomes remain independent of previous plays and of the fly's state. No probability changes occur mid-run. RTP is an expectation, not a promised session result; even the favored fly loses most individual spins.

Choose a scenario, seed, starting bankroll, stake, and decision limit. **Start experiment** begins a fresh brain, balance and RNG. **One neural decision** runs one observation/action/feedback cycle, then pauses. On a paused run it always continues the same brain and accumulated money, even if the form has been edited. **Pause** finishes the current decision and saves evidence; **Resume** also continues with the run's original settings. Only **Start a fresh run** applies changed settings and resets the balance. Balances are recorded per experiment, not pooled across runs or restored after a server restart.

The slot panel shows **starting dollars − total wagers + total returns = current balance**. The dashboard initially selects adaptive wagers with **Moderate bankroll influence**: accumulated gains increase the weight on the neural wager margin; losses decrease it. **Off** provides an unweighted decoder control, and **Strong** increases the effect. The underlying neural SPIN/WAIT choice stays binding, and affordability can reduce wagers. This is a declared wealth-response assumption, not demonstrated learning or biological risk preference. API/CLI defaults remain fixed stakes and influence off for compatibility. [Formula, limits and example](docs/experiments.md#accumulated-bankroll).

The neural decoder may choose WAIT. No hidden policy forces it to play. The explicitly labeled random baseline chooses SPIN/WAIT with equal probability while retaining the same sensory and reinforcement loop. Frozen memory disables every efficacy change, including passive decay.

## Behavior and spending

The **Behavior & exposure** panel measures the current run or a selected saved experiment. It shows play frequency, the next choice after a win/loss, mean spending over the following five decisions, bankroll share wagered, neural responses, and connection changes. Use **Plot** to switch between play frequency, bankroll, exposure, and connection strength. **Compare with another run** overlays a compatible saved run and shows both controllers, seeds, and sample counts. **Export measurements** downloads the analysis as JSON.

Fixed mode uses the base stake; adaptive mode lets the neural decoder select affordable 1×, 2×, or 4× stakes. The panel also reports tier counts and larger bets immediately after wins/losses. A falling bankroll also makes the same stake a larger percentage. Missing wins and incomplete follow-up windows stay explicit; charts summarize the whole run rather than just recent history. These are observed associations, not measurements of risk preference or proof of learning. [Metric definitions](docs/model.md#behavioral-measurements).

## Experimental templates and learning tests

**Experimental controls** selects physiology, chemistry, reward encoding, pulse timing, memory decay, visual encoding, and motor mapping. Pause a slot run to freeze/re-enable learning, forget half of learned efficacy, erase it, or reset chemistry and reward expectation. Every intervention is recorded.

**Did memory change the choice?** runs matched trained, frozen, erased-memory, and unpaired-feedback arms across seeds. Passive visual conditioning is followed by frozen, feedback-free probes. Results include paired control differences, exploratory intervals, saved reports, and an explicit conclusion when learning is not established. No rule forces learning or wager escalation. Physiology presets are uncalibrated sensitivity templates; sensitization and tolerance/withdrawal are bounded addiction hypotheses, not evidence of biological addiction. [Definitions and equations](docs/experiments.md).

```sh
nix run . -- run --wager-mode adaptive --motor mbon-assisted --chemistry sensitization --pulse ramp
nix run . -- condition --seeds 5 --trials 20 --motor mbon-assisted --wager-mode adaptive
```

## Headless experiments and checks

```sh
python -m flybet run --scenario random --seed 42 --decisions 20
python -m flybet run --scenario fly --seed 42 --decisions 20 --frozen
python -m flybet run --scenario house --seed 42 --decisions 20 --policy random-baseline
python -m flybet verify
pytest -q
FLYBET_FULL_TEST=1 OPENBLAS_NUM_THREADS=1 pytest -q
ruff check .
ruff format --check .
node --test tests/*.mjs
```

Use multiple preselected seeds, equal budgets, and matched policies for comparisons. Do not treat a favorable seed or changed weights as evidence of learning. Exact neural results depend on the recorded source, native binary and platform as well as the seed. `OPENBLAS_NUM_THREADS=1` is set in the Nix shell and avoids excessive threading for the small plasticity matrices.

## Files and records

- `flybet/data.py`: checksum-locked official downloads, retention, visual projection, CSR graph, population connectivity.
- `flybet/native/kernel.cpp`, `flybet/neural.py`: full-graph integration, explicit sensory encoding, decoding, memory, and telemetry.
- `flybet/game.py`: isolated seeded probability distributions and integer-cent accounting.
- `flybet/experiment.py`: one worker, phase scheduling, pause/step, and run records.
- `flybet/server.py`, `flybet/web/`: loopback API, event stream, and offline dashboard.
- `flybet/anatomy.py`, `flybet/activity.py`, `flybet/web/anatomy.js`: verified spatial mapping, per-neuron display activity, and interactive WebGL point cloud with a Canvas fallback.
- `flybet/insights.py`, `flybet/web/insights.js`: whole-run behavior/exposure metrics, saved-log analysis, and labeled reference comparisons.
- [docs/model.md](docs/model.md): architecture, equations, assumptions, and interpretation.
- [THIRD_PARTY.md](THIRD_PARTY.md): data/model provenance and attribution.

`data/` and `runs/` are ignored. `FLYBET_DATA` defaults to `data/malecns-v1.0`; `FLYBET_RUNS` defaults to `runs`. A run records `provenance.json`, complete `events.jsonl`, actual input PNGs, `summary.json`, and a compressed neural checkpoint with its checksum. The dashboard exports the full JSONL log. The observation table retains the latest 100 decisions internally and shows 12 rows, and the live neural trace shows 240 samples. Behavioral counters cover all completed decisions, with up to 80 chart blocks; the log retains the full per-decision record. Saved analyses remain accessible after restarting, including records created before the behavior panel existed.

Pause/resume works while the process remains alive. Checkpoints preserve analysis evidence; **automatic restoration after restarting the server is not implemented**. A new process starts a fresh run and never guesses how to recover a partly completed decision. Errors preserve a partial-run record.

The server binds only to loopback and has one simulation owner per runs directory. There are no payment, wallet, casino, exchange, or remote-control integrations.
