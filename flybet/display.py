"""The exact RGB observation shown to the modeled photoreceptors."""

import math

import numpy as np
from PIL import Image, ImageDraw

COLORS = [(226, 121, 33), (22, 144, 127), (54, 101, 191), (188, 57, 85)]


def frame(reels, bankroll, initial, phase="observe"):
    image = Image.new("RGB", (320, 180), (238, 241, 245))
    d = ImageDraw.Draw(image)
    d.rectangle((0, 0, 319, 28), fill=(21, 29, 41))
    d.text((12, 9), "FLYBET / SIMULATED", fill=(245, 245, 245))
    for i, symbol in enumerate(reels):
        x = 58 + 102 * i
        d.rounded_rectangle(
            (x - 43, 40, x + 43, 126),
            radius=9,
            fill=(255, 255, 255),
            outline=(160, 172, 185),
            width=2,
        )
        color = COLORS[symbol]
        if symbol == 0:
            d.ellipse((x - 23, 61, x + 23, 107), fill=color)
        elif symbol == 1:
            d.polygon([(x, 57), (x + 26, 84), (x, 111), (x - 26, 84)], fill=color)
        elif symbol == 2:
            d.line([(x - 20, 62), (x + 20, 62), (x - 5, 107)], fill=color, width=9)
        else:
            points = [
                (
                    x + (27 if j % 2 == 0 else 12) * math.sin(j * math.pi / 5),
                    84 - (27 if j % 2 == 0 else 12) * math.cos(j * math.pi / 5),
                )
                for j in range(10)
            ]
            d.polygon(points, fill=color)
    d.rectangle((12, 141, 308, 149), fill=(193, 201, 211))
    # Starting balance sits at the midpoint; gains remain visually distinguishable.
    level = bankroll / (bankroll + initial)
    if bankroll:
        d.rectangle((12, 141, 12 + int(296 * level), 149), fill=(22, 144, 127))
    d.line((160, 138, 160, 152), fill=(21, 29, 41), width=1)
    d.text((12, 160), f"CREDITS {bankroll / 100:.2f} / {phase.upper()}", fill=(21, 29, 41))
    return np.asarray(image, dtype=np.uint8)


def cue_frame(cue):
    """Equal-area, equal-color orthogonal bars; no outcome or cue label metadata."""
    if cue not in (0, 1):
        raise ValueError("Unknown conditioning cue")
    image = Image.new("RGB", (320, 180), (30, 30, 30))
    d = ImageDraw.Draw(image)
    for offset in range(0, 120, 20):
        if cue == 0:
            d.rectangle((100 + offset, 30, 109 + offset, 149), fill=(160, 160, 160))
        else:
            d.rectangle((100, 30 + offset, 219, 39 + offset), fill=(160, 160, 160))
    return np.asarray(image, dtype=np.uint8)
