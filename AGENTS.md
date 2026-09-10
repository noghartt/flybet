# Flybet

Local, fake-money MaleCNS v1.0 experiment. Read `docs/model.md` before changing neural dynamics or interpreting results.

- Preserve every retained neuronal entry and every released connection between retained entries, including weak edges and autapses. Never substitute a small generated network for MaleCNS.
- Keep dataset import, neural integration, sensory encoding, plasticity, declared decoding, game randomness, accounting, and presentation separate.
- Game outcomes depend only on the declared scenario and its seeded RNG, never neural activity, bankroll, prior wins, or desired demo results. All scenarios remain stochastic.
- Only the neural decoder chooses SPIN/WAIT and proposed stake tiers in neural runs. Affordability can reduce a proposed tier but must never raise it or change slot odds. Never force a spin to make a demonstration look active. Label baseline policies explicitly.
- Currency is simulated only. Use integer cents; no casino, wallet, exchange, payment, or credential integrations.
- Dopamine currents and delivery traces are modeling assumptions. Do not claim measured concentrations, consciousness, addiction, pleasure, pain, biological replication, or proven learning.
- UI telemetry must come from the running simulation. Missing data must be shown as missing, never populated with fabricated activity.
- Anatomical positions must come from verified release data and bind to exact simulator indices. Omit unlocated neurons from spatial views without excluding them from simulation. Label cell-family coloring separately from neuropil boundaries; keep camera and display smoothing outside neural dynamics.
- Scenario changes start new runs. Record source checksums, model parameters, seed, actions, outcomes, and actual neural measurements. Keep downloaded data and run artifacts ignored.
- Use one simulation worker per process and bind the HTTP service to loopback. Preserve crash evidence; don't silently resume partial runs.
- Run `pytest`, `ruff check .`, `ruff format --check .`, and the native numerical tests after relevant changes. Full-data tests require `FLYBET_FULL_TEST=1` after `flybet prepare`.
- Run `node --test tests/*.mjs` for dashboard changes. Animate only committed spins and measured activity changes; never add spontaneous pulses or feed spectator animation back into the model. Freeze brain motion on pause or disconnect and respect reduced-motion settings.
- Behavioral metrics cover all completed decisions, not the UI history tail. Keep absent outcomes missing, show denominators, exclude incomplete fixed-length follow-ups, and distinguish fixed stake, spending frequency, and bankroll exposure. Observed outcome associations and individual run comparisons do not establish causality or risk preference.
- Validate `nix flake check` where supported. Keep dependency and flake lockfiles current. Do not stage unrelated files or commit datasets.

- Presets are uncalibrated hypotheses until fitted against independent measurements. Keep reward encoding, pulse timing, chemical dose history, neural plasticity and behavioral evidence separate. Never implement a direct win-to-bet-escalation rule or label sensitization/tolerance as demonstrated addiction.
- Conditioning training is passive and has no game wagers. Probes freeze plasticity and reset electrical/chemical transients. Preserve all four paired arms and include only complete seeds in statistical comparisons; negative evidence is a valid result. Separate activity identities for fresh protocol brains.
- Memory/chemistry interventions require an idle paused slot run and append an event. Ordinary matched comparisons must flag intervened runs. Keep adaptive-stake accounting and archived legacy fixed-stake records compatible.
- Accumulate integer-cent gains/losses across decisions; step/resume must preserve money and brain even when the form was edited. Only an explicit fresh run applies new settings and resets funds. The optional wealth template weights wager-tier margins using pre-decision net wealth; keep it distinct from measured neural rates and learned behavior. Preserve SPIN/WAIT and the gate, log unweighted/weighted proposals, and bypass monetary context in passive conditioning.
