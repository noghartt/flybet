"""Full retained graph, explicit vision, spike-derived readout and candidate plasticity."""

import ctypes
import hashlib
import math
import os
import platform
import shlex
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from .activity import Activity
from .data import GROUP_NAMES, verify
from .paths import atomic_json, data_root, sha256
from .reinforcement import Chemistry, pulse_current
from .templates import MEMORY, MOTOR, PHYSIOLOGY, VISION, WEALTH

MODEL = {
    "version": "flybet-lif-v2",
    "dt_ms": 0.1,
    "membrane_tau_ms": 20,
    "synapse_tau_ms": 5,
    "threshold_mv": -45,
    "rest_mv": -52,
    "kc_rest_mv": -60,
    "delay_ms": 1.8,
    "refractory_ms": 2.2,
    "kc_adaptation_mv": 8,
    "kc_adaptation_tau_ms": 200,
    "contact_gain": 0.275,
    "lamina_current": 12,
    "decision_ms": 300,
    "feedback_ms": 200,
    "dopamine_current": 20,
    "trace_seconds": 1.0,
    "memory_decay_seconds": 1800,
    "learning_rate": 0.001,
    "efficacy_min": 0.1,
    "efficacy_max": 2.0,
    "delivery_tau_ms": 100,
    "decoder_threshold_hz": 2,
    "biology_validated": False,
}


def library():
    native = Path(__file__).with_name("native")
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    bundled = native / ("libflybet" + suffix)
    if bundled.exists():
        return bundled
    source = native / "kernel.cpp"
    target = data_root() / "cache" / ("libflybet-" + sha256(source)[:16] + suffix)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(suffix + ".partial")
        subprocess.run(
            [
                *shlex.split(os.environ.get("CXX", "c++")),
                "-O3",
                "-std=c++17",
                "-shared",
                "-fPIC",
                str(source),
                "-o",
                str(tmp),
            ],
            check=True,
        )
        tmp.replace(target)
    return target


class Native:
    """Own every native buffer; validate indices before exposing pointers."""

    def __init__(self, ptr, post, weight, kc, mod_kind, physiology="default"):
        self.n = len(kc)
        self.ptr = np.ascontiguousarray(ptr, dtype=np.int64)
        self.post = np.ascontiguousarray(post, dtype=np.int32)
        self.weight = np.array(weight, dtype=np.float32, copy=True)
        self.kc = np.ascontiguousarray(kc, dtype=np.uint8)
        self.mod_kind = np.ascontiguousarray(mod_kind, dtype=np.uint8)
        if (
            self.n < 1
            or self.ptr.shape != (self.n + 1,)
            or self.ptr[0] != 0
            or self.ptr[-1] != len(self.post)
            or np.any(np.diff(self.ptr) < 0)
        ):
            raise ValueError("Invalid CSR pointers")
        if (
            self.post.ndim != 1
            or self.weight.shape != self.post.shape
            or np.any(self.post < 0)
            or np.any(self.post >= self.n)
            or not np.isfinite(self.weight).all()
        ):
            raise ValueError("Invalid CSR edges")
        if (
            self.kc.shape != (self.n,)
            or self.mod_kind.shape != (self.n,)
            or np.any(self.kc > 1)
            or np.any(self.mod_kind > 3)
        ):
            raise ValueError("Invalid neuron flags")
        p = PHYSIOLOGY[physiology]
        self.parameters = np.array(
            [
                p[k]
                for k in (
                    "membrane_tau_ms",
                    "synapse_tau_ms",
                    "threshold_mv",
                    "kc_adaptation_mv",
                    "kc_adaptation_tau_ms",
                    "delivery_tau_ms",
                )
            ],
            np.float32,
        )
        self.weight[np.repeat(self.mod_kind == 0, np.diff(self.ptr))] *= p["fast_gain"]
        self.rest = np.where(self.kc, p["kc_rest_mv"], p["rest_mv"]).astype(np.float32)
        self.v = self.rest.copy()
        self.g = np.zeros(self.n, np.float32)
        self.adaptation = np.zeros(self.n, np.float32)
        self.refractory = np.zeros(self.n, np.int32)
        self.queue = np.zeros((19, self.n), np.int32)
        self.queue_count = np.zeros(19, np.int32)
        self.clock = np.zeros(1, np.int64)
        self.pam = np.zeros(self.n, np.float32)
        self.ppl = np.zeros(self.n, np.float32)
        self.library_path = library()
        self.lib = ctypes.CDLL(str(self.library_path))
        self.fn = self.lib.fb_advance
        self.fn.argtypes = [ctypes.c_int] + [ctypes.c_void_p] * 17 + [ctypes.c_int, ctypes.c_void_p]
        self.fn.restype = None

    def advance(self, drive, milliseconds=10):
        steps = round(milliseconds * 10)
        drive = np.ascontiguousarray(drive, dtype=np.float32)
        if (
            drive.shape != (self.n,)
            or not np.isfinite(drive).all()
            or not 1 <= steps <= 1000
            or abs(steps - milliseconds * 10) > 1e-6
        ):
            raise ValueError("Invalid neural input or time interval")
        counts = np.zeros(self.n, np.int32)
        arrays = [
            self.ptr,
            self.post,
            self.weight,
            self.rest,
            self.kc,
            self.mod_kind,
            self.v,
            self.g,
            self.adaptation,
            self.refractory,
            self.queue,
            self.queue_count,
            self.clock,
            self.pam,
            self.ppl,
            drive,
            self.parameters,
        ]
        self.fn(self.n, *[a.ctypes.data for a in arrays], steps, counts.ctypes.data)
        return counts


def decode(counts, group, milliseconds, motor="default"):
    seconds = milliseconds / 1000
    left = float(counts[group == 8].mean() / seconds)
    right = float(counts[group == 9].mean() / seconds)
    gate = int(counts[group == 10].sum())
    p = MOTOR[motor]
    mbon = [float(counts[group == g].mean() / seconds) if np.any(group == g) else 0 for g in (6, 7)]
    signal = p["direction_sign"] * (right - left) + p["mbon_gain"] * (mbon[1] - mbon[0])
    action = "SPIN" if gate and signal >= p["threshold_hz"] else "WAIT"
    margin = signal - p["threshold_hz"]
    tier = 4 if margin >= p["high_margin_hz"] else 2 if margin >= p["medium_margin_hz"] else 1
    return {
        "action": action,
        "left_hz": left,
        "right_hz": right,
        "raw_direction_hz": right - left,
        "difference_hz": signal,
        "gate_spikes": gate,
        "requested_multiplier": tier if action == "SPIN" else 0,
        "motor": motor,
        "mbon_difference_hz": mbon[1] - mbon[0],
    }


def wager_decision(decoded, config, bankroll):
    """Declared monetary context for tier decoding, separate from measured firing.

    Uses only the balance before the decision. Never changes SPIN/WAIT, measured
    rates, reward currents, or game odds. Passive conditioning does not call this.
    """
    p = WEALTH[config.wealth]
    reason = (
        "random-baseline"
        if config.policy != "neural"
        else "fixed-wager"
        if config.wager_mode != "adaptive"
        else "off"
        if config.wealth == "off"
        else "weighted"
    )
    fraction = (bankroll - config.bankroll_cents) / config.bankroll_cents
    gain = (
        min(p["maximum_gain"], max(p["minimum_gain"], 1 + p["strength"] * fraction))
        if reason == "weighted"
        else 1.0
    )
    motor = MOTOR[config.motor]
    margin = decoded.get("difference_hz", 0.0) - motor["threshold_hz"]
    weighted = margin * gain
    proposed = decoded.get("requested_multiplier", 0)
    if reason == "weighted" and decoded["action"] == "SPIN":
        proposed = (
            4
            if weighted >= motor["high_margin_hz"]
            else 2
            if weighted >= motor["medium_margin_hz"]
            else 1
        )
    return {
        **decoded,
        "requested_multiplier": proposed,
        "bankroll_context": {
            "profile": config.wealth,
            "applied": reason == "weighted",
            "reason": reason,
            "before_cents": bankroll,
            "starting_cents": config.bankroll_cents,
            "profit_cents": bankroll - config.bankroll_cents,
            "return_fraction": fraction,
            "gain": gain,
            "neural_margin_hz": margin,
            "weighted_margin": weighted,
            "unweighted_multiplier": decoded.get("requested_multiplier", 0),
            "proposed_multiplier": proposed,
        },
    }


class Plasticity:
    """Timing-sensitive rate/eligibility rule on existing KC→MBON07/11 edges."""

    def __init__(self, baseline, gains, memory="default"):
        self.baseline = baseline.copy()
        self.gains = gains
        self.kc_trace = np.zeros(len(baseline), np.float64)
        self.dan_trace = np.zeros(gains.shape[0], np.float64)
        self.efficacy = np.ones(len(baseline), np.float64)
        self.decay_seconds = MEMORY[memory]["decay_seconds"]

    def step(self, kc_hz, dan_hz, seconds, learning=True):
        if not 0 < seconds <= 0.010001:
            raise ValueError("Plasticity requires bins of at most 10 ms")
        decay = math.exp(-seconds / MODEL["trace_seconds"])
        if learning:
            # Earlier KC, later DAN depresses; reversed timing potentiates.
            drive = kc_hz * (self.dan_trace @ self.gains) - self.kc_trace * (dan_hz @ self.gains)
            self.efficacy[:] = 1 + (self.efficacy - 1) * math.exp(-seconds / self.decay_seconds)
            self.efficacy += MODEL["learning_rate"] * drive * seconds
            np.clip(self.efficacy, MODEL["efficacy_min"], MODEL["efficacy_max"], out=self.efficacy)
        self.kc_trace[:] = decay * self.kc_trace + (1 - decay) * kc_hz
        self.dan_trace[:] = decay * self.dan_trace + (1 - decay) * dan_hz
        return (self.baseline * self.efficacy).astype(np.float32)


class Brain:
    def __init__(self, root=None, learning=None, config=None):
        from .game import Config

        self.config = config or Config(learning=True if learning is None else learning)
        self.vision = VISION[self.config.vision]
        self.chemistry = Chemistry(self.config.chemistry)
        self.root = Path(root or data_root())
        self.manifest = verify(self.root)
        self.arrays = {
            key: np.load(self.root / "compiled" / f"{key}.npy", mmap_mode="r", allow_pickle=False)
            for key in self.manifest["arrays"]
        }
        a = self.arrays
        self.native = Native(
            a["ptr"], a["post"], a["weight"], a["kc"], a["mod_kind"], self.config.physiology
        )
        self.learning = self.config.learning if learning is None else learning
        self.light = np.zeros(len(a["retina"]), np.float32)
        self.dan = np.flatnonzero(np.isin(a["group"], [4, 5]))
        self.group_sizes = np.bincount(a["group"], minlength=12)
        if (
            tuple(self.group_sizes[[4, 5, 6, 7]]) != (15, 2, 4, 2)
            or not self.group_sizes[8:11].all()
        ):
            raise ValueError("Unexpected annotated neuron populations")
        gains = np.zeros((len(self.dan), len(a["plastic"])), np.float64)
        targets = a["post"][a["plastic"]]
        for target in np.unique(targets):
            compartment = 4 if a["group"][target] == 6 else 5
            contact = []
            for cell in self.dan:
                sl = slice(a["ptr"][cell], a["ptr"][cell + 1])
                count = np.abs(a["weight"][sl][a["post"][sl] == target]).sum()
                contact.append(float(count) if a["group"][cell] == compartment else 0)
            contact = np.array(contact)
            if contact.sum() <= 0:
                raise ValueError("Missing anatomical dopamine-to-MBON support")
            gains[:, targets == target] = (contact / contact.sum())[:, None]
        self.memory = Plasticity(self.native.weight[a["plastic"]], gains, self.config.memory)
        self.total_spikes = 0
        self.last_counts = np.zeros(self.native.n, np.int32)
        self.activity = Activity(self.native.n)

    def runtime_metadata(self):
        return {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "native_binary_sha256": sha256(self.native.library_path),
            "native_source_sha256": sha256(Path(__file__).with_name("native") / "kernel.cpp"),
        }

    @property
    def neural_ms(self):
        return float(self.native.clock[0] / 10)

    def sensory(self, frame):
        a = self.arrays
        h, w, channels = frame.shape
        if channels != 3 or frame.dtype != np.uint8:
            raise ValueError("Expected RGB uint8 frame")
        x = (a["uv"][:, 0] * (w - 1)).astype(int)
        if self.vision["mirror"]:
            x = w - 1 - x
        y = (a["uv"][:, 1] * (h - 1)).astype(int)
        rgb = frame[y, x].astype(np.float32) / 255
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        values = linear @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        color = a["channels"] != 0
        if not self.vision["grayscale"]:
            values[color] = linear[np.flatnonzero(color), a["channels"][color]]
        return 0.5 + self.vision["contrast"] * (values - 0.5)

    def advance(self, frame, milliseconds, stimulus="none", callback=None, reinforcement=None):
        if stimulus not in ("none", "reward", "aversive"):
            raise ValueError("Unknown stimulus")
        if milliseconds <= 0 or milliseconds % 10:
            raise ValueError("Observation must be a positive multiple of 10 ms")
        a, n = self.arrays, self.native
        light = self.sensory(frame)
        total = np.zeros(n.n, np.int32)
        start = time.perf_counter()
        reward_dose = aversive_dose = 0.0
        for elapsed in range(0, milliseconds, 10):
            self.light += (1 - math.exp(-10 / self.vision["tau_ms"])) * (light - self.light)
            drive = np.zeros(n.n, np.float32)
            drive[a["group"] == 2] = MODEL["lamina_current"]
            drive[a["retina"]] = (
                self.vision["gain"] * self.light / (self.vision["half_saturation"] + self.light)
            )
            amplitude = reinforcement["amplitude"] if reinforcement else MODEL["dopamine_current"]
            pulse = reinforcement["pulse"] if reinforcement else "sustained"
            current = pulse_current(pulse, amplitude, elapsed) if stimulus != "none" else 0.0
            chemistry = self.chemistry.step(stimulus, current)
            drive[a["group"] == 4] += chemistry["reward_current"]
            drive[a["group"] == 5] += chemistry["aversive_current"]
            reward_dose += chemistry["reward_current"] * 0.01
            aversive_dose += chemistry["aversive_current"] * 0.01
            counts = n.advance(drive)
            n.weight[a["plastic"]] = self.memory.step(
                counts[a["plastic_pre"]] * 100, counts[self.dan] * 100, 0.01, self.learning
            )
            total += counts
            self.total_spikes += int(counts.sum())
            self.last_counts = counts
            self.activity.step(counts, 10)
            if callback:
                callback(self.telemetry(counts, 10, stimulus))
        report = self.telemetry(total, milliseconds, stimulus)
        report["compute_seconds"] = time.perf_counter() - start
        report["decoder"] = decode(total, a["group"], milliseconds, self.config.motor)
        report["dose"] = dict(
            reward_current_seconds=reward_dose, aversive_current_seconds=aversive_dose
        )
        report["input_sha256"] = hashlib.sha256(frame.tobytes()).hexdigest()
        report["spike_sha256"] = hashlib.sha256(total.tobytes()).hexdigest()
        return report

    def telemetry(self, counts, milliseconds, stimulus):
        groups = self.arrays["group"]
        spikes = np.bincount(groups, weights=counts, minlength=12)
        sizes = np.maximum(self.group_sizes, 1)
        pam = np.bincount(groups, weights=self.native.pam, minlength=12) / sizes
        ppl = np.bincount(groups, weights=self.native.ppl, minlength=12) / sizes
        rates = spikes / sizes / (milliseconds / 1000)
        efficacy = self.memory.efficacy
        return {
            "neural_ms": self.neural_ms,
            "window_ms": milliseconds,
            "stimulus": stimulus,
            "chemistry": dict(self.chemistry.last),
            "learning_enabled": self.learning,
            "spikes": spikes.astype(int).tolist(),
            "rates_hz": rates.tolist(),
            "pam_delivery": pam.tolist(),
            "ppl_delivery": ppl.tolist(),
            "total_spikes": self.total_spikes,
            "memory": {
                "edges": len(efficacy),
                "changed": int(
                    np.count_nonzero(
                        self.native.weight[self.arrays["plastic"]] != self.memory.baseline
                    )
                ),
                "mean": float(efficacy.mean()),
                "min": float(efficacy.min()),
                "max": float(efficacy.max()),
            },
        }

    def forget(self, fraction=1.0):
        if not 0 <= fraction <= 1:
            raise ValueError("Forgetting fraction must be between zero and one")
        self.memory.efficacy[:] = 1 + (self.memory.efficacy - 1) * (1 - fraction)
        self.memory.kc_trace.fill(0)
        self.memory.dan_trace.fill(0)
        self.native.weight[self.arrays["plastic"]] = (
            self.memory.baseline * self.memory.efficacy
        ).astype(np.float32)

    def clear_transients(self, reset_chemistry=True):
        """Controlled probe initialization: preserve weights and neural clock only."""
        self.native.v[:] = self.native.rest
        for key in ("g", "adaptation", "refractory", "queue", "queue_count", "pam", "ppl"):
            getattr(self.native, key).fill(0)
        self.memory.kc_trace.fill(0)
        self.memory.dan_trace.fill(0)
        self.light.fill(0)
        self.activity.rates.fill(0)
        if reset_chemistry:
            self.chemistry.reset()

    def checkpoint(self, path):
        path = Path(path)
        tmp = path.with_suffix(".partial")
        with tmp.open("wb") as f:
            np.savez_compressed(
                f,
                **{
                    k: getattr(self.native, k)
                    for k in [
                        "v",
                        "g",
                        "adaptation",
                        "refractory",
                        "queue",
                        "queue_count",
                        "clock",
                        "pam",
                        "ppl",
                        "weight",
                    ]
                },
                light=self.light,
                efficacy=self.memory.efficacy,
                kc_trace=self.memory.kc_trace,
                dan_trace=self.memory.dan_trace,
                activity_rates=self.activity.rates,
                chemistry_exposure=np.array([self.chemistry.exposure]),
            )
        tmp.replace(path)
        atomic_json(
            path.with_suffix(".json"),
            {
                "sha256": sha256(path),
                "model": MODEL,
                "neural_ms": self.neural_ms,
                "groups": GROUP_NAMES,
                "dataset_arrays": self.manifest["arrays"],
                "purpose": "End-of-run evidence; automatic resume is not implemented.",
            },
        )
