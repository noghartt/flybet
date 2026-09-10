"""Independent, disclosed probability distributions and integer fake-money accounting."""

import itertools
import random
from dataclasses import asdict, dataclass

from .templates import CATALOG

LOSSES = [x for x in itertools.product(range(4), repeat=3) if len(set(x)) != 1]
PAYOUT_MULTIPLIER = 16
SCENARIOS = {
    "random": {
        "name": "Totally random",
        "win_probability": 1 / 16,
        "rtp": 1.0,
        "description": "Three independent, uniform reels. Every combination is equally likely.",
    },
    "fly": {
        "name": "Fly favored",
        "win_probability": 0.10,
        "rtp": 1.6,
        "description": "Independent weighted outcomes: a 10% chance of three matching symbols.",
    },
    "house": {
        "name": "House favored",
        "win_probability": 0.025,
        "rtp": 0.4,
        "description": "Independent weighted outcomes: a 2.5% chance of three matching symbols.",
    },
}


@dataclass(frozen=True)
class Config:
    scenario: str = "random"
    seed: int = 42
    bankroll_cents: int = 10000
    stake_cents: int = 100
    max_decisions: int = 200
    learning: bool = True
    policy: str = "neural"
    wager_mode: str = "fixed"
    physiology: str = "default"
    vision: str = "default"
    motor: str = "default"
    chemistry: str = "baseline"
    pulse: str = "sustained"
    reward: str = "binary"
    memory: str = "default"
    wealth: str = "off"

    def __post_init__(self):
        if self.scenario not in SCENARIOS or self.policy not in ("neural", "random-baseline"):
            raise ValueError("Unknown scenario or policy")
        for key in ("seed", "bankroll_cents", "stake_cents", "max_decisions"):
            if type(getattr(self, key)) is not int:
                raise ValueError(f"{key} must be an integer")
        if not 0 <= self.seed <= 2**32 - 1 or not 1 <= self.max_decisions <= 100000:
            raise ValueError("Seed or decision limit out of range")
        if not 1 <= self.stake_cents <= self.bankroll_cents <= 10000000:
            raise ValueError("Invalid simulated bankroll or stake")
        if type(self.learning) is not bool:
            raise ValueError("learning must be boolean")
        if self.wager_mode not in ("fixed", "adaptive"):
            raise ValueError("Unknown wager mode")
        for name, values in CATALOG.items():
            if getattr(self, name) not in values:
                raise ValueError(f"Unknown {name} template")


def allowed_stakes(config, bankroll):
    multipliers = (1, 2, 4) if config.wager_mode == "adaptive" else (1,)
    return [config.stake_cents * m for m in multipliers if config.stake_cents * m <= bankroll]


class SlotGame:
    def __init__(self, config):
        self.config = config
        self.rng = random.Random(config.seed)
        self.bankroll = config.bankroll_cents
        self.spins = self.wins = self.wagered = self.returned = 0
        self.reels = [0, 1, 2]

    def draw(self):
        if self.config.scenario == "random":
            return [self.rng.randrange(4) for _ in range(3)]
        if self.rng.random() < SCENARIOS[self.config.scenario]["win_probability"]:
            return [self.rng.randrange(4)] * 3
        return list(self.rng.choice(LOSSES))

    def spin(self, stake=None):
        stake = self.config.stake_cents if stake is None else stake
        if self.bankroll < stake:
            raise ValueError("Insufficient simulated funds")
        if type(stake) is not int or stake not in allowed_stakes(self.config, self.bankroll):
            raise ValueError("Stake is not an allowed affordable tier")
        self.reels = self.draw()
        won = len(set(self.reels)) == 1
        payout = stake * PAYOUT_MULTIPLIER if won else 0
        net = payout - stake
        self.bankroll += net
        self.spins += 1
        self.wins += int(won)
        self.wagered += stake
        self.returned += payout
        return {
            "reels": self.reels.copy(),
            "won": won,
            "stake_cents": stake,
            "payout_cents": payout,
            "net_cents": net,
            "bankroll_cents": self.bankroll,
        }

    def summary(self):
        return {
            "config": asdict(self.config),
            "starting_bankroll_cents": self.config.bankroll_cents,
            "bankroll_cents": self.bankroll,
            "spins": self.spins,
            "wins": self.wins,
            "wagered_cents": self.wagered,
            "returned_cents": self.returned,
            "net_cents": self.bankroll - self.config.bankroll_cents,
            "observed_rtp": self.returned / self.wagered if self.wagered else None,
            "reels": self.reels.copy(),
        }
