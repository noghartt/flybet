"""Read-only, whole-run behavioral measurements. Never feeds the controller."""

import copy
import hashlib
import json
import math
import re
from collections import deque
from pathlib import Path

from .game import SCENARIOS, Config, allowed_stakes

SCHEMA = 2
FOLLOWUP = 5
RUN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$")


def ratio(value, count):
    return value / count if count else None


class Insights:
    def __init__(self, config, threshold=2.0):
        self.config = dict(config)
        self.threshold = threshold
        self.count = self.spins = self.wins = self.wagered = self.returned = 0
        self.bankroll = config["bankroll_cents"]
        self.risk_sum = 0.0
        self.max_risk = None
        self.previous = None
        self.previous_stake = 0
        self.stake_tiers = {"1": 0, "2": 0, "4": 0}
        self.wealth_decisions = self.wealth_spins = self.wealth_higher = self.wealth_lower = 0
        self.pending = []
        self.recent = deque(maxlen=20)
        self.wait_reasons = dict(gate_only=0, direction_only=0, both=0, unavailable=0)
        self.conditions = {
            name: dict(
                events=0,
                next_n=0,
                next_spins=0,
                next_wagered=0,
                next_risk_sum=0.0,
                next_bet_increases=0,
                windows=0,
                window_wagered=0,
                response_n=0,
                pam_before=0.0,
                pam_after=0.0,
                ppl_before=0.0,
                ppl_after=0.0,
            )
            for name in ("win", "loss", "wait")
        }
        self.bins = []
        self.bin_size = 1
        self.changed_edges = self.efficacy = None

    def add(self, row, observation=None, feedback=None):
        """Consume each completed decision exactly once, in order."""
        if row["decision"] != self.count + 1:
            raise ValueError("Insight records must be consecutive completed decisions")
        action = row["action"]
        stake, payout, net = row["stake_cents"], row["payout_cents"], row["net_cents"]
        if action not in ("SPIN", "WAIT") or any(type(v) is not int for v in (stake, payout, net)):
            raise ValueError("Invalid decision or cent amounts in insight record")
        if (action == "WAIT" and (stake or payout or net)) or (
            action == "SPIN" and stake not in allowed_stakes(Config(**self.config), self.bankroll)
        ):
            raise ValueError("Insight record contradicts the configured stake tiers")
        if payout - stake != net or row["bankroll_cents"] != self.bankroll + net:
            raise ValueError("Insight record fails bankroll reconciliation")
        if stake > self.bankroll or stake < 0 or payout < 0:
            raise ValueError("Invalid wager in insight record")
        spin = int(action == "SPIN")
        category = "wait" if not spin else "win" if net > 0 else "loss"
        risk = stake / self.bankroll if spin else 0.0
        self.count += 1
        self.spins += spin
        self.wins += int(category == "win")
        self.wagered += stake
        self.returned += payout
        self.bankroll = row["bankroll_cents"]
        self.risk_sum += risk
        if spin:
            self.max_risk = max(self.max_risk or 0, risk)
            self.stake_tiers[str(stake // self.config["stake_cents"])] += 1
        self.recent.append(spin)

        if self.previous:
            group = self.conditions[self.previous]
            group["next_n"] += 1
            group["next_spins"] += spin
            group["next_wagered"] += stake
            group["next_risk_sum"] += risk
            group["next_bet_increases"] += int(
                spin and self.previous_stake > 0 and stake > self.previous_stake
            )
        # Full fixed-length follow-ups only. The triggering bet is excluded.
        remaining = []
        for window in self.pending:
            window["n"] += 1
            window["wagered"] += stake
            if window["n"] == FOLLOWUP:
                group = self.conditions[window["category"]]
                group["windows"] += 1
                group["window_wagered"] += window["wagered"]
            else:
                remaining.append(window)
        self.pending = remaining
        if spin:
            self.pending.append(dict(category=category, n=0, wagered=0))
        self.conditions[category]["events"] += 1
        self.previous = category
        self.previous_stake = stake

        observation, feedback = observation or {}, feedback or {}
        context = observation.get("decoder", {}).get("bankroll_context", {})
        if context.get("applied"):
            self.wealth_decisions += 1
            self.wealth_spins += spin
            if spin:
                self.wealth_higher += int(
                    context["proposed_multiplier"] > context["unweighted_multiplier"]
                )
                self.wealth_lower += int(
                    context["proposed_multiplier"] < context["unweighted_multiplier"]
                )
        before, after = observation.get("rates_hz", []), feedback.get("rates_hz", [])
        if len(before) > 5 and len(after) > 5:
            values = [before[4], after[4], before[5], after[5]]
            if all(math.isfinite(v) and v >= 0 for v in values):
                group = self.conditions[category]
                group["response_n"] += 1
                for name, value in zip(
                    ("pam_before", "pam_after", "ppl_before", "ppl_after"), values, strict=True
                ):
                    group[name] += value
        if not spin and self.config["policy"] == "neural":
            decoder = observation.get("decoder", {})
            gate, difference = decoder.get("gate_spikes"), decoder.get("difference_hz")
            if gate is None or difference is None:
                reason = "unavailable"
            else:
                silent, low = gate == 0, difference < self.threshold
                reason = (
                    "both"
                    if silent and low
                    else "gate_only"
                    if silent
                    else "direction_only"
                    if low
                    else "unavailable"
                )
            self.wait_reasons[reason] += 1
        memory = feedback.get("memory", {})
        self.changed_edges = memory.get("changed", row.get("changed_edges"))
        self.efficacy = memory.get("mean")
        if not self.bins or self.bins[-1]["n"] >= self.bin_size:
            self.bins.append(
                dict(
                    start=self.count,
                    end=self.count,
                    n=0,
                    spins=0,
                    wagered=0,
                    risk_sum=0.0,
                    bankroll=self.bankroll,
                    changed_edges=None,
                    efficacy=None,
                )
            )
        bucket = self.bins[-1]
        bucket.update(
            end=self.count,
            bankroll=self.bankroll,
            changed_edges=self.changed_edges,
            efficacy=self.efficacy,
            chemistry_exposure=feedback.get("chemistry", {}).get("exposure"),
            reward_gain=feedback.get("chemistry", {}).get("reward_gain"),
            withdrawal_current=feedback.get("chemistry", {}).get("withdrawal_current"),
            wealth_gain=context.get("gain"),
        )
        bucket["n"] += 1
        bucket["spins"] += spin
        bucket["wagered"] += stake
        bucket["risk_sum"] += risk
        # Pairwise merging preserves counts and whole-run coverage in bounded telemetry.
        if len(self.bins) > 80:
            merged = []
            for i in range(0, len(self.bins), 2):
                a = self.bins[i].copy()
                if i + 1 < len(self.bins):
                    b = self.bins[i + 1]
                    for key in ("n", "spins", "wagered", "risk_sum"):
                        a[key] += b[key]
                    for key in (
                        "end",
                        "bankroll",
                        "changed_edges",
                        "efficacy",
                        "chemistry_exposure",
                        "reward_gain",
                        "withdrawal_current",
                        "wealth_gain",
                    ):
                        a[key] = b[key]
                merged.append(a)
            self.bins = merged
            self.bin_size *= 2

    def snapshot(self):
        groups = {}
        for name, raw in self.conditions.items():
            groups[name] = {
                **raw,
                "next_spin_rate": ratio(raw["next_spins"], raw["next_n"]),
                "next_bet_increase_rate": ratio(raw["next_bet_increases"], raw["next_n"]),
                "next_mean_wager_cents": ratio(raw["next_wagered"], raw["next_n"]),
                "next_mean_bankroll_fraction": ratio(raw["next_risk_sum"], raw["next_n"]),
                "mean_followup_wager_cents": ratio(raw["window_wagered"], raw["windows"]),
                "without_next_decision": raw["events"] - raw["next_n"],
                "incomplete_followups": raw["events"] - raw["windows"] if name != "wait" else None,
                "response": {
                    key: ratio(raw[key], raw["response_n"])
                    for key in ("pam_before", "pam_after", "ppl_before", "ppl_after")
                },
            }
        win, loss = groups["win"], groups["loss"]
        difference = (
            win["next_spin_rate"] - loss["next_spin_rate"]
            if win["next_n"] and loss["next_n"]
            else None
        )
        spend_difference = (
            win["mean_followup_wager_cents"] - loss["mean_followup_wager_cents"]
            if win["windows"] and loss["windows"]
            else None
        )
        return {
            "schema": SCHEMA,
            "decisions": self.count,
            "spins": self.spins,
            "wins": self.wins,
            "waits": self.count - self.spins,
            "play_rate": ratio(self.spins, self.count),
            "recent_play_rate": ratio(sum(self.recent), len(self.recent)),
            "recent_decisions": len(self.recent),
            "wagered_cents": self.wagered,
            "returned_cents": self.returned,
            "bankroll_cents": self.bankroll,
            "net_cents": self.bankroll - self.config["bankroll_cents"],
            "expected_net_cents": self.wagered * (SCENARIOS[self.config["scenario"]]["rtp"] - 1),
            "mean_stake_cents": ratio(self.wagered, self.spins),
            "stake_tiers": dict(self.stake_tiers),
            "bankroll_influence": {
                "decisions": self.wealth_decisions,
                "spins": self.wealth_spins,
                "higher_proposals": self.wealth_higher,
                "lower_proposals": self.wealth_lower,
            },
            "mean_bankroll_fraction_per_spin": ratio(self.risk_sum, self.spins),
            "max_bankroll_fraction_per_spin": self.max_risk,
            "followup_decisions": FOLLOWUP,
            "conditions": groups,
            "next_spin_difference": difference,
            "followup_spending_difference_cents": spend_difference,
            "wait_reasons": dict(self.wait_reasons),
            "changed_edges": self.changed_edges,
            "mean_efficacy": self.efficacy,
            "bin_size": self.bin_size,
            "timeline": [
                {
                    **b,
                    "play_rate": b["spins"] / b["n"],
                    "mean_fraction_per_decision": b["risk_sum"] / b["n"],
                }
                for b in self.bins
            ],
        }


def model_identity(provenance, include_templates=True):
    """Conditions that must match before a saved run can be compared."""
    value = {
        "model": provenance.get("model"),
        "arrays": provenance.get("dataset", {}).get("arrays"),
        "native": provenance.get("runtime", {}).get("native_source_sha256"),
        **{
            name: provenance.get("sources", {}).get(name)
            for name in ("neural.py", "display.py", "game.py")
        },
    }
    if provenance.get("templates"):
        if include_templates:
            value["templates"] = provenance["templates"]
        for name in ("templates.py", "reinforcement.py", "experiment.py", "protocol.py"):
            value[name] = provenance.get("sources", {}).get(name)
    if any(v is None for v in value.values()):
        return None
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class InsightArchive:
    """Read existing records without altering or resuming past experiments."""

    def __init__(self, root):
        self.root = Path(root)
        self.cache = {}

    def directory(self, run_id):
        if not RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid run identifier")
        directory = self.root / run_id
        if directory.is_symlink() or not directory.is_dir():
            raise FileNotFoundError("Recorded run unavailable")
        return directory

    def metadata(self, directory):
        provenance = json.loads((directory / "provenance.json").read_text())
        summary_path = directory / "summary.json"
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        return {
            "run_id": directory.name,
            "config": provenance["config"],
            "status": summary.get("status", "partial"),
            "decisions": summary.get("decisions"),
            "model_identity": model_identity(provenance),
            "source_identity": model_identity(provenance, include_templates=False),
            "runtime": provenance.get("runtime", {}),
            "interventions": summary.get("interventions", []),
        }

    def catalog(self, exclude_run_id=None):
        entries, unavailable = [], 0
        directories = sorted(
            (
                p
                for p in self.root.iterdir()
                if p.name != exclude_run_id
                and RUN_ID.fullmatch(p.name)
                and p.is_dir()
                and not p.is_symlink()
                and not (p / "protocol.json").exists()
            ),
            reverse=True,
        )
        for directory in directories[:200]:
            try:
                entries.append(self.metadata(directory))
            except (OSError, ValueError, KeyError):
                unavailable += 1
        return {
            "runs": entries,
            "unavailable": unavailable,
            "omitted": max(0, len(directories) - 200),
        }

    def read(self, run_id):
        directory = self.directory(run_id)
        path = directory / "events.jsonl"
        stat = path.stat()
        summary = directory / "summary.json"
        key = (
            run_id,
            stat.st_size,
            stat.st_mtime_ns,
            summary.stat().st_mtime_ns if summary.exists() else None,
        )
        if key in self.cache:
            return copy.deepcopy(self.cache[key])
        meta = self.metadata(directory)
        provenance = json.loads((directory / "provenance.json").read_text())
        metrics = Insights(
            meta["config"], provenance.get("model", {}).get("decoder_threshold_hz", 2)
        )
        observation, warnings, interventions = None, [], []
        with path.open() as stream:
            for line in stream:
                if not line.endswith("\n"):
                    warnings.append("The final log line is incomplete; it is excluded.")
                    break
                record = json.loads(line)
                if record.get("kind") == "intervention":
                    interventions.append({k: record[k] for k in ("operation", "after_decision")})
                if record.get("kind") == "decision":
                    if observation or record["decision"] != metrics.count + 1:
                        raise ValueError("Decision records are duplicated or out of order")
                    observation = record
                elif record.get("kind") == "outcome":
                    if not observation or observation["decision"] != record["decision"]:
                        raise ValueError("Outcome has no matching decision record")
                    if observation.get("action") not in (None, record["action"]):
                        raise ValueError("Outcome action contradicts its decision record")
                    metrics.add(record, observation.get("observation"), record.get("feedback"))
                    observation = None
        if observation:
            warnings.append("A decision has no completed feedback record; it is excluded.")
        if interventions:
            warnings.append("This run contains recorded memory or chemistry interventions.")
        result = {
            **meta,
            "interventions": interventions,
            "metrics": metrics.snapshot(),
            "warnings": warnings,
        }
        # Bound cached results; identities change when a log is appended.
        if len(self.cache) >= 8:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = copy.deepcopy(result)
        return result
