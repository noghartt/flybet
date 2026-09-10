"""Read-only spike visualization; never feeds back into the controller."""

import math
import struct

import numpy as np

TAU_MS = 100
DISPLAY_MAX_HZ = 200


class Activity:
    def __init__(self, neurons):
        self.rates = np.zeros(neurons, np.float32)

    def step(self, counts, milliseconds):
        decay = math.exp(-milliseconds / TAU_MS)
        self.rates *= decay
        self.rates += (1 - decay) * (1000 / milliseconds) * counts

    def packet(self, neural_ms):
        encoded = np.rint(np.clip(self.rates, 0, DISPLAY_MAX_HZ) * (255 / DISPLAY_MAX_HZ))
        return (
            struct.pack("<4sId", b"FBA1", len(self.rates), neural_ms)
            + encoded.astype("u1").tobytes()
        )
