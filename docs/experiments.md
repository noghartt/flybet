# Experimental controls

All experiments retain the locked 166,700 MaleCNS neurons and 25,582,938 directed connections. Presets change modeled dynamics and interfaces, never the anatomical graph or slot outcome probabilities. `flybet/templates.py` is the versioned parameter registry; the dashboard exposes every resolved value. These are **sensitivity templates, not biologically fitted calibrations**.

## Learning and forgetting

In a slot run, pause before using **Freeze memory**, **Enable learning**, **Forget 50%**, or **Erase memory**. Freeze holds eligible weights constant, including passive decay. Forgetting moves efficacy toward its original value of one and clears eligibility traces. It does not clear membrane activity, chemistry, or reward expectation. Those are distinct state variables. **Reset chemistry & expectation** clears reward-dose history and the external reward encoder's expectation. Each intervention is written to the event log; ordinary matched comparisons reject intervened runs. The current telemetry reflects interventions immediately; behavior metrics retain the state at the last completed decision until another decision completes.

The default memory decay constant is 1,800 neural seconds; fast forgetting uses 10 seconds. Decay operates during simulated time only and only when learning is enabled. Manual erasure remains available while weights are frozen. Fresh runs start from baseline.

### Controlled conditioning

**Run learning test** performs four arms for each seed: trained, frozen throughout training, trained then erased, and unpaired reinforcement. All arms use a fresh full graph and the selected physiology, vision, motor, memory, pulse, reward and chemistry presets. The slot memory selector does not override these experimental arms. The random-baseline controller is rejected for this test.

Two equal-area, equal-color patterns of horizontal/vertical bars enter the actual photoreceptor encoder. Half the trials use each pattern; the seeded trial order is shared across arms. The rewarded pattern is counterbalanced by seed index. Paired training gives the designated pattern a positive unit outcome and the other a negative unit outcome to the selected reward encoder. Unpaired training permutes the same balanced reinforcement list using a separate seeded RNG; finite samples can retain accidental associations, so the full pairing schedule is exported. Prediction-error encoding can change pulse sign relative to the nominal outcome; `off` eliminates outcome pulses. Training is passive conditioning with no game accounting and no forced SPIN.

Every trial presents the cue for 300 ms, then the same image and configured pulse for 200 ms. Between training trials, electrical state, sensory filtering and eligibility traces reset, while learned efficacy and chemistry exposure persist. Probes occur both before and after training. Each cue probe starts from identical electrical, sensory, eligibility and chemistry state, with plasticity disabled and no outcome feedback. The erased arm resets efficacy immediately before the final probes. An optional retention interval applies the analytical passive-decay equation directly to efficacy; it is not a simulation of sleep, elapsed wall time, or ongoing neural activity.

The primary measure is the change in `(SPIN for designated rewarded cue − SPIN for designated punished cue)`, after minus before training. For every seed, subtract each control's change from the trained arm's change. A seeded 4,000-resample percentile bootstrap over complete paired seeds gives exploratory 95% intervals when at least five seeds complete. A **candidate memory-dependent choice effect** is reported only if every requested seed completed and the lower interval bound is positive against all three controls. Otherwise the result is **learning not established**. No correction for multiple comparisons is applied; the candidate label requires independent replication. Seeds vary schedules and cue assignment, not biological individuals. The deterministic model has no sampled physiological noise. No assumption guarantees that this circuit or decoder can learn the task.

Secondary measures use the same contrast calculation for the continuous neural decoder signal and proposed wager tier. Tier probes involve no money or bankroll clipping. A changed continuous signal without a changed choice does not pass the primary criterion. This protocol evaluates retained cue-conditioned responses, not profitable slot play or human addiction.

`protocol.json` records presets, source hashes, full dataset identity, runtime, pairing schedules, before/after measurements, control differences, and the conclusion. `events.jsonl` records observed neural trajectories. Incomplete arms do not enter paired statistics. **Stop test** finishes the current trial/probe boundary and saves partial evidence; tests cannot be resumed after cancellation. Saved conditioning reports have their own selector and download, separate from slot analytics. Each arm has a separate activity-frame identity because its neural clock starts fresh.

```sh
nix run . -- condition --seeds 5 --trials 20 --motor mbon-assisted --wager-mode adaptive
nix run . -- condition --seeds 5 --trials 20 --retention-seconds 30 --memory fast-forgetting
```

## Wager and motor templates

Fixed mode uses the base stake. Adaptive mode offers 1×, 2×, and 4× the base stake. The neural decoder alone proposes a tier from its signal's margin above the SPIN threshold: less than 5 Hz gives 1×, at least 5 gives 2×, at least 15 gives 4×. DNpe017 must fire and the decoder signal must reach 2 Hz for a SPIN. The game executes the largest affordable allowed tier no greater than the requested tier; if the base stake is unaffordable, the session ends. Requested and executed amounts are recorded. The random baseline explicitly samples an affordable tier uniformly after choosing SPIN with probability 1/2, using its own policy RNG.

- Default signal: mean DNp20 right firing minus left firing.
- Mirrored signal: reverse that difference to test inherited directional asymmetry.
- MBON-assisted signal: default difference plus `0.1 × (mean MBON11 rate − mean MBON07 rate)`. This exposes output downstream of plastic connections to the decoder, but does not establish the biological sign of this decision mapping.

The measured neural signal receives no monetary metadata. Chemistry and memory can influence wagers through neural activity; an optional declared bankroll context also weights the margin for wager tiers as specified below. Slot odds and 16× returns are unchanged across tiers. Larger bets scale both expected return and variability; this is not an equal-expected-value risk-choice experiment and does not isolate risk preference.

### Accumulated bankroll

Accounting is in integer simulated USD cents: `balance = starting balance − sum(stakes) + sum(gross payouts)`. A winning payout already includes the returned stake; it is not added twice. WAIT has zero stake and payout. Every decision uses the previous outcome's balance, including all earlier gains and losses. Stepping, pausing, resuming, and memory/chemistry interventions preserve it. A fresh experiment resets both money and brain. Archived balances are evidence, not a wallet pooled across independent experiments; checkpoints do not yet support restoring a session after process restart.

For adaptive neural wagers, let `r = (pre-decision balance − starting balance) / starting balance`. The selected **Bankroll influence** template computes `g = clamp(1 + strength × r, minimum, maximum)`. Multiply the raw neural signal's margin above the 2 Hz threshold by `g`, then apply the same 5 / 15 tier boundaries. The weighted margin is a decoder score, not a new firing-rate measurement. SPIN/WAIT and the DNpe017 gate are unchanged by this calculation.

| Template | Strength | Minimum / maximum weight |
| --- | ---: | ---: |
| Off | 0 | 1× / 1× |
| Moderate | 1 | 0.25× / 2× |
| Strong | 2 | 0.25× / 3× |

Example: after starting with $100, a $2 winning stake returns $32 gross, leaving $130. Moderate weighting is now 1.3×. On the **next** decision a 12 Hz neural margin becomes a 15.6 decoder score, proposing a 4× rather than a 2× wager. A neural WAIT remains WAIT. Different margins can stay in the same tier, and affordability can lower a proposal. A loss alone does not necessarily lower the weight below 1: accumulated net profit can remain positive. No calculation sees the forthcoming outcome or changes the seeded slot RNG. Current bankroll, not the previous win flag, is the context.

The dashboard starts with adaptive wagers and Moderate weighting; API/CLI defaults remain fixed stakes and Off for compatibility. Fixed wagers and the random baseline bypass weighting. Conditioning probes have no monetary context and bypass it too. **Off removes only this explicit decoder weight**: the credit-bar pixels, reward pulses, memory, chemistry and affordability remain active. Disabling learning does not disable the imposed wealth response.

Each new decision/outcome records pre-decision funds, net profit, gain, raw and weighted margins, and unweighted/proposed tiers. Executed cents remain recorded separately. The ledger shows actual totals, and the decision caption distinguishes pre-decision funds from the post-outcome balance. Whole-run analytics count higher/lower tier proposals relative to that same decision's unweighted decoder, before affordability. This comparison isolates the explicit arithmetic adjustment, not the counterfactual future trajectory of an Off run. The **Bankroll influence on wagers** plot preserves the pre-decision gain at each block endpoint; legacy records have missing observations.

The visual credit bar now uses `balance / (balance + starting balance)`, with a reference tick at the midpoint. It can show gains above the initial balance instead of clipping immediately. This changes the retinal input; source identity prevents silently comparing it as the same old model. Pixels remain an engineered sensory mapping, with no assumption that the fly understands dollar amounts.

```sh
nix run . -- run --wager-mode adaptive --wealth moderate --seed 42 --decisions 200
nix run . -- run --wager-mode adaptive --wealth off --seed 42 --decisions 200
```

Accumulated-wealth weighting is an explicit behavioral hypothesis, not a demonstrated biological mechanism or learned risk preference. It creates a controlled way to test sensitivity to wealth; neither winning nor larger wagers establishes learning. Larger dollar wagers also need not mean a larger fraction of bankroll at risk.

Analytics record tier counts, mean stake, and the proportion of immediate following decisions with a larger executed stake than the triggering win/loss. WAIT counts as no increase; absent follow-ups do not enter the denominator. Bankroll affordability can constrain this measurement. Both live and archived variable-stake records reconcile in integer cents. The observation log includes each executed stake. Plots include mean played stake, reward-dose history, sensitivity, and withdrawal current. Historical runs lacking chemistry observations show missing values. To overlay different presets, enable **Allow different presets**; model source and dataset identities must still match, and changed presets are listed explicitly. Such comparisons remain exploratory and intervened runs are rejected.

## Reward and pulse templates

The reward encoder is an **external engineered interface**, separate from neural learning. Let `r = net cents / configured base-stake cents` and `E` be its running expected return. `E` starts at zero and updates after each played outcome by `E ← E + 0.1(r − E)` except in `off` mode. WAIT neither updates `E` nor supplies an outcome pulse. Freezing neural plasticity does not freeze this encoder.

- Binary: sign(r), giving 20 current units for a gain or loss.
- Magnitude: r, so amount matters, with amplitude capped at 40 units.
- Prediction error: r − E using the expectation **before** updating it. An outcome below expectation can stimulate PPL101 even if net gain is positive. This moving average is not a learned neural value function.
- Off: no outcome pulse. Endogenous neural activity and configured withdrawal drive can still occur.

Positive encoded signals target PAM11, negative signals target PPL101. The amplitude is `min(40, 20 × |encoded value|)`. Pulse shapes occupy the fixed 200 ms feedback window:

| Shape | Timing | Dose at amplitude 20, baseline chemistry |
| --- | --- | ---: |
| Sustained | 0–200 ms | 4 current-seconds |
| Brief | 0–50 ms | 1 current-second |
| Delayed | 100–200 ms | 2 current-seconds |
| Ramp | Linear rise, sampled at 10 ms bin midpoints | 2 current-seconds |

These shapes are not dose-matched. Dose is accumulated from actual delivered current and exported with each feedback observation. The preview is a normalized shape; exact effective currents and chemistry history are live measurements from the model.

## Physiology and chemistry

Default physiology preserves the original parameter values. Less-excitable raises spike threshold to −43 mV, scales fast weights by 0.9, and increases KC adaptation to 10 mV. More-excitable lowers threshold to −46 mV, scales fast weights by 1.1, uses membrane/synaptic constants 25/6 ms, KC adaptation 6 mV with a 250 ms decay, and delivery-trace decay 150 ms. The C++ integrator consumes these runtime values. Source contact arrays remain untouched. These alternatives test sensitivity and are not inferred cell-specific electrophysiology; unknown transmitter/receptor effects remain unresolved.

Chemistry hypotheses affect selected PAM11/PPL101 input currents. They do not reconstruct concentrations or add unmeasured physiology to other modulators. In each 10 ms neural bin, reward-dose history `x` decays with a 60-second time constant. A delivered 20-unit reward for 200 ms adds approximately one dose, with history bounded to 20. No exposure accumulates in baseline mode.

- Baseline: reward sensitivity 1, no withdrawal drive.
- Sensitization: reward gain `1 + 0.1x`, bounded to 3 by the exposure limit.
- Tolerance/withdrawal: gain `1 / (1 + 0.15x)`; when no positive current is delivered, add `min(5, 0.25x)` current units to PPL101. Exposure decays during WAIT as well as other simulated phases.

Final positive current is capped at 80 units. Dose history depends on delivered positive current; sensitization therefore has a bounded positive feedback loop. Increased exposure, sensitization, tolerance and withdrawal are imposed **addiction hypotheses**, not demonstrated addiction or inferred human mechanisms. Whether they change repeated play or stake escalation is an experimental result, not a programmed behavioral conclusion. The live cards show dose history, gain, effective currents and withdrawal drive. Traces and outcomes preserve these measurements for analysis.

## Vision templates

Default uses the original inferred retinal sampling. Grayscale removes the R8 channel distinction; mirrored reverses horizontal sampling; low contrast maps each sampled linear intensity `L` to `0.5 + 0.25(L − 0.5)`. All use the selected saturating photoreceptor-current transform and low-pass filter. The image panel shows the rendered source observation; sampling/contrast/channel transforms occur inside the declared encoder. No template reads text, identifies a winning combination, or injects future outcomes into the brain.

## Evidence and further calibration

Useful calibration requires measured target responses and held-out validation. The present presets are starting hypotheses for that process. Simpler connectome-based models can be useful when checked against particular behaviors; that does not automatically transfer their validation to this model or its MaleCNS interfaces.

- [Shiu et al., A Drosophila computational brain model reveals sensorimotor processing](https://www.nature.com/articles/s41586-024-07763-9): connects a simple whole-brain model to experimentally tested sensorimotor predictions.
- [Lappalainen et al., Connectome-constrained networks predict neural activity across the fly visual system](https://www.nature.com/articles/s41586-024-07939-3): illustrates constraining visual models and checking neural response predictions.
- [Gkanias et al., An incentive circuit for memory dynamics in the mushroom body of Drosophila melanogaster](https://elifesciences.org/articles/75611): motivates timing-sensitive memory and competing reinforcement hypotheses. Flybet does not reproduce its full circuit or parameter fits.
- [Aso and Rubin, Dopaminergic neurons write and update memories with cell-type-specific rules](https://elifesciences.org/articles/16135): supports testing differences in memory formation and retention rather than assuming one universal dopamine rule.

No parameters here were fitted to these papers' raw data. A physical body is outside the current implementation scope.
