const symbols = ["●", "◆", "7", "★"];
const neighbors = (value) => [(value + 1) % 4, value, (value + 2) % 4];

// A finite reveal of an already resolved spin. No RNG, policy, or sensory input.
export class ReelView {
  constructor() {
    this.window = document.getElementById("reel-window");
    this.caption = document.getElementById("reel-motion");
    this.reels = Array.from(document.querySelectorAll("[data-reel]"));
    this.values = [0, 1, 2];
    this.animations = [];
    this.generation = 0;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)");
    this.reduced.addEventListener("change", () => this.finish());
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this.finish();
    });
    new ResizeObserver(() => this.finish()).observe(this.window);
  }

  paint(values) {
    this.reels.forEach((reel, i) => {
      neighbors(values[i]).forEach((value, j) => {
        const element = reel.children[j];
        element.textContent = symbols[value];
        element.className = `symbol symbol-${value}${j === 1 ? "" : " ghost"}`;
      });
    });
    this.window.setAttribute(
      "aria-label",
      `Three reels; recorded center payline: ${values.map((v) => symbols[v]).join(" ")}`,
    );
    this.values = [...values];
  }

  update(state) {
    const game = state.game;
    if (!game) return;
    // Spin count is the committed game event. Decision/phase may still hold an old outcome.
    const fresh = this.run === state.run_id && game.spins > this.spins;
    this.run = state.run_id;
    this.spins = game.spins;
    this.won = !!state.outcome?.won && state.phase !== "observe";
    if (fresh && !this.reduced.matches && !document.hidden)
      this.play(game.reels, game.spins);
    else if (
      this.window.dataset.motion !== "rolling" ||
      !this.target ||
      this.targetRun !== state.run_id
    ) {
      this.finish();
      this.paint(game.reels);
    }
    if (this.window.dataset.motion !== "rolling")
      this.window.classList.toggle("won", this.won);
  }

  play(values, spin) {
    this.finish();
    const generation = ++this.generation;
    this.target = [...values];
    this.targetRun = this.run;
    this.window.dataset.motion = "rolling";
    this.window.classList.remove("won");
    this.caption.textContent = `Revealing spin ${spin} · recorded outcome`;
    this.caption.hidden = false;
    this.animations = this.reels.map((reel, i) => {
      const track = document.createElement("div");
      track.className = "reel-track";
      track.setAttribute("aria-hidden", "true");
      const steps = 16 + i * 4;
      const strip = [
        ...neighbors(this.values[i]),
        ...Array.from({ length: steps - 3 }, (_, j) => (j + i) % 4),
        ...neighbors(values[i]),
      ];
      strip.forEach((value) => {
        const cell = document.createElement("span");
        cell.className = `symbol symbol-${value}`;
        cell.textContent = symbols[value];
        track.append(cell);
      });
      reel.append(track);
      reel.classList.add("rolling");
      return track.animate(
        [
          { transform: "translateY(0)", filter: "blur(0)" },
          {
            transform: `translateY(${((-steps * reel.clientHeight) / 3) * 0.8}px)`,
            filter: "blur(3px)",
            offset: 0.6,
          },
          {
            transform: `translateY(${(-steps * reel.clientHeight) / 3}px)`,
            filter: "blur(0)",
          },
        ],
        {
          duration: 1050 + i * 260,
          easing: "cubic-bezier(.15,.65,.25,1)",
          fill: "forwards",
        },
      );
    });
    // Each reel settles independently, landing on the exact committed payline.
    this.animations.forEach((animation, i) => {
      animation.finished
        .then(() => {
          if (generation !== this.generation) return;
          this.reels[i].classList.remove("rolling");
          this.paint(values);
          if (i === this.reels.length - 1) this.finish();
        })
        .catch(() => {}); // Cancellation on a fresh run, visibility change, or reduced motion.
    });
  }

  finish() {
    this.generation++;
    this.animations.forEach((animation) => animation.cancel());
    this.animations = [];
    this.reels.forEach((reel) => {
      reel.classList.remove("rolling");
      reel.querySelector(".reel-track")?.remove();
    });
    if (this.target) this.paint(this.target);
    this.target = null;
    this.window.dataset.motion = "settled";
    this.window.classList.toggle("won", !!this.won);
    this.caption.hidden = true;
  }
}
