"""Explicit reward encoding and bounded chemistry hypotheses; no action selection."""

import math

from .templates import CHEMISTRY, PULSES, REWARD


class RewardEncoder:
    def __init__(self, template="binary", pulse="sustained"):
        self.template, self.pulse = template, pulse
        self.expected = 0.0

    def encode(self, net_cents, base_stake, played=True, update=True):
        if not played:
            return dict(
                stimulus="none",
                amplitude=0.0,
                pulse=self.pulse,
                expected_before=self.expected,
                prediction_error=None,
            )
        result = net_cents / base_stake
        before = self.expected
        error = result - before
        value = {
            "binary": float((result > 0) - (result < 0)),
            "magnitude": result,
            "prediction-error": error,
            "off": 0.0,
        }[self.template]
        if update:
            self.expected += REWARD[self.template]["expectation_alpha"] * error
        amplitude = min(REWARD[self.template]["max_current"], 20 * abs(value))
        return dict(
            stimulus="reward" if value > 0 else "aversive" if value < 0 else "none",
            amplitude=amplitude,
            pulse=self.pulse,
            expected_before=before,
            prediction_error=error,
        )


def pulse_current(pulse, amplitude, elapsed_ms):
    p = PULSES[pulse]
    t = elapsed_ms - p["start_ms"]
    if t < 0 or t >= p["duration_ms"]:
        return 0.0
    return amplitude * ((t + 5) / p["duration_ms"] if p["shape"] == "ramp" else 1.0)


class Chemistry:
    def __init__(self, template="baseline"):
        self.template = template
        self.parameters = CHEMISTRY[template]
        self.exposure = 0.0
        self.last = dict(
            exposure=0.0,
            reward_gain=1.0,
            reward_current=0.0,
            aversive_current=0.0,
            withdrawal_current=0.0,
        )

    def step(self, stimulus, current, seconds=0.01):
        p = self.parameters
        self.exposure *= math.exp(-seconds / p["exposure_tau_s"])
        gain = (1 + p["sensitization"] * self.exposure) / (1 + p["tolerance"] * self.exposure)
        reward = min(80.0, current * gain) if stimulus == "reward" else 0.0
        aversive = current if stimulus == "aversive" else 0.0
        withdrawal = min(5.0, p["withdrawal_current"] * self.exposure) if not reward else 0.0
        # One 20-unit, 200 ms reward contributes one dose before decay.
        self.exposure = min(
            p["max_exposure"], self.exposure + p["dose_gain"] * reward * seconds / 4
        )
        self.last = dict(
            exposure=self.exposure,
            reward_gain=gain,
            reward_current=reward,
            aversive_current=aversive + withdrawal,
            withdrawal_current=withdrawal,
        )
        return self.last

    def reset(self):
        self.__init__(self.template)
