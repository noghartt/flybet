"""One isolated simulation owner, immutable scenarios, observable decisions."""

import copy
import fcntl
import json
import random
import threading
import time
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from . import display
from .data import EXPECTED, GROUP_NAMES
from .game import SCENARIOS, SlotGame, allowed_stakes
from .insights import Insights, model_identity
from .neural import MODEL, Brain, wager_decision
from .paths import atomic_json, data_root, runs_root, sha256
from .reinforcement import RewardEncoder
from .templates import MOTOR, resolve


class Busy(ValueError):
    pass


class Experiment:
    def __init__(self, data=None, runs=None, brain_factory=Brain):
        self.data = Path(data or data_root())
        self.runs = Path(runs or runs_root())
        self.runs.mkdir(parents=True, exist_ok=True)
        self.owner = (self.runs / "worker.lock").open("a")
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner.close()
            raise RuntimeError("Another Flybet process owns this runs directory") from None
        self.brain_factory = brain_factory
        self.lock = threading.RLock()
        self.thread = None
        self.pause_requested = threading.Event()
        self.shutdown_requested = threading.Event()
        self.brain = self.game = self.run_dir = None
        self.insights = None
        self.activity_packet = None
        self.activity_identity = None
        self.image = display.frame([0, 1, 2], 10000, 10000)
        self.state = {
            "status": "idle",
            "phase": "ready",
            "run_id": None,
            "decision": 0,
            "dataset": {
                **EXPECTED,
                "name": "MaleCNS v1.0",
                "available": (self.data / "compiled/manifest.json").exists(),
            },
            "scenarios": SCENARIOS,
            "group_names": GROUP_NAMES,
            "model": MODEL,
            "telemetry": None,
            "series": [],
            "history": [],
            "insights": None,
            "game": None,
            "error": None,
            "revision": 0,
            "image_revision": 0,
        }

    def snapshot(self):
        with self.lock:
            state = copy.deepcopy(self.state)
            state["busy"] = bool(self.thread and self.thread.is_alive())
            return state

    def update(self, **values):
        with self.lock:
            self.state.update(values)
            self.state["revision"] += 1

    def start(self, config, single=False):
        with self.lock:
            self._idle_required()
            self.brain = None
            self.activity_packet = None
            self.activity_identity = None
            self.game = SlotGame(config)
            self.reward = RewardEncoder(config.reward, config.pulse)
            self.insights = Insights(asdict(config), MOTOR[config.motor]["threshold_hz"])
            self.image = display.frame(self.game.reels, self.game.bankroll, config.bankroll_cents)
            self.state["image_revision"] += 1
            self.policy_rng = random.Random(config.seed ^ 0xF17BE7)
            self.run_dir = self.runs / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
            self.run_dir.mkdir()
            self.pause_requested.clear()
            self.update(
                status="loading",
                phase="loading",
                run_id=self.run_dir.name,
                decision=0,
                game=self.game.summary(),
                config=asdict(config),
                history=[],
                insights=self.insights.snapshot(),
                model_identity=None,
                source_identity=None,
                runtime=None,
                series=[],
                telemetry=None,
                decoder=None,
                outcome=None,
                activity_id=None,
                protocol=None,
                interventions=[],
                learning_enabled=config.learning,
                templates=resolve(config),
                stop_reason=None,
                saving=False,
                error=None,
                started_at=time.time(),
            )
            self._launch(single)

    def _idle_required(self):
        if self.thread and self.thread.is_alive():
            raise Busy("A decision is in progress; pause and wait before starting another run")

    def start_protocol(self, config, settings):
        from .protocol import execute

        with self.lock:
            self._idle_required()
            self.brain = None
            self.activity_packet = self.activity_identity = None
            self.game = None
            self.insights = None
            self.run_dir = self.runs / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
            self.run_dir.mkdir()
            self.pause_requested.clear()
            self.update(
                status="running",
                phase="conditioning",
                run_id=self.run_dir.name,
                config=asdict(config),
                templates=resolve(config),
                decision=0,
                game=None,
                history=[],
                insights=None,
                series=[],
                telemetry=None,
                decoder=None,
                outcome=None,
                error=None,
                saving=False,
                model_identity=None,
                protocol=dict(status="running", completed_arms=0, total_arms=settings.seeds * 4),
                source_identity=None,
                activity_id=None,
                interventions=[],
            )
            self.thread = threading.Thread(
                target=execute, args=(self, config, settings), daemon=True
            )
            self.thread.start()

    def _launch(self, single):
        self.thread = threading.Thread(target=self._work, args=(single,), daemon=True)
        self.thread.start()

    def resume(self, single=False):
        with self.lock:
            self._idle_required()
            if self.brain is None or self.state["status"] != "paused":
                raise ValueError("Only a paused experiment can resume")
            self.pause_requested.clear()
            self.update(status="running")
            self._launch(single)

    def pause(self):
        self.pause_requested.set()
        self.update(pause_requested=True)

    def memory_control(self, operation):
        with self.lock:
            self._idle_required()
            if self.brain is None or self.state["status"] != "paused" or self.state.get("protocol"):
                raise ValueError("Pause a slot experiment before changing memory")
            if operation in ("enable", "freeze"):
                self.brain.learning = operation == "enable"
            elif operation in ("erase", "half"):
                self.brain.forget(1.0 if operation == "erase" else 0.5)
            elif operation == "reset-chemistry":
                self.brain.chemistry.reset()
                self.reward.expected = 0.0
            else:
                raise ValueError("Unknown memory operation")
            intervention = dict(operation=operation, after_decision=self.state["decision"])
            self.state["interventions"].append(intervention)
            self.log("intervention", **intervention)
            self.brain.checkpoint(self.run_dir / "brain.npz")
            self.update(
                learning_enabled=self.brain.learning,
                telemetry=self.brain.telemetry(self.brain.last_counts, 10, "none"),
            )

    def log(self, kind, **payload):
        row = {
            "kind": kind,
            "wall_time": time.time(),
            "decision": self.state["decision"],
            **payload,
        }
        with (self.run_dir / "events.jsonl").open("a") as f:
            f.write(json.dumps(row, allow_nan=False) + "\n")
            f.flush()

    def show(self, phase):
        image = display.frame(
            self.game.reels, self.game.bankroll, self.game.config.bankroll_cents, phase
        )
        with self.lock:
            self.image = image
            self.state["image_revision"] += 1
        Image.fromarray(image).save(
            self.run_dir / f"input-{self.state['decision']:06d}-{phase}.png"
        )
        self.update(phase=phase)
        return image

    def telemetry(self, data):
        with self.lock:
            if hasattr(self.brain, "activity"):
                self.activity_packet = self.brain.activity.packet(data["neural_ms"])
                self.activity_identity = (
                    self.state.get("activity_id") or self.state["run_id"],
                    self.brain.manifest["arrays"]["ids"],
                )
            self.state["telemetry"] = data
            self.state["series"].append(
                {
                    "ms": data["neural_ms"],
                    "pam": data["rates_hz"][4],
                    "ppl": data["rates_hz"][5],
                    "kc": data["rates_hz"][3],
                    "efficacy": data["memory"]["mean"],
                    "stimulus": data["stimulus"],
                }
            )
            self.state["series"] = self.state["series"][-240:]
            self.state["revision"] += 1
        self.log("neural", phase=self.state["phase"], **data)

    def _work(self, single):
        try:
            if self.brain is None:
                self.brain = self.brain_factory(
                    self.data, learning=self.game.config.learning, config=self.game.config
                )
                source = Path(__file__).parent
                provenance = {
                    "config": asdict(self.game.config),
                    "model": MODEL,
                    "templates": resolve(self.game.config),
                    "runtime": self.brain.runtime_metadata(),
                    "dataset": self.brain.manifest,
                    "sources": {
                        str(p.relative_to(source)): sha256(p)
                        for p in source.rglob("*")
                        if p.suffix in (".py", ".cpp", ".js", ".html", ".css")
                    },
                    "dopamine_cells": {
                        name: [
                            str(i)
                            for i in self.brain.arrays["ids"][self.brain.arrays["group"] == group]
                        ]
                        for name, group in [("PAM11", 4), ("PPL101", 5)]
                    },
                    "decoder": (
                        "Configured neural signal plus DNpe017 gate chooses SPIN/WAIT; "
                        "The declared wealth template weights the signal margin for "
                        "1x/2x/4x adaptive tiers using accumulated pre-decision bankroll. "
                        "It does not change SPIN/WAIT or measured firing rates."
                    ),
                }
                atomic_json(self.run_dir / "provenance.json", provenance)
                self.update(
                    anatomy=self.brain.arrays["anatomy"].tolist(),
                    group_sizes=self.brain.group_sizes.tolist(),
                    dataset={**self.state["dataset"], "verified": True},
                    model_identity=model_identity(provenance),
                    source_identity=model_identity(provenance, include_templates=False),
                    runtime=provenance["runtime"],
                )
                self.log(
                    "start",
                    config=asdict(self.game.config),
                    provenance_sha256=sha256(self.run_dir / "provenance.json"),
                )
            self.update(status="running", pause_requested=False)
            while not self.shutdown_requested.is_set():
                if (
                    self.state["decision"] >= self.game.config.max_decisions
                    or self.game.bankroll < self.game.config.stake_cents
                ):
                    reason = (
                        "Decision limit reached"
                        if self.state["decision"] >= self.game.config.max_decisions
                        else "Simulated bankroll exhausted"
                    )
                    self.update(status="finished", phase="complete", stop_reason=reason)
                    break
                self.update(decision=self.state["decision"] + 1)
                observation = self.brain.advance(
                    self.show("observe"), MODEL["decision_ms"], callback=self.telemetry
                )
                decoded = wager_decision(
                    observation["decoder"], self.game.config, self.game.bankroll
                )
                observation["decoder"] = decoded
                action = decoded["action"]
                if self.game.config.policy == "random-baseline":
                    action = "SPIN" if self.policy_rng.random() < 0.5 else "WAIT"
                stakes = allowed_stakes(self.game.config, self.game.bankroll)
                requested = self.game.config.stake_cents * (
                    decoded.get("requested_multiplier", 1)
                    if self.game.config.wager_mode == "adaptive"
                    else 1
                )
                if self.game.config.policy == "random-baseline" and action == "SPIN":
                    requested = self.policy_rng.choice(stakes)
                stake = max((v for v in stakes if v <= requested), default=stakes[0])
                self.update(
                    decoder={
                        **decoded,
                        "executed_action": action,
                        "policy": self.game.config.policy,
                        "requested_stake_cents": requested if action == "SPIN" else 0,
                        "executed_stake_cents": stake if action == "SPIN" else 0,
                    },
                    phase="spin" if action == "SPIN" else "wait",
                )
                self.log(
                    "decision",
                    observation=observation,
                    action=action,
                    policy=self.game.config.policy,
                )
                outcome = (
                    self.game.spin(stake)
                    if action == "SPIN"
                    else {
                        "reels": self.game.reels.copy(),
                        "net_cents": 0,
                        "payout_cents": 0,
                        "stake_cents": 0,
                        "bankroll_cents": self.game.bankroll,
                        "won": False,
                    }
                )
                reinforcement = self.reward.encode(
                    outcome["net_cents"], self.game.config.stake_cents, action == "SPIN"
                )
                stimulus = reinforcement["stimulus"]
                self.update(game=self.game.summary(), outcome=outcome)
                feedback = self.brain.advance(
                    self.show("feedback" if action == "SPIN" else "wait"),
                    MODEL["feedback_ms"],
                    stimulus,
                    self.telemetry,
                    reinforcement=reinforcement,
                )
                row = {
                    "decision": self.state["decision"],
                    "action": action,
                    "stimulus": stimulus,
                    "reinforcement": reinforcement,
                    "bankroll_context": decoded["bankroll_context"],
                    "requested_stake_cents": requested if action == "SPIN" else 0,
                    **outcome,
                    "pam_spikes": feedback["spikes"][4],
                    "ppl_spikes": feedback["spikes"][5],
                    "neural_ms": feedback["neural_ms"],
                    "changed_edges": feedback["memory"]["changed"],
                }
                self.log("outcome", **row, feedback=feedback)
                with self.lock:
                    self.insights.add(row, observation, feedback)
                    self.state["history"] = (self.state["history"] + [row])[-100:]
                    self.state["insights"] = self.insights.snapshot()
                    self.state["revision"] += 1
                if single or self.pause_requested.is_set():
                    self.update(status="paused", phase="paused")
                    break
            if self.shutdown_requested.is_set():
                self.update(status="paused", phase="paused")
            self.update(saving=True)
            self.brain.checkpoint(self.run_dir / "brain.npz")
            atomic_json(
                self.run_dir / "summary.json",
                {
                    "run_id": self.run_dir.name,
                    "decisions": self.state["decision"],
                    "status": self.state["status"],
                    "game": self.game.summary(),
                    "neural_ms": self.brain.neural_ms,
                    "insights": self.insights.snapshot(),
                    "interventions": self.state["interventions"],
                },
            )
            self.update(saving=False, pause_requested=False)
        except Exception as error:
            traceback.print_exc()
            self.update(
                status="error",
                phase="error",
                error=f"{type(error).__name__}: {error}",
                saving=False,
            )
            if self.run_dir:
                atomic_json(
                    self.run_dir / "error.json",
                    {"error": str(error), "decision": self.state["decision"], "partial_run": True},
                )

    def close(self):
        self.shutdown_requested.set()
        if self.thread:
            self.thread.join(timeout=60)
        if self.thread and self.thread.is_alive():
            # Keep ownership until the process exits if native work hasn't finished.
            return
        self.owner.close()
