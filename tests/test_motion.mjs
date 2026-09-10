import assert from "node:assert/strict";
import test from "node:test";
import { ActivityMotion } from "../flybet/web/motion.js";

const displayed = (motion, index, now) => {
  const { mix, pulse } = motion.weights(now);
  const rate = motion.rates[index] / 255;
  return {
    rate: motion.previous[2 * index] * (1 - mix) + rate * mix,
    halo: Math.sqrt(Math.max(0, rate - motion.previous[2 * index + 1])) * pulse,
  };
};

test("transitions interpolate measurements without changing their values", () => {
  const motion = new ActivityMotion(2);
  const measurement = new Uint8Array([255, 128]);
  motion.set(measurement, 1000, true);
  assert.equal(displayed(motion, 0, 1000).rate, 0);
  assert.equal(displayed(motion, 0, 1120).rate, 0.5);
  assert.equal(displayed(motion, 0, 1240).rate, 1);
  assert.deepEqual(motion.rates, measurement);
  assert.deepEqual(measurement, new Uint8Array([255, 128]));
  assert.deepEqual(motion.weights(1500), { mix: 1, pulse: 0, done: true });
});

test("halos require a measured increase, including during overlapping frames", () => {
  const motion = new ActivityMotion(3);
  motion.set(new Uint8Array([128, 128, 128]), 0, false);
  motion.set(new Uint8Array([255, 128, 0]), 1000, true);
  const before = displayed(motion, 0, 1120).rate;
  assert.ok(displayed(motion, 0, 1120).halo > 0);
  assert.equal(displayed(motion, 1, 1120).halo, 0);
  assert.equal(displayed(motion, 2, 1120).halo, 0);
  motion.set(new Uint8Array([255, 128, 0]), 1120, true);
  assert.ok(Math.abs(displayed(motion, 0, 1120).rate - before) < 1e-7);
  assert.equal(displayed(motion, 0, 1240).halo, 0);
});

test("pause, disconnect, or reduced motion settles on the exact latest frame", () => {
  const motion = new ActivityMotion(1);
  motion.set(new Uint8Array([255]), 1000, true);
  motion.finish();
  for (const now of [1001, 1120, 15000])
    assert.deepEqual(displayed(motion, 0, now), { rate: 1, halo: 0 });
  motion.set(new Uint8Array([0]), 2000, false);
  assert.deepEqual(displayed(motion, 0, 2001), { rate: 0, halo: 0 });
});

test("a new run removes both measured and interpolated activity", () => {
  const motion = new ActivityMotion(1);
  motion.set(new Uint8Array([255]), 1000, true);
  motion.clear();
  assert.deepEqual(displayed(motion, 0, 1100), { rate: 0, halo: 0 });
  motion.set(new Uint8Array([128]), 2000, true);
  assert.equal(displayed(motion, 0, 2000).rate, 0);
});
