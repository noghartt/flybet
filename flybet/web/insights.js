const $ = (id) => document.getElementById(id);
const n = (v, digits = 1) =>
  v == null
    ? "—"
    : Number(v).toLocaleString("en-US", { maximumFractionDigits: digits });
const percent = (v) =>
  v == null ? "—" : `${n(v * 100, v > 0 && v < 0.001 ? 5 : 1)}%`;
const money = (v) =>
  v == null
    ? "—"
    : `$${(v / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = (v, format) =>
  v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${format(Math.abs(v))}`;
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const svg = (tag, attrs = {}, text) => {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs))
    element.setAttribute(key, value);
  if (text != null) element.textContent = text;
  return element;
};

export function controller(config) {
  if (!config) return "No run selected";
  return config.policy === "random-baseline"
    ? `Random baseline · learning ${config.learning ? "on" : "off"}`
    : config.learning
      ? "Neural · learning enabled"
      : "Neural · frozen memory";
}

export function comparisonIssue(a, b, comparePresets = false) {
  if (!a?.metrics || !b?.metrics) return "Select two recorded runs to compare.";
  if (a.run_id === b.run_id) return "Choose a different reference run.";
  if (
    (!a.model_identity || a.model_identity !== b.model_identity) &&
    !(
      comparePresets &&
      a.source_identity &&
      a.source_identity === b.source_identity
    )
  )
    return "These runs do not have matching verified model and dataset identities.";
  for (const [key, label] of [
    ["scenario", "odds"],
    ["stake_cents", "stake"],
    ["bankroll_cents", "starting bankroll"],
    ["max_decisions", "decision limit"],
  ])
    if (a.config[key] !== b.config[key])
      return `Choose a reference with the same ${label}.`;
  if (a.interventions?.length || 0 || b.interventions?.length || 0)
    return "This comparison includes memory or chemistry interventions. Use a controlled learning test.";
  if ((a.config.wager_mode || "fixed") !== (b.config.wager_mode || "fixed"))
    return "Choose a reference with the same wager mode.";
  return "";
}

export function outcomeMessage(metrics) {
  if (!metrics?.decisions)
    return "Complete a decision to start measuring behavior.";
  const { win, loss } = metrics.conditions;
  if (!win.events)
    return "No wins recorded yet. Play after a win cannot be measured.";
  if (!win.next_n) return "No win has a following completed decision yet.";
  if (!loss.next_n)
    return "A loss also needs a following decision before the two can be compared.";
  const d = metrics.next_spin_difference;
  return `Observed play-again difference: ${signed(d * 100, (v) => `${n(v)} percentage points`)} after wins versus losses. This is an association in this run.`;
}

export class InsightView {
  constructor() {
    this.source = "live";
    this.saved = this.reference = this.state = null;
    this.catalog = [];
    this.sourceRequest = this.referenceRequest = 0;
    $("insight-source").addEventListener("change", () => this.selectSource());
    $("insight-reference").addEventListener("change", () =>
      this.selectReference(),
    );
    $("insight-refresh").addEventListener("click", () => this.refresh());
    $("insight-chart-kind").addEventListener("change", () => this.render());
    $("insight-compare-presets").addEventListener("change", () =>
      this.render(),
    );
    this.refresh();
  }

  live() {
    const s = this.state;
    return s
      ? {
          run_id: s.run_id,
          config: s.config,
          status: s.status,
          metrics: s.insights,
          model_identity: s.model_identity,
          source_identity: s.source_identity,
          runtime: s.runtime,
          interventions: s.interventions,
          warnings: s.interventions?.length
            ? ["This run contains recorded memory or chemistry interventions."]
            : [],
        }
      : null;
  }

  update(state) {
    const key = `${state.run_id}:${state.insights?.decisions}:${state.status}`;
    const previous = this.state;
    this.state = state;
    if (previous?.run_id !== state.run_id || (previous?.busy && !state.busy))
      this.refresh();
    if (key !== this.lastKey) {
      this.lastKey = key;
      this.render();
    }
  }

  async request(id) {
    const response = await fetch(
      `/api/runs/${encodeURIComponent(id)}/insights`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(
        result.detail || "Could not read this run's measurements.",
      );
    }
    return response.json();
  }

  async refresh() {
    if (this.refreshing) return;
    this.refreshing = true;
    $("insight-refresh").disabled = true;
    try {
      const response = await fetch("/api/runs", { cache: "no-store" });
      if (!response.ok) throw new Error("Could not load saved runs.");
      const catalog = await response.json();
      this.catalog = catalog.runs;
      for (const id of ["insight-source", "insight-reference"]) {
        const select = $(id),
          value = select.value;
        const option = node(
          "option",
          id === "insight-source" ? "Current live run" : "No reference run",
        );
        option.value = id === "insight-source" ? "live" : "";
        select.replaceChildren(option);
        for (const run of this.catalog) {
          if (run.run_id === this.state?.run_id) continue;
          const item = node(
            "option",
            `${run.run_id.slice(0, 15)} · ${run.config.scenario} · ${controller(run.config)} · seed ${run.config.seed}`,
          );
          item.value = run.run_id;
          select.append(item);
        }
        if ([...select.options].some((o) => o.value === value))
          select.value = value;
      }
      $("insight-catalog-note").textContent =
        catalog.unavailable || catalog.omitted
          ? `${catalog.unavailable} unreadable records · ${catalog.omitted} older runs omitted from this list`
          : "";
      $("insight-error").hidden = true;
      // Refresh selected archives too: a formerly live/paused record may have grown.
      if (this.source !== "live") await this.selectSource();
      if ($("insight-reference").value) await this.selectReference();
    } catch (error) {
      this.error(error.message);
    } finally {
      this.refreshing = false;
      $("insight-refresh").disabled = false;
      this.render();
    }
  }

  error(message) {
    $("insight-error").textContent = message;
    $("insight-error").hidden = false;
  }

  async selectSource() {
    const request = ++this.sourceRequest;
    this.source = $("insight-source").value;
    this.saved = null;
    this.render();
    if (this.source === "live") return;
    try {
      const result = await this.request(this.source);
      if (request !== this.sourceRequest) return;
      this.saved = result;
      $("insight-error").hidden = true;
    } catch (error) {
      if (request === this.sourceRequest) this.error(error.message);
    }
    this.render();
  }

  async selectReference() {
    const request = ++this.referenceRequest;
    const id = $("insight-reference").value;
    this.reference = null;
    this.render();
    if (!id) return;
    try {
      const result = await this.request(id);
      if (request !== this.referenceRequest) return;
      this.reference = result;
      $("insight-error").hidden = true;
    } catch (error) {
      if (request === this.referenceRequest) this.error(error.message);
    }
    this.render();
  }

  render() {
    const run = this.source === "live" ? this.live() : this.saved;
    const m = run?.metrics;
    $("insight-scope").textContent = run?.config
      ? `${this.source === "live" ? "Current run" : "Saved analysis"} · ${controller(run.config)} · ${run.config.scenario} odds · seed ${run.config.seed} · ${run.status}`
      : this.source === "live"
        ? "Choose settings above and start a run, or inspect a saved run."
        : "Loading recorded measurements…";
    $("insight-source-note").hidden = this.source === "live";
    $("insight-coverage").textContent =
      `${n(m?.decisions ?? 0, 0)} completed decisions · whole run`;
    $("insight-warning").textContent = run?.warnings?.join(" ") || "";
    $("insight-export").hidden = !run?.run_id || !m?.decisions;
    $("insight-export").href = run?.run_id
      ? `/api/runs/${encodeURIComponent(run.run_id)}/insights?download=true`
      : "#";
    $("insight-play-rate").textContent = percent(m?.play_rate);
    $("insight-play-count").textContent = m
      ? `${n(m.spins, 0)} spins / ${n(m.decisions, 0)} decisions`
      : "No decisions yet";
    $("insight-recent").textContent = percent(m?.recent_play_rate);
    $("insight-recent-count").textContent =
      `Last ${n(m?.recent_decisions ?? 0, 0)} decisions · up to 20`;
    $("insight-wagered").textContent = money(m?.wagered_cents);
    $("insight-net").textContent = `Net result ${signed(m?.net_cents, money)}`;
    $("insight-risk").textContent = percent(m?.mean_bankroll_fraction_per_spin);
    $("insight-risk-max").textContent =
      `Largest share ${percent(m?.max_bankroll_fraction_per_spin)}`;
    $("insight-stake-note").textContent =
      run?.config?.wager_mode === "adaptive"
        ? `Neural signal selects affordable 1×, 2×, or 4× the ${money(run.config.stake_cents)} base stake. Mean played stake ${money(m?.mean_stake_cents)}. Tier counts: ${m?.stake_tiers?.["1"] ?? 0} / ${m?.stake_tiers?.["2"] ?? 0} / ${m?.stake_tiers?.["4"] ?? 0}. Choice of a larger wager does not by itself establish risk preference.`
        : run?.config
          ? `Each SPIN wagers ${money(run.config.stake_cents)}. The fly can play or wait; it cannot raise the stake. The same bet uses a larger share when the bankroll shrinks.`
          : "We measure wager size, play frequency, and the share of bankroll exposed.";
    if (run?.config?.wealth && run.config.wealth !== "off") {
      const w = m?.bankroll_influence;
      $("insight-stake-note").textContent += w?.decisions
        ? ` Bankroll influence (${run.config.wealth}): ${w.higher_proposals} higher and ${w.lower_proposals} lower proposals versus the unweighted decoder, across ${w.spins} SPIN decisions, before affordability. These are imposed decoder adjustments.`
        : " No completed decisions with bankroll weighting applied.";
    }
    $("insight-verdict").textContent = outcomeMessage(m);
    for (const name of ["win", "loss"]) {
      const c = m?.conditions[name];
      $(`after-${name}-rate`).textContent = percent(c?.next_spin_rate);
      $(`after-${name}-bar`).setAttribute(
        "width",
        (c?.next_spin_rate ?? 0) * 100,
      );
      $(`after-${name}-count`).textContent = c
        ? `${n(c.next_spins, 0)} plays / ${n(c.next_n, 0)} following decisions · ${n(c.without_next_decision, 0)} without a next decision`
        : "No following decisions yet";
      $(`after-${name}-spend`).textContent = money(
        c?.mean_followup_wager_cents,
      );
      $(`after-${name}-risk`).textContent =
        `Mean bankroll share on next decision: ${percent(c?.next_mean_bankroll_fraction)} · WAIT = 0. Larger next bet: ${n(c?.next_bet_increases ?? 0, 0)} / ${n(c?.next_n ?? 0, 0)} following decisions (${percent(c?.next_bet_increase_rate)}).`;
      $(`after-${name}-windows`).textContent = c
        ? `${n(c.windows, 0)} complete windows · ${n(c.incomplete_followups, 0)} incomplete / excluded`
        : "Needs five later decisions";
    }
    $("insight-spend-difference").textContent =
      m?.followup_spending_difference_cents == null
        ? "Spending comparison needs complete five-decision windows after both wins and losses."
        : `Observed difference after wins: ${signed(m.followup_spending_difference_cents, money)} wagered over the next five decisions.`;
    this.responses(m);
    this.waits(m, run?.config);
    const issue = comparisonIssue(
      run,
      this.reference,
      $("insight-compare-presets").checked,
    );
    this.chart(m, !issue ? this.reference.metrics : null);
    this.compare(run, issue);
  }

  responses(m) {
    const body = $("insight-responses");
    body.replaceChildren();
    for (const [key, label] of [
      ["win", "After a win"],
      ["loss", "After a loss"],
      ["wait", "After waiting"],
    ]) {
      const c = m?.conditions[key],
        response = c?.response;
      const row = body.insertRow();
      row.insertCell().textContent = label;
      row.insertCell().textContent = n(c?.response_n ?? 0, 0);
      for (const cell of ["pam", "ppl"]) {
        const before = response?.[`${cell}_before`],
          after = response?.[`${cell}_after`];
        row.insertCell().textContent =
          before == null || after == null
            ? "—"
            : `${n(before)} → ${n(after)} Hz (${signed(after - before, n)})`;
      }
    }
    $("insight-memory").textContent =
      m?.changed_edges == null
        ? "—"
        : `${n(m.changed_edges, 0)} connections changed`;
    $("insight-efficacy").textContent =
      m?.mean_efficacy == null
        ? "—"
        : `${n(m.mean_efficacy, 6)}× mean strength · starts at 1×`;
  }

  waits(m, config) {
    const target = $("insight-wait-reasons");
    if (config?.policy === "random-baseline") {
      target.textContent =
        "Random baseline: a separate coin flip chooses SPIN or WAIT. Neural output does not choose these actions.";
      return;
    }
    const r = m?.wait_reasons;
    target.textContent = !m?.waits
      ? "No completed WAIT decisions yet."
      : `${n(r.gate_only, 0)}: gate silent only · ${n(r.direction_only, 0)}: direction signal too low only · ${n(r.both, 0)}: both · ${n(r.unavailable, 0)}: unavailable. These describe the decoder, not the fly's intention.`;
  }

  chart(m, reference) {
    const kind = $("insight-chart-kind").value;
    const specs = {
      play: {
        value: (b) => b.play_rate * 100,
        format: (v) => percent(v / 100),
        label: "Decisions choosing SPIN",
        min: 0,
        max: 100,
      },
      bankroll: {
        value: (b) => b.bankroll,
        format: money,
        label: "Bankroll at the end of each block",
      },
      exposure: {
        value: (b) => b.mean_fraction_per_decision * 100,
        format: (v) => percent(v / 100),
        label:
          "Mean bankroll share wagered per decision; WAIT contributes zero",
        min: 0,
      },
      stake: {
        value: (b) => (b.spins ? b.wagered / b.spins : null),
        format: money,
        label: "Mean executed stake per SPIN; blocks without spins are missing",
        min: 0,
      },
      chemistry: {
        value: (b) => b.chemistry_exposure,
        format: n,
        label: "Reward-dose history at each block endpoint, model units",
        min: 0,
      },
      sensitivity: {
        value: (b) => b.reward_gain,
        format: (v) => (v == null ? "—" : `${n(v, 3)}×`),
        label: "Reward sensitivity at each block endpoint",
        anchor: 1,
      },
      wealth: {
        value: (b) => b.wealth_gain,
        format: (v) => (v == null ? "—" : `${n(v, 3)}×`),
        label:
          "Bankroll weight used before the last decision in each block; 1× is neutral",
        anchor: 1,
      },
      withdrawal: {
        value: (b) => b.withdrawal_current,
        format: n,
        label: "Withdrawal current at each block endpoint, model units",
        min: 0,
      },
      memory: {
        value: (b) => b.efficacy,
        format: (v) => `${n(v, 6)}×`,
        label: "Mean connection strength at the end of each block",
        anchor: 1,
      },
    };
    const spec = specs[kind],
      chart = $("insight-chart");
    chart.replaceChildren(svg("title", {}, spec.label));
    const series = [m?.timeline || [], reference?.timeline || []];
    const values = series
      .flatMap((points) => points.map(spec.value))
      .filter((v) => v != null && Number.isFinite(v));
    $("insight-chart-note").textContent = m?.decisions
      ? `${spec.label}. Blocks contain up to ${m.bin_size} decision${m.bin_size === 1 ? "" : "s"}${reference ? `; reference up to ${reference.bin_size}` : ""}. Hover for values; export for full precision.`
      : "The chart will use completed decisions. Saved runs can be inspected without starting a new experiment.";
    $("insight-reference-key").hidden = !reference;
    if (!values.length) {
      chart.append(
        svg(
          "text",
          { x: 500, y: 110, "text-anchor": "middle", class: "insight-axis" },
          "No measurements yet",
        ),
      );
      $("insight-chart-values").replaceChildren();
      return;
    }
    const min = spec.min ?? Math.min(...values, spec.anchor ?? Infinity);
    let max = spec.max ?? Math.max(...values, spec.anchor ?? -Infinity);
    if (max === min)
      max =
        min + (kind === "memory" ? 0.001 : Math.max(1, Math.abs(min) * 0.05));
    const last = Math.max(m?.decisions || 1, reference?.decisions || 1);
    const x = (v) => 115 + ((v - 1) / Math.max(1, last - 1)) * 850;
    const y = (v) => 180 - ((v - min) / (max - min)) * 150;
    for (let i = 0; i <= 3; i++) {
      const value = min + ((max - min) * i) / 3,
        at = y(value);
      chart.append(
        svg("line", {
          x1: 115,
          x2: 965,
          y1: at,
          y2: at,
          class: "insight-gridline",
        }),
        svg(
          "text",
          { x: 103, y: at + 4, "text-anchor": "end", class: "insight-axis" },
          spec.format(value),
        ),
      );
    }
    chart.append(
      svg("text", { x: 115, y: 210, class: "insight-axis" }, "Decision 1"),
      svg(
        "text",
        { x: 965, y: 210, "text-anchor": "end", class: "insight-axis" },
        `Decision ${n(last, 0)}`,
      ),
    );
    series.forEach((points, i) => {
      const valid = points.filter(
        (b) => spec.value(b) != null && Number.isFinite(spec.value(b)),
      );
      if (!valid.length) return;
      chart.append(
        svg("path", {
          d: valid
            .map((b, j) => `${j ? "L" : "M"}${x(b.end)},${y(spec.value(b))}`)
            .join(" "),
          class: i ? "insight-path reference" : "insight-path",
        }),
      );
      for (const b of valid) {
        const dot = svg("circle", {
          cx: x(b.end),
          cy: y(spec.value(b)),
          r: 4,
          class: i ? "insight-dot reference" : "insight-dot",
        });
        dot.append(
          svg(
            "title",
            {},
            `${i ? "Reference" : "Selected run"} · decisions ${b.start}–${b.end}: ${spec.format(spec.value(b))} · ${b.spins}/${b.n} SPIN`,
          ),
        );
        chart.append(dot);
      }
    });
    const body = $("insight-chart-values");
    body.replaceChildren();
    for (const b of series[0]) {
      const row = body.insertRow();
      for (const text of [
        `${b.start}–${b.end}`,
        `${b.spins} / ${b.n}`,
        spec.format(spec.value(b)),
      ])
        row.insertCell().textContent = text;
    }
  }

  compare(run, issue) {
    const reference = this.reference;
    $("insight-comparison").hidden = !reference || !!issue;
    $("insight-comparison-note").textContent = !reference
      ? "Choose a saved run with the same odds, stake, starting bankroll, decision limit, model and dataset. Learning-enabled, frozen-memory and random-baseline runs stay labeled separately."
      : issue ||
        `Selected: ${controller(run.config)} · seed ${run.config.seed} · ${run.metrics.decisions} decisions. Reference: ${controller(reference.config)} · seed ${reference.config.seed} · ${reference.metrics.decisions} decisions. Two sessions are a descriptive comparison, not evidence that learning caused a difference. Runtime versions may also differ; they are included in the export. ${[
          "physiology",
          "vision",
          "motor",
          "chemistry",
          "reward",
          "pulse",
          "memory",
          "wealth",
        ]
          .filter((k) => run.config[k] !== reference.config[k])
          .map((k) => `${k}: ${run.config[k]} versus ${reference.config[k]}`)
          .join("; ")}`;
    if (!reference || issue) return;
    const body = $("insight-comparison");
    body.replaceChildren();
    for (const [label, get] of [
      [
        "Play rate",
        (m) => `${percent(m.play_rate)} · ${m.spins}/${m.decisions}`,
      ],
      [
        "Play again after a win",
        (m) =>
          `${percent(m.conditions.win.next_spin_rate)} · ${m.conditions.win.next_spins}/${m.conditions.win.next_n}`,
      ],
      [
        "Play again after a loss",
        (m) =>
          `${percent(m.conditions.loss.next_spin_rate)} · ${m.conditions.loss.next_spins}/${m.conditions.loss.next_n}`,
      ],
      [
        "Spend in 5 decisions after wins",
        (m) =>
          `${money(m.conditions.win.mean_followup_wager_cents)} · ${m.conditions.win.windows} windows`,
      ],
      ["Mean played stake", (m) => money(m.mean_stake_cents)],
      ["Total wagered", (m) => money(m.wagered_cents)],
      ["Net result", (m) => signed(m.net_cents, money)],
    ]) {
      const row = body.insertRow();
      for (const text of [label, get(run.metrics), get(reference.metrics)])
        row.insertCell().textContent = text;
    }
  }
}
