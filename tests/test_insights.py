import copy
import json
from dataclasses import asdict

import pytest

from flybet.game import Config
from flybet.insights import InsightArchive, Insights, model_identity


def record(metrics, outcome, observation=None, feedback=None):
    stake = metrics.config["stake_cents"] if outcome != "wait" else 0
    payout = stake * 16 if outcome == "win" else 0
    row = {
        "decision": metrics.count + 1,
        "action": "WAIT" if outcome == "wait" else "SPIN",
        "stake_cents": stake,
        "payout_cents": payout,
        "net_cents": payout - stake,
        "bankroll_cents": metrics.bankroll + payout - stake,
    }
    metrics.add(row, observation, feedback)
    return row


def test_next_decision_and_five_decision_spending_exclude_the_trigger_and_incomplete_windows():
    metrics = Insights(asdict(Config()))
    record(metrics, "win")
    first = metrics.snapshot()["conditions"]["win"]
    assert first["next_spin_rate"] is None and first["mean_followup_wager_cents"] is None
    for outcome in ["loss", "wait", "loss", "wait", "wait", "wait", "wait", "wait"]:
        record(metrics, outcome)
    result = metrics.snapshot()
    win, loss = result["conditions"]["win"], result["conditions"]["loss"]
    assert (win["next_spins"], win["next_n"], win["next_spin_rate"]) == (1, 1, 1)
    assert (loss["next_spins"], loss["next_n"], loss["next_spin_rate"]) == (0, 2, 0)
    assert win["mean_followup_wager_cents"] == 200 and win["windows"] == 1
    assert loss["mean_followup_wager_cents"] == 50 and loss["windows"] == 2
    assert result["followup_spending_difference_cents"] == 150
    assert result["conditions"]["wait"]["without_next_decision"] == 1
    assert result["play_rate"] == 3 / 9
    assert result["net_cents"] == 1300 and result["wagered_cents"] == 300


def test_no_wins_and_bankruptcy_do_not_manufacture_followup_waits():
    metrics = Insights(asdict(Config(bankroll_cents=100)))
    record(metrics, "loss")
    result = metrics.snapshot()
    assert result["bankroll_cents"] == 0
    assert result["conditions"]["loss"]["without_next_decision"] == 1
    assert result["conditions"]["loss"]["next_spin_rate"] is None
    assert result["conditions"]["loss"]["incomplete_followups"] == 1
    assert result["conditions"]["win"]["next_spin_rate"] is None
    assert result["next_spin_difference"] is None
    assert result["mean_bankroll_fraction_per_spin"] == 1
    json.dumps(result, allow_nan=False)


def test_bankroll_share_uses_pre_bet_balance_and_fixed_bets_can_shrink_as_a_fraction():
    metrics = Insights(asdict(Config()))
    record(metrics, "win")  # 100 -> 115, with 1 wagered out of 100
    record(metrics, "loss")  # another 1 wagered, this time out of 115
    record(metrics, "wait")
    result = metrics.snapshot()
    assert result["mean_stake_cents"] == 100
    assert result["mean_bankroll_fraction_per_spin"] == pytest.approx((0.01 + 100 / 11500) / 2)
    assert result["max_bankroll_fraction_per_spin"] == 0.01
    assert result["timeline"][2]["mean_fraction_per_decision"] == 0
    assert result["wagered_cents"] == 200
    assert result["conditions"]["win"]["next_mean_bankroll_fraction"] == 100 / 11500
    assert result["conditions"]["loss"]["next_mean_bankroll_fraction"] == 0


def test_long_run_matches_independent_event_analysis_beyond_the_ui_history_limit():
    metrics = Insights(asdict(Config(bankroll_cents=1000000, max_decisions=2000)))
    sequence = ["win" if i % 13 == 0 else "loss" if i % 3 == 0 else "wait" for i in range(1001)]
    for outcome in sequence:
        record(metrics, outcome)
    result = metrics.snapshot()
    for category in ("win", "loss"):
        next_actions = [
            sequence[i + 1] for i, event in enumerate(sequence[:-1]) if event == category
        ]
        windows = [
            sequence[i + 1 : i + 6] for i, event in enumerate(sequence[:-5]) if event == category
        ]
        group = result["conditions"][category]
        assert group["next_n"] == len(next_actions)
        assert group["next_spins"] == sum(a != "wait" for a in next_actions)
        assert group["windows"] == len(windows)
        assert group["window_wagered"] == sum(100 for w in windows for a in w if a != "wait")
    assert result["decisions"] == 1001 and len(result["timeline"]) <= 80
    assert sum(b["n"] for b in result["timeline"]) == 1001
    assert sum(b["wagered"] for b in result["timeline"]) == result["wagered_cents"]
    assert result["timeline"][0]["start"] == 1 and result["timeline"][-1]["end"] == 1001
    assert all(
        a["end"] + 1 == b["start"]
        for a, b in zip(result["timeline"], result["timeline"][1:], strict=False)
    )
    assert result["recent_play_rate"] == sum(a != "wait" for a in sequence[-20:]) / 20


def test_neural_response_uses_rates_and_wait_reasons_are_exclusive():
    metrics = Insights(asdict(Config()))
    observations = []
    for gate, difference in [(0, 3), (1, 1), (0, 1)]:
        obs = {
            "rates_hz": [0, 0, 0, 0, 2, 5],
            "decoder": {"gate_spikes": gate, "difference_hz": difference},
        }
        feedback = {"rates_hz": [0, 0, 0, 0, 20, 15], "memory": {"mean": 1.25, "changed": 30}}
        observations.append(copy.deepcopy(obs))
        record(metrics, "wait", obs, feedback)
        assert obs == observations[-1]
    result = metrics.snapshot()
    assert result["wait_reasons"] == dict(gate_only=1, direction_only=1, both=1, unavailable=0)
    response = result["conditions"]["wait"]["response"]
    assert response == dict(pam_before=2, pam_after=20, ppl_before=5, ppl_after=15)
    assert result["changed_edges"] == 30 and result["mean_efficacy"] == 1.25
    baseline = Insights(asdict(Config(policy="random-baseline")))
    record(baseline, "wait", obs, feedback)
    assert sum(baseline.snapshot()["wait_reasons"].values()) == 0


def test_duplicate_or_unreconciled_records_are_rejected():
    metrics = Insights(asdict(Config()))
    row = record(metrics, "loss")
    with pytest.raises(ValueError, match="consecutive"):
        metrics.add(row)
    bad = {**row, "decision": 2}
    with pytest.raises(ValueError, match="reconciliation"):
        metrics.add(bad)
    assert metrics.count == 1


def test_comparison_identity_includes_neural_and_environment_code_but_not_presentation():
    provenance = {
        "model": {"threshold": 2},
        "dataset": {"arrays": {"ids": "a"}},
        "runtime": {"native_source_sha256": "b"},
        "sources": {"neural.py": "c", "display.py": "d", "game.py": "e"},
    }
    original = model_identity(provenance)
    assert original is not None
    provenance["sources"]["web/app.js"] = "new chart"
    assert model_identity(provenance) == original
    provenance["sources"]["neural.py"] = "different learning rule"
    assert model_identity(provenance) != original
    del provenance["sources"]["game.py"]
    assert model_identity(provenance) is None


def test_archive_replays_old_records_and_detects_growth_partial_lines_and_invalid_ids(tmp_path):
    run = tmp_path / "20260910-000000-12345678"
    run.mkdir()
    config = asdict(Config())
    (run / "provenance.json").write_text(json.dumps({"config": config, "model": {}}))
    metrics = Insights(config)
    path = run / "events.jsonl"
    rows = []
    for result in ["win", "loss"]:
        row = record(metrics, result)
        rows += [
            {"kind": "decision", "decision": row["decision"], "observation": {}},
            {"kind": "outcome", **row},
        ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    archive = InsightArchive(tmp_path)
    assert archive.read(run.name)["metrics"] == metrics.snapshot()
    cached = archive.read(run.name)
    cached["metrics"]["decisions"] = 999
    assert archive.read(run.name)["metrics"]["decisions"] == 2
    with path.open("a") as stream:
        stream.write('{"kind": "neural"')
    partial = archive.read(run.name)
    assert partial["warnings"] and partial["metrics"]["decisions"] == 2
    assert archive.catalog()["runs"][0]["run_id"] == run.name
    assert archive.catalog(exclude_run_id=run.name) == {"runs": [], "unavailable": 0, "omitted": 0}
    with pytest.raises(ValueError, match="identifier"):
        archive.read("../elsewhere")
    with pytest.raises(FileNotFoundError):
        archive.read("20260910-000000-87654321")
