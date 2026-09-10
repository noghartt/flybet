import hashlib
import math
import os
import struct
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from flybet.activity import Activity
from flybet.anatomy import POINT_DTYPE, Anatomy, load_anatomy, pack_points
from flybet.experiment import Experiment
from flybet.paths import data_root
from flybet.server import create_app


def annotated_nodes():
    return pd.DataFrame(
        {
            "bodyId": np.array([2**53 + 1, 42, 101, 900], dtype=np.int64),
            "somaLocation": [[100, 200, 300], None, [40000, 20000, 30000], [45000, 50000, 90000]],
            "superclass": ["cb_intrinsic", "ol_sensory", "cb_intrinsic", "vnc_intrinsic"],
            "class": ["Kenyon_Cell", "visual", "DAN", None],
            "somaNeuromere": [None, None, None, "T1"],
            "type": ["KC", "R8p", "PAM11", None],
            "somaSide": ["L", None, "R", "L"],
        }
    )


def test_anatomy_uses_exact_simulator_indices_and_only_real_somas():
    nodes = annotated_nodes()
    anatomy = Anatomy(nodes, [3, 1, 4, 11], "index-hash", "source-hash")
    points = np.frombuffer(anatomy.binary, dtype=POINT_DTYPE)
    assert POINT_DTYPE.itemsize == 20
    np.testing.assert_array_equal(points["index"], [0, 2, 3])
    np.testing.assert_array_equal(points["population"], [2, 7, 6])
    np.testing.assert_array_equal(points["group"], [3, 4, 11])
    np.testing.assert_allclose(points["xyz"][0], [0.8, 1.6, 2.4])
    assert points["part"].tolist() == [0, 0, 1]
    assert anatomy.neuron(0)["body_id"] == str(2**53 + 1)
    assert anatomy.neuron(1)["soma_um"] is None
    assert anatomy.metadata["unlocated_neurons"] == 1
    assert anatomy.metadata["points_sha256"] == hashlib.sha256(anatomy.binary).hexdigest()
    with pytest.raises(IndexError):
        anatomy.neuron(-1)
    nodes.at[0, "somaLocation"] = [1, float("nan"), 3]
    with pytest.raises(ValueError, match="coordinate"):
        pack_points(nodes, [3, 1, 4, 11])


def test_activity_tracks_individual_spikes_and_neural_time_only():
    activity = Activity(3)
    counts = np.array([1, 0, 0], np.int32)
    activity.step(counts, 10)
    expected = (1 - math.exp(-0.1)) * 100
    np.testing.assert_allclose(activity.rates, [expected, 0, 0], rtol=1e-6)
    activity.step(np.zeros(3), 10)
    assert activity.rates[0] == pytest.approx(expected * math.exp(-0.1))
    before = activity.rates.copy()
    packet = activity.packet(20)
    assert activity.packet(20) == packet  # Rendering/pausing does not advance activity.
    np.testing.assert_array_equal(activity.rates, before)
    assert struct.unpack("<4sId", packet[:16]) == (b"FBA1", 3, 20)
    assert packet[17:] == b"\x00\x00"
    activity.rates[:] = [0, 100, 350]
    assert list(activity.packet(20)[16:]) == [0, 128, 255]
    assert activity.rates[2] == 350  # Display clipping never changes the measured rate.


def test_activity_api_identity_pause_and_fresh_run_clear(tmp_path):
    experiment = Experiment(data=tmp_path / "data", runs=tmp_path / "runs")
    with TestClient(create_app(experiment)) as client:
        assert client.get("/api/activity").status_code == 204
        assert client.get("/api/anatomy").status_code == 503
        activity = Activity(2)
        activity.step(np.array([0, 1]), 10)
        experiment.brain = SimpleNamespace(activity=activity, manifest={"arrays": {"ids": "hash"}})
        experiment.state["run_id"] = "first"
        experiment.run_dir = tmp_path / "record"
        experiment.run_dir.mkdir()
        data = {"neural_ms": 10, "rates_hz": [0] * 12, "memory": {"mean": 1}, "stimulus": "none"}
        experiment.telemetry(data)
        frame = client.get("/api/activity")
        assert frame.headers["x-flybet-run"] == "first"
        assert frame.headers["x-flybet-ids"] == "hash"
        assert frame.content == activity.packet(10)
        assert client.post("/api/pause", headers={"X-Flybet-Client": "local"}).status_code == 202
        assert client.get("/api/activity").content == frame.content
        # Isolate lifecycle from native loading: start must clear the previous run's frame.
        experiment._launch = lambda single: None
        assert (
            client.post("/api/run", json={}, headers={"X-Flybet-Client": "local"}).status_code
            == 202
        )
        assert client.get("/api/activity").status_code == 204


@pytest.mark.skipif(os.environ.get("FLYBET_FULL_TEST") != "1", reason="Requires MaleCNS data")
def test_full_anatomy_maps_real_cells_and_api_binary(tmp_path):
    anatomy = load_anatomy(str(data_root()))
    assert anatomy.metadata["located_neurons"] == 139662
    assert anatomy.metadata["unlocated_neurons"] == 27038
    assert anatomy.metadata["total_neurons"] == 166700
    ids = np.load(data_root() / "compiled/ids.npy", allow_pickle=False)
    index = int(np.flatnonzero(ids == 11327)[0])
    cell = anatomy.neuron(index)
    assert cell["type"] == "PPL101"
    np.testing.assert_allclose(cell["soma_um"], np.array([33705, 14310, 33911]) * 0.008)
    point = anatomy.points[anatomy.points["index"] == index][0]
    assert point["group"] == 5
    np.testing.assert_allclose(point["xyz"], cell["soma_um"])
    experiment = Experiment(runs=tmp_path / "runs")
    with TestClient(create_app(experiment)) as client:
        assert client.get("/api/anatomy").json() == anatomy.metadata
        assert client.get("/api/anatomy/points").content == anatomy.binary
        assert client.get(f"/api/anatomy/neuron/{index}").json() == cell
        assert client.get("/api/anatomy/neuron/166700").status_code == 404
