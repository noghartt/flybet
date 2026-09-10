import math
import os

import numpy as np
import pytest

from flybet.display import frame
from flybet.neural import Brain, Native, Plasticity, decode


def reference(ptr, post, weight, kc, mod, drive, steps):
    """Independent scalar implementation of the declared discrete-time equations."""
    n = len(kc)
    rest = [-60.0 if k else -52.0 for k in kc]
    v, g, adaptation, refractory = rest.copy(), [0.0] * n, [0.0] * n, [0] * n
    pam, ppl, counts, pending = [0.0] * n, [0.0] * n, [0] * n, {}
    em, es, ea, ed = [math.exp(-0.1 / tau) for tau in (20, 5, 200, 100)]
    for t in range(steps):
        for i in pending.pop(t, []):
            for e in range(ptr[i], ptr[i + 1]):
                j = post[e]
                if mod[i] == 1:
                    pam[j] += abs(weight[e]) / 0.275
                elif mod[i] == 2:
                    ppl[j] += abs(weight[e]) / 0.275
                elif mod[i] == 0 and refractory[j] == 0:
                    g[j] += weight[e]
        for i in range(n):
            pam[i] *= ed
            ppl[i] *= ed
            if refractory[i]:
                refractory[i] -= 1
                v[i] = rest[i]
            else:
                v[i] = (
                    rest[i]
                    + (v[i] - rest[i]) * em
                    + drive[i] * (1 - em)
                    + g[i] * (em - es) / 3
                    - adaptation[i] * (200 / 180) * (ea - em)
                )
            g[i] *= es
            adaptation[i] *= ea
            if refractory[i] == 0 and v[i] > -45:
                counts[i] += 1
                pending.setdefault(t + 18, []).append(i)
                v[i], g[i], refractory[i] = rest[i], 0, 22
                if kc[i]:
                    adaptation[i] += 8
    return counts, v, g, adaptation, pam, ppl


@pytest.mark.parametrize("mod", [[0, 0, 0], [1, 0, 2], [3, 0, 0]])
def test_native_matches_scalar_reference_and_chunk_boundaries(mod):
    ptr, post, weight, kc = [0, 2, 3, 4], [0, 1, 2, 0], [0.275, 9, -3, 2], [0, 1, 0]
    drive = np.array([26, 22, 13], np.float32)
    native = Native(ptr, post, weight, kc, mod)
    expected = reference(ptr, post, weight, kc, mod, drive, 1000)
    counts = native.advance(drive, 100)
    np.testing.assert_array_equal(counts, expected[0])
    for key, values in zip(["v", "g", "adaptation", "pam", "ppl"], expected[1:], strict=True):
        np.testing.assert_allclose(getattr(native, key), values, rtol=0.0003, atol=0.003)
    chunked = Native(ptr, post, weight, kc, mod)
    partial = sum((chunked.advance(drive, 10) for _ in range(10)), np.zeros(3, np.int32))
    np.testing.assert_array_equal(partial, counts)
    np.testing.assert_array_equal(chunked.v, native.v)


def test_native_silent_without_input_and_validates_graph():
    native = Native([0, 1], [0], [2], [0], [0])
    assert native.advance([0], 100).sum() == 0
    np.testing.assert_array_equal(native.v, [-52])
    with pytest.raises(ValueError):
        Native([0, 1], [1], [2], [0], [0])
    with pytest.raises(ValueError):
        native.advance([float("nan")])


def test_decoder_does_not_force_spins():
    group = np.array([8, 9, 10])
    assert decode(np.array([0, 10, 0]), group, 300)["action"] == "WAIT"
    assert decode(np.array([0, 10, 1]), group, 300)["action"] == "SPIN"
    assert decode(np.array([10, 0, 1]), group, 300)["action"] == "WAIT"


def protocol(order, learning=True):
    memory = Plasticity(np.ones(2, np.float32), np.ones((1, 2)))
    for cue in order:
        for _ in range(20):
            memory.step(
                np.array([20.0, 0.0]) if cue == "cue" else np.zeros(2),
                np.array([30.0]) if cue == "reward" else np.zeros(1),
                0.01,
                learning,
            )
    return memory.efficacy


def test_plasticity_temporal_specificity_and_frozen_control():
    assert protocol(["cue", "reward"])[0] < 1
    assert protocol(["reward", "cue"])[0] > 1
    assert protocol(["cue", "reward"])[1] == 1
    np.testing.assert_array_equal(protocol(["cue", "reward"], False), [1, 1])


@pytest.mark.skipif(
    os.environ.get("FLYBET_FULL_TEST") != "1", reason="Requires verified full MaleCNS data"
)
def test_full_malecns_sensory_dopamine_and_frozen_memory(tmp_path):
    b = Brain(learning=False)
    assert b.native.n == 166700
    assert len(b.native.post) == 25582938
    assert len(b.arrays["plastic"]) == 7835
    baseline = b.native.weight[b.arrays["plastic"]].copy()
    image = frame([0, 1, 2], 10000, 10000)
    neutral = b.advance(image, 200)
    reward = b.advance(image, 200, "reward")
    loss = b.advance(image, 200, "aversive")
    assert neutral["spikes"][0] > 0 and neutral["spikes"][3] > 0
    assert reward["spikes"][4] > 0 and reward["pam_delivery"][6] > 0
    assert loss["spikes"][5] > 0 and loss["ppl_delivery"][7] > 0
    np.testing.assert_array_equal(b.native.weight[b.arrays["plastic"]], baseline)
    b.learning = True
    for _ in range(2):
        result = b.advance(image, 200, "reward")
    assert result["memory"]["changed"] > 0
    assert np.isfinite(b.native.weight).all()
    b.checkpoint(tmp_path / "brain.npz")
    with np.load(tmp_path / "brain.npz", allow_pickle=False) as checkpoint:
        assert checkpoint["clock"][0] == 10000
        np.testing.assert_array_equal(checkpoint["weight"], b.native.weight)
