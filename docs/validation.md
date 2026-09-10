# Validation record

Validated on 2026-09-10 on Apple Silicon, macOS 26.6. These are software and data-integrity checks, not validation of biological behavior or successful learning.

Monetary figures below use the dashboard's current simulated USD notation. This display change preserves the original cent amounts; no exchange conversion or saved-log changes were made.

## Dataset

Downloaded all three official MaleCNS v1.0 inputs and verified their byte sizes and SHA-256 hashes. Compiled the full retained graph locally and committed the resulting array hashes in `flybet/graph.lock.json`. Both the development runtime and `nix run . -- verify` authenticated the graph:

| Quantity | Verified value |
| --- | ---: |
| Retained neurons | 166,700 |
| Directed connections | 25,582,938 |
| Contact counts | 124,177,617 |
| Weight-one connections | 10,299,701 |
| Self-connections | 101 |
| Candidate plastic connections | 7,835 |
| Mapped brightness / color inputs | 3,335 / 811 |

Retention is defined in [model.md](model.md). All retained neurons are integrated; the small circuit diagram is only a selected-population view.

## Automated checks

- `FLYBET_FULL_TEST=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest -q`: **31 passed** after adding the anatomical view. The full-data tests verify sensory responses, reward and aversive population responses, delivery to selected MBON populations, exactly frozen weights, enabled weight changes, finite weights, neural checkpoint contents, anatomical coverage, actual PPL101 soma coordinates, and the binary/metadata APIs. Two upstream FastAPI/Starlette deprecation warnings remain.
- Offline tests cover all three probability distributions over 60,000 seeded draws each, reproducibility, cent accounting, invalid settings, large integer neuron IDs, retained weak/self edges, numerical integration against an independent scalar reference, timing-sensitive plasticity, API control and export, single simulation ownership, and explicit failure when data are missing.
- `ruff check .` and `ruff format --check .`: passed.
- `node --test tests/test_motion.mjs`: **4 passed** for measured-rate interpolation, overlapping frames, increase-only halos, freezing, and new-run clearing. The Nix frontend check and CI run this suite; the development shell includes Node.
- `uv lock --check --offline` with the project-local cache: passed.
- `nix flake check`: built the native library and application and passed its offline test suite on `aarch64-darwin`. The full-data test is opt-in and excluded from the Nix build sandbox.
- `nix flake check --all-systems --no-build`: evaluated all declared package, app, shell, check, and formatter outputs on Apple Silicon and both Linux architectures. Linux builds were not executed here. Intel macOS is excluded because the pinned Arrow package is marked broken there.
- The dashboard itself was launched with `nix run . -- serve --port 8765`, then ran the actual full graph. Its recorded runtime is Python 3.12.14, NumPy 2.4.4, arm64 macOS, with source and native-binary SHA-256 values in the run's provenance.

## Browser checks and observations

Inspected the desktop dashboard in Chrome, including scenario selection, fresh runs, single-decision stepping, pause, resume, slot results, the neural circuit, the dopamine plot, exact RGB observation, and outcome history. Runs were made in all three scenarios. Controls prevented configuration changes during active work; pause completed the current decision before checkpointing; resume retained the same run.

A six-decision fly-favored run with seed 42 produced **one SPIN, one loss, and five WAITs**, ending with $99.00 of its $100.00 fake bankroll. A four-decision house-favored run in the Nix package similarly produced one SPIN and three WAITs. These short runs did not distinguish the scenario distributions; a favored fly still loses most individual spins. The initial neural choice was not overridden to force further play.

The first completed losing spin produced simulated PPL101 activity and changes on eligible connections. This verifies that the engineered feedback loop operates. It does **not** establish that the weight changes caused useful behavioral learning. Endogenous PPL101 activity also continues during neutral phases, an observable property of this uncalibrated model.

The 3D view was checked in Chrome with all 139,662 located somas. A live neural decision produced a final 500 ms anatomical activity frame, population readouts, and the expected PPL101 feedback. The displayed cell inspector resolved an actual neuron ID. Additional tests check missing-coordinate exclusion, exact simulator index mapping, μm conversion, per-neuron activity decay, quantization without modifying measured rates, frame identity, pause stability, and clearing old frames on fresh runs. No synthetic positions or activity are used.

Camera rotation, brain cropping, mushroom-body highlighting, PAM11/PPL101 isolation, and switching back to the circuit view were verified in Chrome. The same seed's first observation had identical input and spike hashes and the same action before and after the visualization change. The final package check exposed stale browser assets caused by Nix's fixed file timestamps; assets now use content-versioned URLs, bypass conditional mtime caching, and use `Cache-Control: no-store`, with a regression test. Relative module and stylesheet imports stay within the versioned bundle.

The subsequent animation update was inspected during a real seed-42 neural run: all three reel strips rolled during the first committed SPIN and settled on `● ● 7`. The 3D cloud displayed live measured activity with interpolated brightness and increase highlights. The next two decisions were WAITs; the spin count stayed at one and no reel tracks remained. The “Animate activity” toggle, final frozen frame, and population explanation were checked in Chrome, with no browser warning/error logs. The first decision's input and spike hashes matched the pre-animation Nix run exactly. All 31 Python tests and both Nix package/frontend checks passed again. Reduced-motion transition semantics are covered by the motion tests; OS-level reduced-motion and the Canvas fallback were not exercised in this browser session.

## Behavior and exposure analytics

The subsequent metrics implementation passed **39 Python tests**, including the full MaleCNS checks, and **6 JavaScript tests**. New coverage includes immediate outcome follow-ups, fixed five-decision spending windows, terminal/incomplete windows, bankruptcy, absent wins, pre-bet bankroll exposure, a 1,001-decision independent reference calculation, bounded whole-run chart aggregation, decoder reasons, live/saved API parity, fresh-run resets, JSON download headers, malformed record rejection, and model/source identity matching. Ruff checks and formatting passed. Nix package/frontend checks also passed during development.

Actual saved logs were analyzed without modification. In `20260910-135712-8d97d3d5`, all 200 completed decisions reconcile to 43 spins, five wins, $43 wagered, and +$37 net. The next decision was SPIN after 0/5 wins and 9/38 losses. Complete five-decision follow-ups averaged $0.80 after wins (5 windows) and $1.138888… after losses (36 windows; 2 incomplete/excluded). These figures were independently recomputed directly from outcome records, rather than only checked against the accumulator. They describe one session and do not establish risk preference or causal learning.

Chrome checks covered loading these existing records, missing-outcome displays, changing chart measurements, a labeled neural/random-baseline comparison, and rejecting different configured decision limits. The browser console showed no warnings or errors. The selected saved analysis is explicitly distinguished from the current live game/brain view. General responsive rules are provided; this check used the desktop viewport.

The Nix-served dashboard also completed a real three-decision frozen-memory run (`20260910-143247-f7e66150`): one SPIN, zero changed connections, and exactly 1× mean strength. Its live API, saved summary, and downloadable metrics JSON matched exactly. The live panel showed completed counts, no-win missing data, and the correct next-decision exposure. The current run is excluded from the archive catalog so initialization is not reported as an unreadable saved record.

## Experimental control expansion

The full-connectome conditioning test `20260910-151634-2dc5bfd7` completed five seeds, four balanced training trials per arm, and all 20 arms. The default physiology/vision/reward/chemistry templates were used with the MBON-assisted motor decoder and adaptive wager probes. Thousands of eligible weights changed in trained arms, but before/after probe signals, choices, and proposed tiers were unchanged. All paired control differences were zero. The report correctly concludes **learning not established**. Four training trials are a short functional check, not an exhaustive learning assessment. The complete original report and events are preserved under `runs/` and accessible in the conditioning report selector.

The Nix-packaged adaptive slot run `20260910-152447-be581fad` completed 20 decisions: three spins, one win, executed stakes $2/$2/$4, $8 total wagered, and $24 net gain. It used the MBON-assisted decoder, magnitude reward, a rising ramp, and sensitization chemistry. The first decision paused; freeze, half-forgetting, full erasure, re-enabling learning, and chemistry/expectation reset were tested and logged before resuming. Erasure restored zero changed connections and exactly 1× mean efficacy. This intervened run is not a causal learning comparison. The sensitivity curve rose above 1 after its reward and decayed during later neural time. UI checks covered the live adaptive-stake summary, actual chemistry curve, and saved negative conditioning result, with no browser warning/error logs.

Automated checks cover strict preset validation, adaptive integer accounting and RNG independence, neural-only tier selection, pulse timing and dose, prediction-error update order, bounded chemistry/recovery/reset, physiology response changes, forgetting/frozen weights, conditioning counterbalancing inputs and controls, cancellation, intervention records, legacy archive compatibility, and preserved whole-run chemistry summaries. Full-data checks also exercised alternative physiology, mirrored vision, MBON-assisted decoding, sensitization, ramp feedback, frozen weights and exact erasure. Nix package and frontend checks passed on Apple Silicon. These checks validate software behavior; presets remain uncalibrated biological hypotheses.

## Accumulated bankroll and wager weighting

The bankroll update passed **66 Python tests**, including full MaleCNS integration and native numerical tests, and **10 JavaScript tests**. Coverage includes accumulating wins/losses without double-counting returned stakes, cent reconciliation, weight bounds, denomination-independent gain, preserving neural WAIT/gate/rates, Off/fixed/baseline bypasses, saved/live parity, and influence traces surviving whole-run aggregation. A controlled API fixture verifies that a $100 start grows to $130, the next decision uses 1.3× weighting to propose a larger tier, and the resulting loss reduces the same balance to $126. That fixture tests the declared arithmetic; it is not evidence of learned behavior.

The real full-connectome run `20260910-154814-47d97226` completed 20 decisions with default physiology/motor, adaptive wagers, and Moderate bankroll influence. Two $1 spins produced one loss and one win: $100 − $2 + $16 = **$114**. Later decisions used a 1.14× bankroll weight but remained neural WAITs; no proposal changed tier in this short run. In Chrome, editing the starting-money field to $200 and the next-run influence to Off before stepping did **not** reset the existing $99 balance or change its active Moderate profile. The second decision used $99, its win accumulated to $114, and resume preserved the same run through decision 20. The ledger, decision-time context, full-session influence plot, and frozen brain display were checked. There was no desktop horizontal overflow and no browser warning/error log; the ledger's contrast was corrected during visual inspection.

## Remaining limits

A controlled multi-seed learning protocol and separate probes are now implemented, with a recorded negative result. Biological calibration, successful retained behavioral learning, broad task generalization, long-run stability, mobile/browser compatibility, and cross-platform neural reproducibility remain unestablished. Responsive layouts are implemented, but this validation used a desktop viewport. Checkpoints are saved for analysis; restoring a run after process restart is not implemented. See [model.md](model.md) for the modeled mechanisms and scientific limits.
