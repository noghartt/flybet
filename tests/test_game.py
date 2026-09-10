import math
from collections import Counter

import pytest

from flybet.game import LOSSES, PAYOUT_MULTIPLIER, SCENARIOS, Config, SlotGame


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_disclosed_probabilities_and_reproducibility(scenario):
    game = SlotGame(Config(scenario=scenario, seed=810))
    draws = [tuple(game.draw()) for _ in range(60000)]
    win_rate = sum(len(set(draw)) == 1 for draw in draws) / len(draws)
    expected = SCENARIOS[scenario]["win_probability"]
    sigma = math.sqrt(expected * (1 - expected) / len(draws))
    assert abs(win_rate - expected) < 5 * sigma
    assert expected * PAYOUT_MULTIPLIER == SCENARIOS[scenario]["rtp"]
    same = SlotGame(Config(scenario=scenario, seed=810))
    assert [tuple(same.draw()) for _ in range(50)] == draws[:50]
    if scenario == "random":
        counts = Counter(draws)
        assert len(counts) == 64
        assert all(
            abs(n - len(draws) / 64) < 5 * math.sqrt(len(draws) / 64) for n in counts.values()
        )


def test_loss_combinations_exclude_matches():
    assert len(LOSSES) == len(set(LOSSES)) == 60
    assert all(len(set(draw)) > 1 for draw in LOSSES)


def test_net_reward_and_bankroll_conservation(monkeypatch):
    game = SlotGame(Config(bankroll_cents=1000, stake_cents=125))
    monkeypatch.setattr(game, "draw", lambda: [2, 2, 2])
    win = game.spin()
    assert win["payout_cents"] == 2000
    assert win["net_cents"] == 1875
    monkeypatch.setattr(game, "draw", lambda: [1, 2, 3])
    loss = game.spin()
    assert loss["net_cents"] == -125
    assert game.bankroll == 1000 + game.returned - game.wagered
    assert game.wins == 1 and game.spins == 2


def test_no_credit_and_no_hidden_bankroll_bias():
    a = SlotGame(Config(seed=10, bankroll_cents=1, stake_cents=1))
    b = SlotGame(Config(seed=10, bankroll_cents=1000000, stake_cents=100, wealth="strong"))
    assert [a.draw() for _ in range(100)] == [b.draw() for _ in range(100)]
    a.bankroll = 0
    with pytest.raises(ValueError, match="Insufficient"):
        a.spin()


@pytest.mark.parametrize(
    "changes",
    [
        dict(seed=True),
        dict(seed=-1),
        dict(stake_cents=0),
        dict(stake_cents=10001),
        dict(scenario="rigged"),
        dict(max_decisions=0),
        dict(learning="yes"),
    ],
)
def test_invalid_config(changes):
    with pytest.raises(ValueError):
        Config(**changes)
