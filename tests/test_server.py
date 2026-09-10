import json
import re
import threading

import numpy as np
from fastapi.testclient import TestClient

from flybet.experiment import Experiment
from flybet.game import Config
from flybet.server import create_app


class TestBrain:
    """Explicit unit-test double. Never available as a runtime backend."""

    __test__ = False

    def __init__(self, root, learning=True, config=None):
        self.manifest = {"dataset": "test-only"}
        self.arrays = {
            "ids": np.arange(12),
            "group": np.arange(12),
            "anatomy": np.eye(12, dtype=int),
        }
        self.group_sizes = np.ones(12, dtype=int)
        self.neural_ms = 0

    def advance(self, image, milliseconds, stimulus="none", callback=None, reinforcement=None):
        self.neural_ms += milliseconds
        result = {
            "neural_ms": self.neural_ms,
            "spikes": [0] * 12,
            "rates_hz": [0] * 12,
            "stimulus": stimulus,
            "memory": {"mean": 1.0, "changed": 0},
            "decoder": {"action": "WAIT"},
        }
        if callback:
            callback(result)
        return result

    def checkpoint(self, path):
        path.write_bytes(b"unit-test-only")

    def runtime_metadata(self):
        return {"backend": "unit-test-only"}


def test_packaged_assets_do_not_reuse_stale_nix_mtime_validators(tmp_path):
    experiment = Experiment(data=tmp_path / "data", runs=tmp_path / "runs")
    with TestClient(create_app(experiment)) as client:
        html = client.get("/").text
        versioned_path = re.search(r'src="(/assets/[a-f0-9]{16}/app.js)"', html).group(1)
        assert client.get(versioned_path).content == client.get("/app.js").content
        assert client.get(versioned_path.replace("app.js", "anatomy.js")).status_code == 200
        assert client.get(versioned_path.replace("app.js", "tokens.css")).status_code == 200
        current = client.get("/app.js")
        assert current.status_code == 200
        cached = client.get(
            "/app.js",
            headers={
                "If-None-Match": current.headers["etag"],
                "If-Modified-Since": "Wed, 01 Jan 2098 00:00:00 GMT",
            },
        )
        assert cached.status_code == 200
        assert cached.content == current.content
        assert cached.headers["cache-control"] == "no-store"


def test_api_controls_validation_export_and_fresh_scenarios(tmp_path):
    experiment = Experiment(data=tmp_path / "data", runs=tmp_path / "runs", brain_factory=TestBrain)
    headers = {"X-Flybet-Client": "local"}
    with TestClient(create_app(experiment)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/retina.png").headers["content-type"] == "image/png"
        assert client.get("/api/state").json()["telemetry"] is None
        assert client.post("/api/run", json={}).status_code == 403
        assert (
            client.post(
                "/api/run", json={}, headers={**headers, "Origin": "https://example.com"}
            ).status_code
            == 403
        )
        assert (
            client.post("/api/run", json={"scenario": "invalid"}, headers=headers).status_code
            == 422
        )
        assert client.post("/api/run", json={"seed": True}, headers=headers).status_code == 422
        assert client.post("/api/run", json={"single": True}, headers=headers).status_code == 202
        experiment.thread.join(5)
        state = client.get("/api/state").json()
        assert state["status"] == "paused", state.get("error")
        assert state["history"][0]["action"] == "WAIT"
        assert state["game"]["spins"] == 0 and state["game"]["bankroll_cents"] == 10000
        assert state["insights"]["decisions"] == 1
        assert state["insights"]["play_rate"] == 0
        old = state["run_id"]
        assert client.post("/api/step", headers=headers).status_code == 202
        experiment.thread.join(5)
        assert experiment.snapshot()["decision"] == 2
        measurements = client.get(f"/api/runs/{old}/insights?download=true")
        assert measurements.json()["metrics"]["decisions"] == 2
        assert "attachment" in measurements.headers["content-disposition"]
        exported = client.get("/api/export")
        records = [json.loads(line) for line in exported.text.splitlines()]
        assert sum(row["kind"] == "outcome" for row in records) == 2
        assert (
            client.post(
                "/api/run", json={"scenario": "house", "single": True}, headers=headers
            ).status_code
            == 202
        )
        experiment.thread.join(5)
        state = experiment.snapshot()
        assert state["run_id"] != old and state["decision"] == 1
        assert state["config"]["scenario"] == "house"
        assert state["insights"]["decisions"] == 1  # A fresh run resets the accumulator.
        assert (
            client.get(f"/api/runs/{old}/insights").json()["metrics"]
            == measurements.json()["metrics"]
        )
        assert len(client.get("/api/runs").json()["runs"]) == 1
        assert client.get("/api/runs/not-a-run/insights").status_code == 422
        assert client.get("/api/runs/20260910-000000-12345678/insights").status_code == 404


def test_single_owner_and_concurrent_run_rejection(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class SlowBrain(TestBrain):
        def advance(self, *args, **kwargs):
            entered.set()
            release.wait(5)
            return super().advance(*args, **kwargs)

    experiment = Experiment(data=tmp_path / "data", runs=tmp_path / "runs", brain_factory=SlowBrain)
    import pytest

    with pytest.raises(RuntimeError, match="Another Flybet"):
        Experiment(data=tmp_path / "data", runs=tmp_path / "runs")
    try:
        experiment.start(Config(), single=True)
        assert entered.wait(5)
        with pytest.raises(ValueError, match="in progress"):
            experiment.start(Config(scenario="house"))
    finally:
        release.set()
        experiment.close()


def test_accumulated_bankroll_survives_steps_and_drives_recorded_wager_proposals(
    tmp_path, monkeypatch
):
    from flybet.game import SlotGame
    from flybet.neural import decode

    class WagerBrain(TestBrain):
        def advance(self, *args, **kwargs):
            result = super().advance(*args, **kwargs)
            result["decoder"] = decode(np.array([0, 14, 1]), np.array([8, 9, 10]), 1000)
            return result

    draws = iter([[0, 0, 0], [0, 1, 2], [0, 1, 2]])
    monkeypatch.setattr(SlotGame, "draw", lambda self: next(draws))
    e = Experiment(data=tmp_path / "data", runs=tmp_path / "runs", brain_factory=WagerBrain)
    headers = {"X-Flybet-Client": "local"}
    with TestClient(create_app(e)) as client:
        config = dict(wealth="moderate", wager_mode="adaptive", single=True)
        assert client.post("/api/run", json=config, headers=headers).status_code == 202
        e.thread.join(5)
        first = e.snapshot()
        assert first["game"]["bankroll_cents"] == 13000  # $2 bet earns $30 net
        assert client.post("/api/step", headers=headers).status_code == 202
        e.thread.join(5)
        second = e.snapshot()
        assert second["run_id"] == first["run_id"]
        context = second["decoder"]["bankroll_context"]
        assert context["before_cents"] == 13000 and context["gain"] == 1.3
        assert context["unweighted_multiplier"] == 2 and context["proposed_multiplier"] == 4
        assert second["history"][-1]["stake_cents"] == 400
        assert second["game"]["bankroll_cents"] == 12600
        metrics = client.get(f"/api/runs/{first['run_id']}/insights").json()["metrics"]
        assert metrics == second["insights"]
        assert metrics["bankroll_influence"]["higher_proposals"] == 1
        assert metrics["bankroll_influence"]["spins"] == 2
        records = [json.loads(s) for s in client.get("/api/export").text.splitlines()]
        decision = [r for r in records if r["kind"] == "decision"][-1]
        assert decision["observation"]["decoder"]["bankroll_context"] == context
        # Reset is explicit, creates a new ID, and has the configured starting funds.
        assert client.post("/api/run", json=config, headers=headers).status_code == 202
        e.thread.join(5)
        fresh = e.snapshot()
        assert fresh["run_id"] != first["run_id"]
        assert fresh["history"][0]["bankroll_context"]["before_cents"] == 10000
        assert fresh["game"]["bankroll_cents"] == 9800


def test_missing_dataset_stops_without_synthetic_fallback(tmp_path):
    experiment = Experiment(data=tmp_path / "missing", runs=tmp_path / "runs")
    try:
        experiment.start(Config(), single=True)
        experiment.thread.join(5)
        state = experiment.snapshot()
        assert state["status"] == "error"
        assert state["telemetry"] is None and state["game"]["spins"] == 0
    finally:
        experiment.close()
