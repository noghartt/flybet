from dataclasses import asdict, replace

import numpy as np
import pytest

from flybet.display import frame
from flybet.game import Config, SlotGame
from flybet.insights import Insights
from flybet.neural import decode, wager_decision


def test_accumulated_balance_weights_neural_tiers_without_changing_activity_or_action():
    config = Config(wager_mode="adaptive", wealth="moderate")
    # 6 Hz margin: starts at 2x, rises to 4x with strong wealth weighting,
    # and drops to 1x with a loss. This is a decoder test, not learning evidence.
    decoded = decode(np.array([0, 8, 1]), np.array([8, 9, 10]), 1000)
    original = decoded.copy()
    outcomes = [wager_decision(decoded, config, b) for b in (5000, 10000, 20000)]
    assert [d["bankroll_context"]["gain"] for d in outcomes] == [0.5, 1, 2]
    assert [d["requested_multiplier"] for d in outcomes] == [1, 2, 2]
    rich = wager_decision(decoded, replace(config, wealth="strong"), 20000)
    assert rich["requested_multiplier"] == 4
    for result in [*outcomes, rich]:
        for key in ("action", "left_hz", "right_hz", "difference_hz", "gate_spikes"):
            assert result[key] == decoded[key]
    assert decoded == original
    # Proportion, not nominal dollar denomination, determines the gain.
    scaled = wager_decision(decoded, replace(config, bankroll_cents=100000), 50000)
    assert scaled["requested_multiplier"] == outcomes[0]["requested_multiplier"]
    assert scaled["bankroll_context"]["gain"] == 0.5


def test_wealth_never_overrides_wait_and_gain_is_bounded():
    config = Config(wager_mode="adaptive", wealth="strong")
    for spikes in ([0, 25, 0], [1, 0, 1]):  # silent gate or wrong direction
        decoded = decode(np.array(spikes), np.array([8, 9, 10]), 1000)
        result = wager_decision(decoded, config, 10**12)
        assert result["action"] == "WAIT" and result["requested_multiplier"] == 0
        assert result["bankroll_context"]["gain"] == 3
        assert wager_decision(decoded, config, 0)["bankroll_context"]["gain"] == 0.25


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"wealth": "off"}, "off"),
        ({"wager_mode": "fixed"}, "fixed-wager"),
        ({"policy": "random-baseline"}, "random-baseline"),
    ],
)
def test_wealth_controls_bypass_tier_weighting(changes, reason):
    config = replace(Config(wager_mode="adaptive", wealth="strong"), **changes)
    decoded = decode(np.array([0, 8, 1]), np.array([8, 9, 10]), 1000)
    result = wager_decision(decoded, config, 20000)
    assert result["requested_multiplier"] == decoded["requested_multiplier"]
    assert result["bankroll_context"]["gain"] == 1
    assert result["bankroll_context"]["reason"] == reason
    assert not result["bankroll_context"]["applied"]


def test_money_accumulates_across_wins_losses_and_waits_and_visual_bar_can_grow():
    config = Config(bankroll_cents=10000, wager_mode="adaptive", wealth="moderate")
    game, metrics = SlotGame(config), Insights(asdict(config))
    game.draw = lambda: [0, 0, 0]
    win = game.spin(400)
    assert win["bankroll_cents"] == 16000  # $4 cost, $64 gross return
    game.draw = lambda: [0, 1, 2]
    loss = game.spin(200)
    assert loss["bankroll_cents"] == 15800
    for i, outcome in enumerate((win, loss)):
        metrics.add(dict(decision=i + 1, action="SPIN", **outcome))
    metrics.add(
        dict(
            decision=3,
            action="WAIT",
            stake_cents=0,
            payout_cents=0,
            net_cents=0,
            bankroll_cents=15800,
        )
    )
    assert metrics.snapshot()["net_cents"] == 5800
    summary = game.summary()
    assert (
        summary["starting_bankroll_cents"] - summary["wagered_cents"] + summary["returned_cents"]
    ) == summary["bankroll_cents"]
    # The original bar clipped every gain above the start. Inspect only bar pixels.
    bars = [frame([0, 1, 2], b, 10000)[141:150, 12:309] for b in (0, 5000, 10000, 20000)]
    colored = [int(np.all(b == (22, 144, 127), axis=2).sum()) for b in bars]
    assert colored[0] == 0 and all(a < b for a, b in zip(colored, colored[1:], strict=False))


def test_wealth_metrics_preserve_decision_context_and_legacy_missing_values():
    config = Config(wager_mode="adaptive", wealth="strong")
    metrics = Insights(asdict(config))
    # Repeated WAIT observations are real missing wagers, even with a wealth factor.
    decoded = decode(np.array([0, 8, 0]), np.array([8, 9, 10]), 1000)
    for i in range(170):
        observation = dict(decoder=wager_decision(decoded, config, 10000))
        metrics.add(
            dict(
                decision=i + 1,
                action="WAIT",
                stake_cents=0,
                payout_cents=0,
                net_cents=0,
                bankroll_cents=10000,
            ),
            observation,
        )
    result = metrics.snapshot()
    assert len(result["timeline"]) <= 80
    assert result["timeline"][-1]["wealth_gain"] == 1
    assert result["bankroll_influence"] == dict(
        decisions=170, spins=0, higher_proposals=0, lower_proposals=0
    )
    legacy = Insights(asdict(Config()))
    legacy.add(
        dict(
            decision=1,
            action="WAIT",
            stake_cents=0,
            payout_cents=0,
            net_cents=0,
            bankroll_cents=10000,
        )
    )
    assert legacy.snapshot()["timeline"][0]["wealth_gain"] is None
