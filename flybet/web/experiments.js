const $ = (id) => document.getElementById(id);
const names = [
  "wager_mode",
  "wealth",
  "physiology",
  "vision",
  "motor",
  "chemistry",
  "pulse",
  "reward",
  "memory",
];
const labels = {
  wager_mode: [
    "Wagers",
    { fixed: "Fixed base stake", adaptive: "Neural tiers · 1× / 2× / 4×" },
  ],
  wealth: [
    "Bankroll influence",
    {
      off: "Off · neural margin only",
      moderate: "Moderate · accumulated gains / losses",
      strong: "Strong · accumulated gains / losses",
    },
  ],
  physiology: [
    "Physiology",
    {
      default: "Default LIF",
      "less-excitable": "Less excitable",
      "more-excitable": "More excitable",
    },
  ],
  vision: [
    "Vision",
    {
      default: "Color + luminance",
      "low-contrast": "Reduced contrast",
      grayscale: "Luminance only",
      mirror: "Mirrored retinal sampling",
    },
  ],
  motor: [
    "Motor decoder",
    {
      default: "DN direction + gate",
      mirror: "Reversed DN direction",
      "mbon-assisted": "DN + mushroom-body output",
    },
  ],
  chemistry: [
    "Chemistry hypothesis",
    {
      baseline: "Baseline",
      sensitization: "Incremental sensitization",
      "tolerance-withdrawal": "Tolerance + withdrawal",
    },
  ],
  pulse: [
    "Pulse timing",
    {
      sustained: "200 ms sustained",
      brief: "50 ms brief",
      delayed: "100 ms delay + 100 ms pulse",
      ramp: "200 ms rising ramp",
    },
  ],
  reward: [
    "Reward encoding",
    {
      binary: "Win / loss sign",
      magnitude: "Amount relative to base stake",
      "prediction-error": "Outcome minus expected return",
      off: "No outcome pulse",
    },
  ],
  memory: [
    "Memory decay",
    {
      default: "Default · 1,800 neural seconds",
      "fast-forgetting": "Fast forgetting · 10 neural seconds",
    },
  ],
};
const fmt = (v) =>
  v == null
    ? "—"
    : Number(v).toLocaleString("en-US", { maximumFractionDigits: 3 });
const money = (cents) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );

export function bankrollReadout(s) {
  const game = s.game;
  if (!game)
    return {
      ledger: "No slot balance yet.",
      decision: "No wager decision yet.",
    };
  const ledger = `${money(game.config.bankroll_cents)} start − ${money(game.wagered_cents)} wagered + ${money(game.returned_cents)} returned = ${money(game.bankroll_cents)} available.`;
  const c = s.decoder?.bankroll_context;
  if (!c) return { ledger, decision: "Waiting for the first wager decision." };
  const reasons = {
    off: "Bankroll influence is off.",
    "fixed-wager": "Fixed wager: bankroll weighting is bypassed.",
    "random-baseline": "Random baseline: bankroll weighting is bypassed.",
  };
  const decision = !c.applied
    ? reasons[c.reason]
    : `Last decision used ${money(c.before_cents)} (${c.profit_cents >= 0 ? "+" : "−"}${money(Math.abs(c.profit_cents))} since start): ${fmt(c.gain)}× wager-margin weight. ${s.decoder.executed_action === "WAIT" ? "Neural WAIT; no wager." : `Neural ${c.unweighted_multiplier}× tier → weighted ${c.proposed_multiplier}× tier → ${money(s.decoder.executed_stake_cents)} affordable wager.`}`;
  return { ledger, decision };
}

export function learningConclusion(analysis) {
  if (!analysis) return "No completed learning test yet.";
  return analysis.conclusion === "candidate-memory-dependent-choice-effect"
    ? "Candidate memory-dependent choice effect. Independent replication is still needed."
    : "Learning not established by this test. Inspect neural responses and control differences below.";
}
export class ExperimentView {
  constructor(command, configuration) {
    this.command = command;
    this.configuration = configuration;
    for (const name of names) {
      const label = document.createElement("label");
      label.textContent = labels[name][0];
      const select = document.createElement("select");
      select.id = `template-${name}`;
      for (const [value, text] of Object.entries(labels[name][1]))
        select.add(new Option(text, value));
      if (name === "wager_mode") select.value = "adaptive";
      if (name === "wealth") select.value = "moderate";
      label.append(select);
      $("template-controls").append(label);
      select.addEventListener("change", () => this.preview());
    }
    document
      .querySelectorAll("[data-memory]")
      .forEach((button) =>
        button.addEventListener("click", () =>
          command("memory", { operation: button.dataset.memory }),
        ),
      );
    $("protocol-start").addEventListener("click", () => {
      try {
        for (const id of [
          "protocol-seeds",
          "protocol-trials",
          "protocol-retention",
        ]) {
          if (!$(id).reportValidity()) return;
        }
        const config = configuration();
        if (config.policy !== "neural")
          throw new Error(
            "Select the neural controller for conditioning probes.",
          );
        $("experiment-error").textContent = "";
        command("protocol", {
          experiment: config,
          seeds: Number($("protocol-seeds").value),
          trials: Number($("protocol-trials").value),
          retention_seconds: Number($("protocol-retention").value),
        });
      } catch (e) {
        $("experiment-error").textContent = e.message;
      }
    });
    $("protocol-stop").addEventListener("click", () => command("pause"));
    $("protocol-refresh").addEventListener("click", () => this.catalog());
    $("protocol-source").addEventListener("change", () => this.selectReport());
    fetch("/api/templates")
      .then((r) => {
        if (!r.ok) throw new Error("Cannot load templates");
        return r.json();
      })
      .then((result) => {
        this.templates = result;
        this.preview();
      })
      .catch((e) => ($("experiment-error").textContent = e.message));
    this.catalog();
  }
  config() {
    return Object.fromEntries(
      names.map((name) => [name, $(`template-${name}`).value]),
    );
  }
  preview() {
    if (!this.templates) return;
    const chosen = this.config();
    const settings = Object.fromEntries(
      Object.entries(this.templates.templates).map(([k, v]) => [
        k,
        v[chosen[k]],
      ]),
    );
    $("template-values").textContent = JSON.stringify(settings, null, 2);
    $("wealth-preview").textContent =
      chosen.wager_mode === "fixed"
        ? "Fixed wagers bypass bankroll weighting. Choose neural tiers to let accumulated gains or losses influence bet size."
        : chosen.wealth === "off"
          ? "Bankroll still accumulates and limits affordability. The decoder uses its unweighted neural margin."
          : `Bankroll weights the neural wager margin: ${fmt(settings.wealth.minimum_gain)}× to ${fmt(settings.wealth.maximum_gain)}×. Gains encourage larger tiers; losses reduce them. SPIN/WAIT still comes from neural activity. This is an explicit model assumption, not learned risk preference.`;
    const p = settings.pulse;
    const path = Array.from({ length: 20 }, (_, i) => {
      const ms = i * 10,
        t = ms - p.start_ms;
      const current =
        t < 0 || t >= p.duration_ms
          ? 0
          : p.shape === "ramp"
            ? (t + 5) / p.duration_ms
            : 1;
      return `${i === 0 ? "M" : "L"}${10 + i * 14},${65 - current * 45}`;
    }).join(" ");
    $("pulse-preview-path").setAttribute("d", path);
    $("pulse-caption").textContent =
      `${labels.pulse[1][chosen.pulse]}. Normalized shape; actual dose also depends on reward encoding and chemistry. Pulse shapes have different total doses.`;
  }
  update(s, busy) {
    this.state = s;
    const wallet = bankrollReadout(s);
    $("bankroll-ledger").textContent = wallet.ledger;
    $("bankroll-decision").textContent = wallet.decision;
    const effect = s.insights?.bankroll_influence;
    $("bankroll-effect").textContent = effect?.decisions
      ? `Bankroll weighting changed ${effect.higher_proposals} proposals upward and ${effect.lower_proposals} downward across ${effect.spins} neural SPIN decisions. This counts decoder adjustments before affordability, not learned behavior.`
      : "Profits and losses carry forward on every decision. Pause, step and resume preserve the balance.";
    document
      .querySelectorAll("#template-controls select, .protocol-settings input")
      .forEach((el) => (el.disabled = busy));
    $("protocol-start").disabled = busy || !s.dataset.available;
    $("protocol-stop").disabled = !s.busy || !s.protocol || s.pause_requested;
    const paused = s.status === "paused" && !busy && !s.protocol;
    document
      .querySelectorAll("[data-memory]")
      .forEach((el) => (el.disabled = !paused));
    $("memory-live").textContent =
      s.run_id && !s.protocol
        ? `${s.learning_enabled ? "Learning enabled" : "Memory frozen"} · ${s.interventions?.length ?? 0} interventions recorded`
        : "Pause a slot run to freeze, re-enable, or erase memory.";
    const chem = s.telemetry?.chemistry;
    $("chem-exposure").textContent = fmt(chem?.exposure);
    $("chem-gain").textContent = chem ? `${fmt(chem.reward_gain)}×` : "—";
    $("chem-current").textContent = chem
      ? `${fmt(chem.reward_current)} / ${fmt(chem.aversive_current)}`
      : "—";
    $("chem-withdrawal").textContent = fmt(chem?.withdrawal_current);
    $("active-presets").textContent = s.config
      ? `Active run: ${s.config.physiology} physiology · ${s.config.vision} vision · ${s.config.motor} motor · ${s.config.chemistry} chemistry · ${s.config.reward} reward · ${s.config.pulse} pulse · ${s.config.wager_mode} wagers · ${s.config.wealth || "off"} bankroll influence${s.protocol ? " (bankroll bypassed in conditioning)" : ""}. Selections apply only to a fresh run.`
      : "Selections apply to the next fresh run or conditioning test.";
    $("protocol-progress").textContent = s.protocol
      ? `${s.protocol.status} · ${s.protocol.completed_arms} / ${s.protocol.total_arms} arms complete${s.protocol.arm ? ` · seed ${s.protocol.seed} · ${s.protocol.arm} · ${s.protocol.phase}` : ""}`
      : "Four matched arms per seed: trained, frozen, erased, and unpaired.";
    if ($("protocol-source").value === "live")
      this.renderAnalysis(s.protocol?.analysis);
    const key = s.protocol && !s.busy ? `${s.run_id}:${s.status}` : null;
    if (key && key !== this.catalogKey) {
      this.catalogKey = key;
      this.catalog();
    }
    $("protocol-download").hidden = !s.protocol && !this.selected;
    $("protocol-download").href =
      `/api/protocols/${encodeURIComponent(this.selected || s.run_id || "")}`;
  }
  async catalog() {
    try {
      const response = await fetch("/api/protocols");
      if (!response.ok) throw new Error("Cannot load conditioning reports");
      const reports = await response.json(),
        current = $("protocol-source").value;
      $("protocol-source").replaceChildren(
        new Option("Current conditioning test", "live"),
      );
      for (const report of reports)
        $("protocol-source").add(
          new Option(`${report.run_id} · ${report.status}`, report.run_id),
        );
      if ([...$("protocol-source").options].some((o) => o.value === current))
        $("protocol-source").value = current;
    } catch (e) {
      $("experiment-error").textContent = e.message;
    }
  }
  async selectReport() {
    const source = $("protocol-source").value;
    this.selected = source === "live" ? null : source;
    if (!this.selected) {
      this.renderAnalysis(this.state?.protocol?.analysis);
      return;
    }
    try {
      const response = await fetch(
        `/api/protocols/${encodeURIComponent(source)}`,
      );
      if (!response.ok)
        throw new Error("Cannot load saved conditioning report");
      const report = await response.json();
      if ($("protocol-source").value === source)
        this.renderAnalysis(report.analysis);
    } catch (e) {
      $("experiment-error").textContent = e.message;
    }
  }
  renderAnalysis(analysis) {
    $("learning-conclusion").textContent = learningConclusion(analysis);
    const body = $("protocol-comparisons");
    body.replaceChildren();
    for (const [metric, label] of [
      ["choice_change", "Choice contrast"],
      ["signal_change", "Neural signal (Hz)"],
      ["tier_change", "Wager-tier contrast"],
    ]) {
      for (const [control, value] of Object.entries(
        analysis?.comparisons?.[metric] || {},
      )) {
        const row = body.insertRow();
        for (const text of [
          label,
          `trained − ${control}`,
          value.n,
          fmt(value.mean),
          value.bootstrap_95_interval
            ? value.bootstrap_95_interval.map(fmt).join(" to ")
            : "Needs ≥5 complete seeds",
        ])
          row.insertCell().textContent = text;
      }
    }
  }
}
