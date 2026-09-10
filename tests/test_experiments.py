import os
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from flybet.display import cue_frame
from flybet.experiment import Experiment
from flybet.game import Config, SlotGame, allowed_stakes
from flybet.insights import InsightArchive, Insights
from flybet.neural import Brain, Native, Plasticity, decode
from flybet.protocol import ARMS, ProtocolConfig, summarize
from flybet.reinforcement import Chemistry, RewardEncoder, pulse_current
from flybet.server import create_app
from flybet.templates import CATALOG, PHYSIOLOGY


def test_templates_are_validated_and_legacy_defaults_still_work():
    for name, presets in CATALOG.items():
        for value in presets:
            Config(**{name: value})
        with pytest.raises(ValueError):
            Config(**{name: "unknown"})
    with pytest.raises(ValueError):
        Config(wager_mode="unbounded")
    for kwargs in (dict(seeds=True), dict(trials=3), dict(retention_seconds=-1)):
        with pytest.raises(ValueError):
            ProtocolConfig(**kwargs)


def test_wager_tiers_affordability_and_outcome_rng_independence():
    config = Config(wager_mode="adaptive", bankroll_cents=100000)
    a, b = SlotGame(config), SlotGame(config)
    for stake in [100, 400, 200] * 10:
        x, y = a.spin(stake), b.spin(100)
        assert x["reels"] == y["reels"]
        assert x["net_cents"] * 100 == y["net_cents"] * stake
    assert a.bankroll == config.bankroll_cents + a.returned - a.wagered
    assert allowed_stakes(config, 350) == [100, 200]
    for stake in (0, 300, True):
        with pytest.raises(ValueError):
            a.spin(stake)
    with pytest.raises(ValueError):
        SlotGame(Config()).spin(200)


def test_neural_mapping_controls_direction_gate_and_wager_tier():
    groups = np.array([8, 9, 10, 6, 7])
    for spikes, tier in [(1, 1), (3, 2), (6, 4)]:
        result = decode(np.array([0, spikes, 1, 0, 0]), groups, 300)
        assert result["action"] == "SPIN" and result["requested_multiplier"] == tier
    assert decode(np.array([0, 20, 0, 0, 0]), groups, 300)["action"] == "WAIT"
    assert decode(np.array([0, 6, 1, 0, 0]), groups, 300, "mirror")["action"] == "WAIT"
    counts = np.array([0, 0, 1, 0, 30])
    assert decode(counts, groups, 300)["action"] == "WAIT"
    assert decode(counts, groups, 300, "mbon-assisted")["action"] == "SPIN"


def test_reward_expected_value_is_updated_after_encoding_and_wait_is_neutral():
    encoder = RewardEncoder("prediction-error")
    first = encoder.encode(100, 100)
    assert first["expected_before"] == 0 and first["amplitude"] == 20
    second = encoder.encode(100, 100)
    assert second["amplitude"] == pytest.approx(18)
    before = encoder.expected
    assert encoder.encode(0, 100, played=False)["amplitude"] == 0
    assert encoder.expected == before
    assert encoder.encode(0, 100)["stimulus"] == "aversive"
    assert RewardEncoder("magnitude").encode(1500, 100)["amplitude"] == 40
    assert RewardEncoder("off").encode(1500, 100)["stimulus"] == "none"
    assert RewardEncoder().encode(-100, 100)["stimulus"] == "aversive"


def test_pulse_durations_delays_and_integrals():
    dose = {
        p: sum(pulse_current(p, 20, t) * 0.01 for t in range(0, 200, 10)) for p in CATALOG["pulse"]
    }
    assert dose == pytest.approx(dict(sustained=4, brief=1, delayed=2, ramp=2))
    assert pulse_current("delayed", 20, 90) == 0
    assert pulse_current("delayed", 20, 100) == 20
    assert pulse_current("brief", 20, 50) == 0


def test_chemistry_accumulates_is_bounded_recovers_and_resets():
    base, sensitized, tolerant = [Chemistry(name) for name in CATALOG["chemistry"]]
    for _ in range(500):
        for model in (base, sensitized, tolerant):
            model.step("reward", 20)
    assert base.last["reward_gain"] == 1 and base.exposure == 0
    assert 1 < sensitized.last["reward_gain"] <= 3
    assert 0 < tolerant.last["reward_gain"] < 1
    assert tolerant.step("none", 0)["withdrawal_current"] > 0
    previous = tolerant.exposure
    tolerant.step("none", 0, seconds=600)
    assert tolerant.exposure < previous / 1000
    tolerant.reset()
    assert tolerant.exposure == 0 and tolerant.last["reward_gain"] == 1


@pytest.mark.parametrize("preset", PHYSIOLOGY)
def test_physiology_single_cell_matches_independent_subthreshold_solution(preset):
    p = PHYSIOLOGY[preset]
    native = Native([0, 0], [], [], [0], [0], preset)
    native.advance([1], 10)
    expected = p["rest_mv"] + 1 - np.exp(-10 / p["membrane_tau_ms"])
    assert native.v[0] == pytest.approx(expected, abs=0.002)
    assert native.parameters[2] == p["threshold_mv"]


def test_fast_forgetting_and_frozen_memory():
    normal = Plasticity(np.ones(1), np.ones((1, 1)))
    fast = Plasticity(np.ones(1), np.ones((1, 1)), "fast-forgetting")
    for model in (normal, fast):
        model.efficacy[:] = 1.5
        for _ in range(100):
            model.step(np.zeros(1), np.zeros(1), 0.01)
    assert fast.efficacy[0] < normal.efficacy[0]
    before = fast.efficacy.copy()
    for _ in range(100):
        fast.step(np.ones(1), np.ones(1), 0.01, False)
    np.testing.assert_array_equal(before, fast.efficacy)


def test_adaptive_metrics_measure_increases_and_include_wait_denominators():
    c = Config(wager_mode="adaptive")
    game, metrics = SlotGame(c), Insights(asdict(c))
    game.draw = lambda: [0, 0, 0]
    for stake in (100, 400):
        metrics.add(dict(decision=metrics.count + 1, action="SPIN", **game.spin(stake)))
    metrics.add(
        dict(
            decision=3,
            action="WAIT",
            stake_cents=0,
            payout_cents=0,
            net_cents=0,
            bankroll_cents=game.bankroll,
        )
    )
    s = metrics.snapshot()
    assert s["conditions"]["win"]["next_bet_increase_rate"] == 0.5
    assert s["stake_tiers"] == {"1": 1, "2": 0, "4": 1}
    assert s["mean_stake_cents"] == 250


def test_conditioning_cues_have_equal_color_area_and_do_not_encode_reward():
    a, b = cue_frame(0), cue_frame(1)
    assert not np.array_equal(a, b)
    np.testing.assert_array_equal(np.sort(a.ravel()), np.sort(b.ravel()))


def test_learning_conclusion_requires_complete_paired_choice_evidence():
    rows = []
    for seed in range(5):
        for arm in ARMS:
            rows.append(
                dict(
                    seed=seed,
                    arm=arm,
                    choice_change=0,
                    signal_change=10 if arm == "trained" else 0,
                    tier_change=0,
                )
            )
    assert summarize(rows, 5)["conclusion"] == "learning-not-established"
    for r in rows:
        r["choice_change"] = int(r["arm"] == "trained")
    assert summarize(rows, 5)["conclusion"] == "candidate-memory-dependent-choice-effect"
    assert summarize(rows[:-1], 5)["conclusion"] == "learning-not-established"


class ProtocolTestBrain:
    """Tiny test double to check orchestration; not exposed by the application."""

    def __init__(self, root, learning=True, config=None):
        self.learning = learning
        self.manifest = {"dataset": "TEST ONLY"}
        self.arrays = dict(anatomy=np.eye(12), group=np.arange(12), ids=np.arange(12))
        self.group_sizes = np.ones(12, int)
        self.memory = SimpleNamespace(efficacy=np.ones(2), decay_seconds=1800)
        self.neural_ms = 0
        self.chemistry = Chemistry()
        self.last_counts = np.zeros(12, int)

    def clear_transients(self, reset_chemistry=True):
        if reset_chemistry:
            self.chemistry.reset()

    def forget(self, fraction=1):
        self.memory.efficacy[:] = 1 + (self.memory.efficacy - 1) * (1 - fraction)

    def runtime_metadata(self):
        return {"backend": "TEST ONLY"}

    def telemetry(self, counts, ms, stimulus):
        return dict(
            neural_ms=self.neural_ms,
            spikes=[0] * 12,
            rates_hz=[0] * 12,
            stimulus=stimulus,
            memory=dict(
                mean=float(self.memory.efficacy.mean()),
                changed=int(np.count_nonzero(self.memory.efficacy != 1)),
            ),
        )

    def advance(self, image, milliseconds, stimulus="none", callback=None, reinforcement=None):
        self.neural_ms += milliseconds
        cue = int(image[50, 115, 0] > 30)
        if self.learning and stimulus != "none":
            self.memory.efficacy[cue] += 0.1 if stimulus == "reward" else -0.1
        result = self.telemetry([], milliseconds, stimulus)
        result["decoder"] = dict(
            action="SPIN" if self.memory.efficacy[cue] > 1 else "WAIT",
            difference_hz=float(self.memory.efficacy[cue]),
            requested_multiplier=1,
        )
        if callback:
            callback(result)
        return result

    def checkpoint(self, path):
        path.write_bytes(b"TEST ONLY")


def test_protocol_api_records_controls_and_keeps_slot_catalog_separate(tmp_path):
    e = Experiment(data=tmp_path / "data", runs=tmp_path / "runs", brain_factory=ProtocolTestBrain)
    headers = {"X-Flybet-Client": "local"}
    with TestClient(create_app(e)) as client:
        assert (
            client.post(
                "/api/protocol", headers=headers, json={"experiment": {}, "trials": 3}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/protocol", headers=headers, json={"experiment": {}, "seeds": 1, "trials": 2}
            ).status_code
            == 202
        )
        e.thread.join(10)
        assert e.state["status"] == "finished", e.state["error"]
        report = client.get("/api/protocols/" + e.state["run_id"]).json()
        assert len(report["rows"]) == 4
        assert report["analysis"]["conclusion"] == "learning-not-established"
        for row in report["rows"]:
            if row["arm"] in ("frozen", "erased"):
                assert row["before"] == row["after"] and row["changed_connections"] == 0
        assert not client.get("/api/runs").json()["runs"]
        assert len(client.get("/api/protocols").json()) == 1
        assert client.get("/api/templates").json()["calibrated"] is False
        assert (
            client.post("/api/memory", headers=headers, json={"operation": "erase"}).status_code
            == 409
        )


def test_memory_controls_are_paused_only_and_archive_records_interventions(tmp_path):
    e = Experiment(data=tmp_path / "data", runs=tmp_path / "runs", brain_factory=ProtocolTestBrain)
    headers = {"X-Flybet-Client": "local"}
    with TestClient(create_app(e)) as client:
        e.start(Config(), single=True)
        e.thread.join(10)
        assert e.state["status"] == "paused", e.state["error"]
        e.brain.memory.efficacy[:] = 1.5
        for op in ("freeze", "half", "enable", "erase", "reset-chemistry"):
            assert (
                client.post("/api/memory", headers=headers, json={"operation": op}).status_code
                == 202
            )
        np.testing.assert_array_equal(e.brain.memory.efficacy, 1)
        assert e.brain.learning
        archived = InsightArchive(e.runs).read(e.state["run_id"])
        assert len(archived["interventions"]) == 5 and archived["warnings"]
        e.update(status="finished")
        assert (
            client.post("/api/memory", headers=headers, json={"operation": "erase"}).status_code
            == 409
        )


@pytest.mark.skipif(os.environ.get("FLYBET_FULL_TEST") != "1", reason="Requires full MaleCNS")
def test_full_templates_memory_chemistry_and_vision():
    b = Brain(
        config=Config(
            physiology="less-excitable",
            vision="mirror",
            motor="mbon-assisted",
            chemistry="sensitization",
            memory="fast-forgetting",
        )
    )
    image = cue_frame(0)
    b.advance(image, 300)
    result = b.advance(image, 200, "reward", reinforcement=dict(amplitude=20, pulse="ramp"))
    assert b.native.n == 166700 and result["chemistry"]["exposure"] > 0
    assert np.isfinite(b.native.v).all() and np.isfinite(b.memory.efficacy).all()
    assert result["dose"]["reward_current_seconds"] > 2
    b.learning = False
    frozen = b.native.weight[b.arrays["plastic"]].copy()
    b.advance(image, 200, "reward")
    np.testing.assert_array_equal(frozen, b.native.weight[b.arrays["plastic"]])
    b.forget()
    np.testing.assert_array_equal(b.native.weight[b.arrays["plastic"]], b.memory.baseline)
    b.clear_transients()
    assert b.chemistry.exposure == 0 and not b.native.queue_count.any()


def test_physiology_templates_actually_change_spike_responses():
    counts = {}
    for name in PHYSIOLOGY:
        native = Native([0, 0], [], [], [0], [0], name)
        counts[name] = sum(int(native.advance([8], 100)[0]) for _ in range(10))
    assert counts["less-excitable"] < counts["default"] < counts["more-excitable"]


def test_chemistry_timeline_survives_merging_and_old_measurements_stay_missing():
    c = Config(bankroll_cents=100000)
    metrics = Insights(asdict(c))
    for i in range(170):
        metrics.add(
            dict(
                decision=i + 1,
                action="WAIT",
                stake_cents=0,
                payout_cents=0,
                net_cents=0,
                bankroll_cents=100000,
            ),
            feedback={
                "chemistry": dict(exposure=i / 10, reward_gain=1 + i / 100, withdrawal_current=0)
            },
        )
    result = metrics.snapshot()
    assert len(result["timeline"]) <= 80
    assert result["timeline"][-1]["chemistry_exposure"] == 16.9
    assert result["timeline"][-1]["reward_gain"] == 2.69
    old = Insights(asdict(c))
    old.add(
        dict(
            decision=1,
            action="WAIT",
            stake_cents=0,
            payout_cents=0,
            net_cents=0,
            bankroll_cents=100000,
        )
    )
    assert old.snapshot()["timeline"][0]["reward_gain"] is None


def test_cancelled_conditioning_excludes_unfinished_arms(tmp_path):
    e = Experiment(data=tmp_path / "data", runs=tmp_path / "runs")

    class StopBrain(ProtocolTestBrain):
        def advance(self, *args, **kwargs):
            result = super().advance(*args, **kwargs)
            e.pause()
            return result

    e.brain_factory = StopBrain
    try:
        e.start_protocol(Config(), ProtocolConfig(seeds=2, trials=2))
        e.thread.join(5)
        assert not e.thread.is_alive()
        assert e.state["status"] == "cancelled"
        assert e.state["protocol"]["analysis"]["completed_seeds"] == 0
        assert e.state["protocol"]["completed_arms"] == 0
    finally:
        e.close()
