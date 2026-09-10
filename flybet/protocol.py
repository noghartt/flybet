"""Paired, counterbalanced conditioning tests on the full connectome.

Passive training has no bets. Probe choices are produced only by the neural decoder.
Results are observations, never a policy that changes slot actions.
"""

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .display import cue_frame
from .neural import MODEL
from .paths import atomic_json, sha256
from .reinforcement import RewardEncoder
from .templates import resolve

ARMS = ("trained", "frozen", "erased", "unpaired")


@dataclass(frozen=True)
class ProtocolConfig:
    seeds: int = 5
    trials: int = 20
    retention_seconds: int = 0

    def __post_init__(self):
        for key, low, high in (
            ("seeds", 1, 30),
            ("trials", 2, 200),
            ("retention_seconds", 0, 3600),
        ):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key} must be an integer between {low} and {high}")
        if self.trials % 2:
            raise ValueError("Use an even number of balanced conditioning trials")


def contrast(probes, field):
    return probes["positive"][field] - probes["negative"][field]


def summarize(rows, requested_seeds):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["seed"], {})[row["arm"]] = row
    complete = [arms for arms in grouped.values() if set(arms) == set(ARMS)]
    comparisons = {}
    rng = np.random.default_rng(1701)
    for metric in ("choice_change", "signal_change", "tier_change"):
        comparisons[metric] = {}
        for control in ARMS[1:]:
            values = np.array([a["trained"][metric] - a[control][metric] for a in complete])
            ci = None
            if len(values) >= 5:
                boot = rng.choice(values, size=(4000, len(values)), replace=True).mean(axis=1)
                ci = np.quantile(boot, [0.025, 0.975]).tolist()
            comparisons[metric][control] = dict(
                n=len(values),
                mean=float(values.mean()) if len(values) else None,
                bootstrap_95_interval=ci,
            )
    supported = bool(
        len(complete) >= 5
        and len(complete) == requested_seeds
        and all(c["bootstrap_95_interval"][0] > 0 for c in comparisons["choice_change"].values())
    )
    return dict(
        completed_seeds=len(complete),
        requested_seeds=requested_seeds,
        comparisons=comparisons,
        conclusion="candidate-memory-dependent-choice-effect"
        if supported
        else "learning-not-established",
        interpretation="Paired seed bootstrap; exploratory, no multiplicity correction. "
        "Independent replication and parameter sensitivity are still required. "
        "Signal changes alone do not establish a learned choice.",
    )


def execute(experiment, config, settings):
    e = experiment
    rows = []
    source = Path(__file__).parent
    report = dict(
        kind="conditioning",
        config=asdict(config),
        settings=asdict(settings),
        templates=resolve(config),
        model=MODEL,
        rows=rows,
        status="running",
        design="Balanced passive cue conditioning; no money or forced spins. "
        "Rewarded cue counterbalanced by seed index. Independent probe state, "
        "no probe reinforcement, frozen probe weights. Erased arm removes only weights.",
        metric="Change in (SPIN for rewarded cue minus SPIN for punished cue), "
        "after minus before conditioning; paired against each control.",
        sources={
            str(p.relative_to(source)): sha256(p)
            for p in source.rglob("*")
            if p.suffix in (".py", ".cpp")
        },
    )
    atomic_json(e.run_dir / "protocol.json", report)
    try:
        for offset in range(settings.seeds):
            seed = (config.seed + offset) % 2**32
            positive = offset % 2
            cues = [0, 1] * (settings.trials // 2)
            random.Random(seed).shuffle(cues)
            signs = ["reward" if cue == positive else "aversive" for cue in cues]
            unpaired = signs.copy()
            random.Random(seed ^ 0xA551).shuffle(unpaired)
            for arm in ARMS:
                if e.pause_requested.is_set() or e.shutdown_requested.is_set():
                    report["status"] = "cancelled"
                    return
                e.brain = None  # Release the preceding full-graph state before allocating another.
                e.brain = e.brain_factory(e.data, learning=arm != "frozen", config=config)
                b = e.brain
                report["dataset"] = b.manifest
                report["runtime"] = b.runtime_metadata()
                e.activity_packet = None
                e.update(
                    anatomy=b.arrays["anatomy"].tolist(),
                    group_sizes=b.group_sizes.tolist(),
                    learning_enabled=b.learning,
                    activity_id=f"{e.state['run_id']}:{seed}:{arm}",
                    telemetry=None,
                    series=[],
                )

                def advance(cue, phase, reinforcement=None, b=b, seed=seed, arm=arm):
                    e.image = cue_frame(cue)
                    e.update(
                        phase=phase,
                        image_revision=e.state["image_revision"] + 1,
                        protocol=dict(
                            status="running",
                            seed=seed,
                            arm=arm,
                            phase=phase,
                            completed_arms=len(rows),
                            total_arms=settings.seeds * len(ARMS),
                        ),
                    )
                    result = b.advance(
                        e.image,
                        200 if reinforcement else 300,
                        reinforcement["stimulus"] if reinforcement else "none",
                        e.telemetry,
                        reinforcement=reinforcement,
                    )
                    e.log(
                        "protocol-observation",
                        arm=arm,
                        seed=seed,
                        cue=cue,
                        phase=phase,
                        observation=result,
                    )
                    return result

                def probe(b=b, positive=positive, advance=advance):
                    b.learning = False
                    result = {}
                    for cue in (0, 1):
                        b.clear_transients()
                        output = advance(cue, "probe")["decoder"]
                        spin = int(output["action"] == "SPIN")
                        result["positive" if cue == positive else "negative"] = dict(
                            signal=output["difference_hz"],
                            choice=spin,
                            tier=output["requested_multiplier"]
                            if config.wager_mode == "adaptive"
                            else spin,
                        )
                    return result

                before = probe()
                b.learning = arm != "frozen"
                training_encoder = RewardEncoder(config.reward, config.pulse)
                for trial, cue in enumerate(cues):
                    if e.pause_requested.is_set() or e.shutdown_requested.is_set():
                        report["status"] = "cancelled"
                        return
                    b.clear_transients(reset_chemistry=False)
                    advance(cue, "conditioning-cue")
                    stimulus = unpaired[trial] if arm == "unpaired" else signs[trial]
                    # A declared conditioning stimulus, not a monetary outcome.
                    pulse = training_encoder.encode(100 if stimulus == "reward" else -100, 100)
                    advance(cue, "conditioning-feedback", pulse)
                    e.update(decision=e.state["decision"] + 1)
                if arm == "erased":
                    b.forget()
                if settings.retention_seconds:
                    b.forget(1 - np.exp(-settings.retention_seconds / b.memory.decay_seconds))
                after = probe()
                row = dict(
                    seed=seed,
                    arm=arm,
                    rewarded_cue=positive,
                    before=before,
                    after=after,
                    choice_change=contrast(after, "choice") - contrast(before, "choice"),
                    signal_change=contrast(after, "signal") - contrast(before, "signal"),
                    tier_change=contrast(after, "tier") - contrast(before, "tier"),
                    changed_connections=int(np.count_nonzero(b.memory.efficacy != 1)),
                    training_pairings=[
                        dict(cue=c, stimulus=s)
                        for c, s in zip(cues, unpaired if arm == "unpaired" else signs, strict=True)
                    ],
                )
                rows.append(row)
                e.log("protocol-arm", **row)
                report["analysis"] = summarize(rows, settings.seeds)
                atomic_json(e.run_dir / "protocol.json", report)
                e.update(protocol={**e.state["protocol"], "analysis": report["analysis"]})
        report["status"] = "finished"
    except Exception as error:
        report.update(status="error", error=f"{type(error).__name__}: {error}")
        e.update(error=report["error"])
    finally:
        report["analysis"] = summarize(rows, settings.seeds)
        atomic_json(e.run_dir / "protocol.json", report)
        digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
        e.update(
            status=report["status"],
            phase=report["status"],
            saving=False,
            pause_requested=False,
            protocol={
                "status": report["status"],
                "analysis": report["analysis"],
                "completed_arms": len(rows),
                "total_arms": settings.seeds * len(ARMS),
                "report_sha256": digest,
            },
        )
