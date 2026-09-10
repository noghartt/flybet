// Presentation only. Targets are measured, quantized rates; time here is wall time.
export class ActivityMotion {
  constructor(count, duration = 240) {
    this.rates = new Uint8Array(count);
    // Interpolated starting value and previous measurement, normalized to 0–1.
    this.previous = new Float32Array(count * 2);
    this.duration = duration;
    this.started = null;
  }

  weights(now) {
    if (this.started === null) return { mix: 1, pulse: 0, done: true };
    const t = Math.max(0, Math.min(1, (now - this.started) / this.duration));
    return { mix: t * t * (3 - 2 * t), pulse: 4 * t * (1 - t), done: t === 1 };
  }

  set(next, now, animate) {
    const { mix } = this.weights(now);
    for (let i = 0; i < this.rates.length; i++) {
      const before = this.rates[i] / 255;
      this.previous[2 * i] += (before - this.previous[2 * i]) * mix;
      this.previous[2 * i + 1] = before;
    }
    this.rates.set(next);
    this.started = animate ? now : null;
  }

  finish() {
    this.started = null;
  }

  clear() {
    this.finish();
    this.rates.fill(0);
    this.previous.fill(0);
  }
}
