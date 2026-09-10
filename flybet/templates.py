"""Versioned experimental presets. None is fitted to biological recordings."""

import copy

PHYSIOLOGY = {
    "default": dict(
        membrane_tau_ms=20,
        synapse_tau_ms=5,
        threshold_mv=-45,
        rest_mv=-52,
        kc_rest_mv=-60,
        kc_adaptation_mv=8,
        kc_adaptation_tau_ms=200,
        delivery_tau_ms=100,
        fast_gain=1.0,
    ),
    "less-excitable": dict(
        membrane_tau_ms=20,
        synapse_tau_ms=5,
        threshold_mv=-43,
        rest_mv=-52,
        kc_rest_mv=-60,
        kc_adaptation_mv=10,
        kc_adaptation_tau_ms=200,
        delivery_tau_ms=100,
        fast_gain=0.9,
    ),
    "more-excitable": dict(
        membrane_tau_ms=25,
        synapse_tau_ms=6,
        threshold_mv=-46,
        rest_mv=-52,
        kc_rest_mv=-60,
        kc_adaptation_mv=6,
        kc_adaptation_tau_ms=250,
        delivery_tau_ms=150,
        fast_gain=1.1,
    ),
}
VISION = {
    "default": dict(
        gain=30.0, half_saturation=0.02, tau_ms=10.0, mirror=False, grayscale=False, contrast=1.0
    ),
    "low-contrast": dict(
        gain=30.0, half_saturation=0.02, tau_ms=10.0, mirror=False, grayscale=False, contrast=0.25
    ),
    "grayscale": dict(
        gain=30.0, half_saturation=0.02, tau_ms=10.0, mirror=False, grayscale=True, contrast=1.0
    ),
    "mirror": dict(
        gain=30.0, half_saturation=0.02, tau_ms=10.0, mirror=True, grayscale=False, contrast=1.0
    ),
}
MOTOR = {
    "default": dict(
        direction_sign=1, mbon_gain=0.0, threshold_hz=2.0, medium_margin_hz=5.0, high_margin_hz=15.0
    ),
    "mirror": dict(
        direction_sign=-1,
        mbon_gain=0.0,
        threshold_hz=2.0,
        medium_margin_hz=5.0,
        high_margin_hz=15.0,
    ),
    "mbon-assisted": dict(
        direction_sign=1, mbon_gain=0.1, threshold_hz=2.0, medium_margin_hz=5.0, high_margin_hz=15.0
    ),
}
CHEMISTRY = {
    "baseline": dict(
        exposure_tau_s=60.0,
        dose_gain=0.0,
        max_exposure=20.0,
        sensitization=0.0,
        tolerance=0.0,
        withdrawal_current=0.0,
    ),
    "sensitization": dict(
        exposure_tau_s=60.0,
        dose_gain=1.0,
        max_exposure=20.0,
        sensitization=0.1,
        tolerance=0.0,
        withdrawal_current=0.0,
    ),
    "tolerance-withdrawal": dict(
        exposure_tau_s=60.0,
        dose_gain=1.0,
        max_exposure=20.0,
        sensitization=0.0,
        tolerance=0.15,
        withdrawal_current=0.25,
    ),
}
PULSES = {
    "sustained": dict(start_ms=0, duration_ms=200, shape="square"),
    "brief": dict(start_ms=0, duration_ms=50, shape="square"),
    "delayed": dict(start_ms=100, duration_ms=100, shape="square"),
    "ramp": dict(start_ms=0, duration_ms=200, shape="ramp"),
}
REWARD = {
    "binary": dict(scale="sign", max_current=40.0, expectation_alpha=0.1),
    "magnitude": dict(scale="base-stake-units", max_current=40.0, expectation_alpha=0.1),
    "prediction-error": dict(scale="return-minus-ema", max_current=40.0, expectation_alpha=0.1),
    "off": dict(scale="none", max_current=0.0, expectation_alpha=0.0),
}
MEMORY = {"default": dict(decay_seconds=1800.0), "fast-forgetting": dict(decay_seconds=10.0)}
WEALTH = {
    "off": dict(strength=0.0, minimum_gain=1.0, maximum_gain=1.0),
    "moderate": dict(strength=1.0, minimum_gain=0.25, maximum_gain=2.0),
    "strong": dict(strength=2.0, minimum_gain=0.25, maximum_gain=3.0),
}
CATALOG = dict(
    physiology=PHYSIOLOGY,
    vision=VISION,
    motor=MOTOR,
    chemistry=CHEMISTRY,
    pulse=PULSES,
    reward=REWARD,
    memory=MEMORY,
    wealth=WEALTH,
)
VERSION = "flybet-templates-v2"


def resolve(config):
    return {
        "version": VERSION,
        "calibrated": False,
        **{name: copy.deepcopy(values[getattr(config, name)]) for name, values in CATALOG.items()},
    }
