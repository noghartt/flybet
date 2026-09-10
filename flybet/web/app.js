import { AnatomyView } from "./anatomy.js";
import { ReelView } from "./reels.js";
import { InsightView } from "./insights.js";
import { ExperimentView } from "./experiments.js";

const $ = (id) => document.getElementById(id);
const symbols = ["●", "◆", "7", "★"];
const money = (cents) =>
  `$${(cents / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = (cents) =>
  `${cents > 0 ? "+" : cents < 0 ? "−" : ""}${money(Math.abs(cents))}`;
const number = (v, digits = 1) =>
  Number(v).toLocaleString("en-US", { maximumFractionDigits: digits });
let scenario = "random";
let state = null;
let lastImage = -1;
let lastHistory = "";
let pending = false;
let lastRun = null;
let localError = "";
let lastRevision = "";
const reelView = new ReelView();
const insightView = new InsightView();
const experimentView = new ExperimentView(command, configuration);
const anatomyView = new AnatomyView(() => {
  if (state) drawBrain(state);
});

function selectScenario(value) {
  scenario = value;
  document.querySelectorAll("[data-scenario]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.scenario === value);
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.scenario === value),
    );
  });
}
document
  .querySelectorAll("[data-scenario]")
  .forEach((button) =>
    button.addEventListener("click", () =>
      selectScenario(button.dataset.scenario),
    ),
  );

function configuration(single = false) {
  for (const id of ["seed", "bankroll", "stake", "decisions"]) {
    if (!$(id).reportValidity())
      throw new Error("Check the experiment settings.");
  }
  const bankroll = Math.round(Number($("bankroll").value) * 100);
  const stake = Math.round(Number($("stake").value) * 100);
  if (!bankroll || !stake || stake > bankroll)
    throw new Error("The stake must fit inside the fake bankroll.");
  return {
    ...experimentView.config(),
    scenario,
    seed: Number($("seed").value),
    bankroll_cents: bankroll,
    stake_cents: stake,
    max_decisions: Number($("decisions").value),
    policy: $("policy").value,
    learning: $("learning").value === "true",
    single,
  };
}

async function command(route, payload) {
  if (pending) return;
  pending = true;
  localError = "";
  if (state) render(state);
  try {
    const response = await fetch(`/api/${route}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Flybet-Client": "local",
      },
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : `Request failed (${response.status}).`,
      );
    }
    const next = await fetch("/api/state");
    state = await next.json();
  } catch (error) {
    localError = error.message;
  } finally {
    pending = false;
    if (state) render(state);
  }
}
$("run").addEventListener("click", () => {
  try {
    command("run", configuration());
  } catch (e) {
    localError = e.message;
    if (state) render(state);
  }
});
$("step").addEventListener("click", () => {
  try {
    state?.status === "paused"
      ? command("step")
      : command("run", configuration(true));
  } catch (e) {
    localError = e.message;
    if (state) render(state);
  }
});
$("pause").addEventListener("click", () =>
  command(state?.status === "paused" ? "resume" : "pause"),
);

function setMoney(id, amount) {
  $(id).textContent = signed(amount);
  $(id).classList.toggle("positive", amount > 0);
  $(id).classList.toggle("negative", amount < 0);
}

function render(s) {
  state = s;
  if (lastRun !== s.run_id) {
    lastHistory = "";
    lastImage = -1;
    lastRun = s.run_id;
  }
  const busy = s.busy || pending;
  const available = s.dataset.available;
  experimentView.update(s, busy);
  $("run").disabled = busy || !available;
  $("run").firstChild.textContent = s.run_id
    ? "Start a fresh run "
    : "Start experiment ";
  $("step").disabled =
    busy ||
    !available ||
    Boolean(s.protocol) ||
    s.status === "finished" ||
    s.status === "error";
  $("pause").disabled =
    pending ||
    Boolean(s.protocol) ||
    (!s.busy && s.status !== "paused") ||
    s.saving ||
    s.status === "loading";
  $("pause").textContent =
    s.status === "paused" && !s.busy
      ? "Resume"
      : s.pause_requested
        ? "Pausing…"
        : "Pause";
  document
    .querySelectorAll(
      ".experiment-controls input, .experiment-controls select, [data-scenario]",
    )
    .forEach((element) => (element.disabled = busy));
  const note =
    localError ||
    s.error ||
    (!available
      ? "The MaleCNS dataset is not prepared. In your terminal, run: flybet prepare. Then restart this server."
      : s.status === "loading"
        ? "Verifying the full dataset and initializing 166,700 neurons…"
        : s.saving
          ? "Saving neural state and the experiment record…"
          : s.status === "finished"
            ? s.stop_reason
            : "");
  $("notice").hidden = !note;
  $("notice").textContent = note || "";
  $("status").textContent = s.saving
    ? "Saving"
    : s.status === "running"
      ? s.phase
      : s.status === "idle"
        ? "Ready"
        : s.status;
  $("dataset-status").textContent =
    `MaleCNS v1.0 · ${available ? `${number(s.dataset.neurons, 0)} neurons / ${number(s.dataset.edges / 1e6)}M connections` : "dataset required"}`;
  $("export").hidden = !s.run_id || !s.decision;
  const game = s.game;
  if (game) {
    $("bankroll-value").textContent = money(game.bankroll_cents);
    setMoney("session-net", game.net_cents);
    $("spins").textContent = number(game.spins, 0);
    $("wins").textContent = number(game.wins, 0);
    $("actual-rtp").textContent =
      game.observed_rtp === null ? "—" : `${number(game.observed_rtp * 100)}%`;
    $("run-scenario").textContent =
      s.scenarios[game.config.scenario].name.toUpperCase();
  }
  if (s.protocol) {
    $("bankroll-value").textContent = "—";
    $("session-net").textContent = "—";
    $("spins").textContent = "0";
    $("wins").textContent = "0";
    $("actual-rtp").textContent = "—";
    $("run-scenario").textContent = "CONDITIONING · NO WAGERS";
  }
  const outcome = s.outcome;
  reelView.update(s);
  $("reel-window").classList.toggle(
    "observing",
    s.phase === "observe" && s.status === "running",
  );
  if (s.decoder) {
    const d = s.decoder;
    $("decoder").textContent =
      `${number(d.difference_hz)} Hz · gate ${d.gate_spikes} · ${d.executed_action}${d.executed_stake_cents ? ` · ${money(d.executed_stake_cents)}` : ""}${d.policy !== "neural" ? " (baseline)" : ""}`;
    $("outcome").textContent =
      s.phase === "observe" && s.status === "running"
        ? "The fly is observing the reels…"
        : d.executed_action === "WAIT"
          ? "The fly chose to wait"
          : outcome?.won
            ? "Three matching symbols. 16× return."
            : "No matching line this time.";
  } else {
    $("decoder").textContent = "DNp20 R − L / DNpe017 gate";
    $("outcome").textContent =
      s.status === "loading"
        ? "Preparing the full connectome…"
        : "Waiting for the first neural decision";
  }
  if (outcome) setMoney("net-spin", outcome.net_cents);
  else $("net-spin").textContent = "—";
  const t = s.telemetry;
  $("brain-empty").hidden = !!t;
  $("neural-clock").textContent = ((t?.neural_ms || 0) / 1000).toFixed(2);
  const metric = (id, value, unit) => {
    $(id).replaceChildren(document.createTextNode(value));
    const small = document.createElement("small");
    small.textContent = ` ${unit}`;
    $(id).append(small);
  };
  metric("pam-rate", t ? number(t.rates_hz[4]) : "—", "Hz");
  metric("ppl-rate", t ? number(t.rates_hz[5]) : "—", "Hz");
  metric("plastic-count", t ? number(t.memory.changed, 0) : "0", "/ 7,835");
  $("pam-delivery").textContent = t ? `${number(t.pam_delivery[6])} a.u.` : "—";
  $("ppl-delivery").textContent = t ? `${number(t.ppl_delivery[7])} a.u.` : "—";
  $("efficacy").textContent = `${(t?.memory.mean || 1).toFixed(6)}×`;
  const pulse = t?.chemistry
    ? t.chemistry.withdrawal_current > 0
      ? "WITHDRAWAL → PPL101"
      : t.chemistry.reward_current > 0
        ? "PAM11"
        : t.chemistry.aversive_current > 0
          ? "PPL101"
          : null
    : t?.stimulus === "reward"
      ? "PAM11"
      : t?.stimulus === "aversive"
        ? "PPL101"
        : null;
  $("stimulus").textContent = pulse
    ? s.status === "running"
      ? `${pulse} CURRENT ON`
      : `LAST: ${pulse} PULSE`
    : "NO OUTCOME PULSE";
  if (s.image_revision !== lastImage) {
    $("retina").src = `/api/retina.png?v=${s.image_revision}`;
    lastImage = s.image_revision;
  }
  document
    .querySelectorAll("[data-phase]")
    .forEach((item) =>
      item.classList.toggle(
        "active",
        s.status === "running" &&
          (item.dataset.phase === s.phase ||
            (s.phase === "wait" && item.dataset.phase === "decide")),
      ),
    );
  const historyKey = `${s.run_id}:${s.history.length}:${s.history.at(-1)?.decision}`;
  if (historyKey !== lastHistory) {
    const body = $("history");
    body.replaceChildren();
    if (!s.history.length) {
      const row = body.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 8;
      cell.className = "empty-row";
      cell.textContent =
        "Outcomes and neural measurements will appear after each completed decision.";
    }
    for (const row of [...s.history].reverse().slice(0, 12)) {
      const tr = body.insertRow();
      const values = [
        String(row.decision).padStart(3, "0"),
        row.action,
        row.reels.map((i) => symbols[i]).join("  "),
        money(row.stake_cents),
        signed(row.net_cents),
        row.stimulus,
        `${row.pam_spikes} / ${row.ppl_spikes}`,
        money(row.bankroll_cents),
      ];
      values.forEach((value, i) => {
        const cell = tr.insertCell();
        cell.textContent = value;
        if (i === 4)
          cell.className =
            row.net_cents > 0
              ? "positive"
              : row.net_cents < 0
                ? "negative"
                : "";
        if (i === 5) {
          const pill = document.createElement("span");
          pill.className = `pill ${row.stimulus}`;
          pill.textContent = value;
          cell.replaceChildren(pill);
        }
      });
    }
    lastHistory = historyKey;
  }
  drawBrain(s);
  drawTrace(s.series);
  anatomyView.update(s);
  insightView.update(s);
}

function context(id) {
  const canvas = $(id),
    rect = canvas.getBoundingClientRect(),
    ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, rect.width),
    height = Math.max(1, rect.height);
  if (
    canvas.width !== Math.round(width * ratio) ||
    canvas.height !== Math.round(height * ratio)
  ) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return [ctx, width, height];
}

const positions = [
  [0.1, 0.36],
  [0.1, 0.65],
  [0.29, 0.5],
  [0.5, 0.43],
  [0.39, 0.16],
  [0.61, 0.16],
  [0.7, 0.38],
  [0.7, 0.68],
  [0.9, 0.28],
  [0.9, 0.5],
  [0.9, 0.74],
];
const labels = [
  "R1–R6",
  "R8",
  "LAMINA",
  "KC",
  "PAM11",
  "PPL101",
  "MBON07",
  "MBON11",
  "DNp20 L",
  "DNp20 R",
  "DNpe017",
];
const colors = positions.map((_, i) =>
  i === 4 || i === 6 ? "#ffa568" : i === 5 || i === 7 ? "#ee8ca8" : "#d2ff65",
);

function drawBrain(s) {
  if ($("circuit-view").hidden) return;
  const [c, w, h] = context("brain");
  const radius = Math.min(w * 0.034, 18);
  const points = positions.map(([x, y]) => [x * w, y * h]);
  const rates = s.telemetry?.rates_hz || [];
  // Only draw an anatomical connection when the compiled dataset records it.
  if (s.anatomy)
    for (let i = 0; i < 11; i++)
      for (let j = 0; j < 11; j++) {
        const contacts = s.anatomy[i][j];
        if (!contacts || i === j) continue;
        const [x, y] = points[i],
          [xx, yy] = points[j];
        const activity = Math.min(1, (rates[i] || 0) / 60);
        c.strokeStyle = activity
          ? `${colors[i]}${Math.round(25 + activity * 65)
              .toString(16)
              .padStart(2, "0")}`
          : "#35443b";
        c.lineWidth = Math.min(2, 0.45 + Math.log10(contacts + 1) * 0.2);
        const curve = (i < j ? -1 : 1) * 13;
        c.beginPath();
        c.moveTo(x, y);
        c.quadraticCurveTo((x + xx) / 2, (y + yy) / 2 + curve, xx, yy);
        c.stroke();
        if (activity > 0) {
          // Position follows neural time; activity controls visibility, never an invented rate.
          const p = (s.telemetry.neural_ms / 400 + i * 0.07 + j * 0.11) % 1;
          const px =
            (1 - p) * (1 - p) * x +
            2 * (1 - p) * p * ((x + xx) / 2) +
            p * p * xx;
          const py =
            (1 - p) * (1 - p) * y +
            2 * (1 - p) * p * ((y + yy) / 2 + curve) +
            p * p * yy;
          c.fillStyle = colors[i];
          c.globalAlpha = activity;
          c.beginPath();
          c.arc(px, py, 1.5, 0, Math.PI * 2);
          c.fill();
          c.globalAlpha = 1;
        }
      }
  points.forEach(([x, y], i) => {
    const activity = Math.min(1, (rates[i] || 0) / 60);
    c.fillStyle = "#19221f";
    c.beginPath();
    c.arc(x, y, radius + 3, 0, Math.PI * 2);
    c.fill();
    c.strokeStyle = colors[i];
    c.globalAlpha = s.telemetry ? 0.3 + activity * 0.7 : 0.3;
    c.lineWidth = 1.3;
    c.beginPath();
    c.arc(x, y, radius, 0, Math.PI * 2);
    c.stroke();
    if (activity) {
      c.globalAlpha = activity * 0.14;
      c.beginPath();
      c.arc(x, y, radius + 7, 0, Math.PI * 2);
      c.fillStyle = colors[i];
      c.fill();
    }
    c.globalAlpha = 1;
    c.fillStyle = s.telemetry ? colors[i] : "#99a69d";
    c.font = `${w < 430 ? 9 : 10}px monospace`;
    c.textAlign = "center";
    c.fillText(s.telemetry ? number(rates[i], 0) : "—", x, y + 3);
    c.fillStyle = "#afbbb2";
    c.font = `${w < 430 ? 9 : 10}px monospace`;
    c.fillText(labels[i], x, y + radius + 16);
  });
  c.textAlign = "left";
  c.fillStyle = "#697b70";
  c.font = "10px monospace";
  c.fillText("INPUT", w * 0.055, h * 0.91);
  c.textAlign = "right";
  c.fillText("OUTPUT", w * 0.96, h * 0.91);
}

function drawTrace(series) {
  const [c, w, h] = context("trace");
  const left = 33,
    top = 15,
    right = w - 6,
    bottom = h - 22;
  const maximum = Math.max(20, ...series.flatMap((p) => [p.pam, p.ppl]));
  c.font = "10px monospace";
  c.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = top + ((bottom - top) * i) / 4;
    c.strokeStyle = "#334039";
    c.beginPath();
    c.moveTo(left, y);
    c.lineTo(right, y);
    c.stroke();
    c.fillStyle = "#99a69d";
    c.textAlign = "right";
    c.fillText(number(maximum * (1 - i / 4), 0), left - 7, y + 3);
  }
  if (series.length < 2) {
    c.fillStyle = "#99a69d";
    c.textAlign = "center";
    c.fillText("Waiting for measured neural activity", w / 2, h / 2);
    return;
  }
  const start = series[0].ms,
    span = Math.max(10, series.at(-1).ms - start);
  for (const [key, color] of [
    ["pam", "#ffa568"],
    ["ppl", "#ee8ca8"],
  ]) {
    c.strokeStyle = color;
    c.lineWidth = 1.6;
    c.beginPath();
    series.forEach((p, i) => {
      const x = left + ((p.ms - start) / span) * (right - left),
        y = bottom - (p[key] / maximum) * (bottom - top);
      i ? c.lineTo(x, y) : c.moveTo(x, y);
    });
    c.stroke();
  }
  c.fillStyle = "#99a69d";
  c.textAlign = "left";
  c.fillText(`${(start / 1000).toFixed(2)}s`, left, h - 3);
  c.textAlign = "right";
  c.fillText(`${(series.at(-1).ms / 1000).toFixed(2)}s`, right, h - 3);
}

const observer = new ResizeObserver(() => {
  if (state) {
    drawBrain(state);
    drawTrace(state.series);
  }
});
observer.observe($("brain"));
observer.observe($("trace"));
const stream = new EventSource("/api/events");
stream.onmessage = (event) => {
  anatomyView.connection(true);
  $("connection").textContent = "Local connection";
  $("connection-light").classList.add("online");
  try {
    const next = JSON.parse(event.data),
      revision = `${next.revision}:${next.busy}`;
    if (revision !== lastRevision) {
      render(next);
      lastRevision = revision;
    }
  } catch (error) {
    console.error(error);
  }
};
stream.onerror = () => {
  reelView.finish();
  anatomyView.connection(false);
  $("connection").textContent = "Reconnecting…";
  $("connection-light").classList.remove("online");
};
window.addEventListener("beforeunload", () => stream.close());
