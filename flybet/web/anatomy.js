// Actual MaleCNS soma positions + measured per-neuron activity. No generated geometry.
import { ActivityMotion } from "./motion.js";
const $ = (id) => document.getElementById(id);
const fmt = (n) =>
  Number(n).toLocaleString("en-US", { maximumFractionDigits: 1 });
const rgb = (hex) =>
  [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);

const vertex = `
precision highp float;
attribute vec3 position;
attribute vec3 familyColor;
attribute float rate;
attribute vec2 previousRate;
attribute float population;
attribute float group;
attribute float part;
attribute float neuron;
uniform vec3 center;
uniform vec2 angle;
uniform vec2 scale;
uniform float mode;
uniform float filter;
uniform float scope;
uniform float selected;
uniform float pixelRatio;
uniform float blend;
uniform float pulseEnvelope;
varying vec4 color;
void main() {
  vec3 p = position - center;
  p = vec3(p.x, -p.z, p.y);
  float cy = cos(angle.x), sy = sin(angle.x), cp = cos(angle.y), sp = sin(angle.y);
  p = vec3(cy*p.x + sy*p.z, p.y, -sy*p.x + cy*p.z);
  p = vec3(p.x, cp*p.y - sp*p.z, sp*p.y + cp*p.z);
  gl_Position = vec4(p.xy * scale, clamp(p.z / 2000.0, -0.95, 0.95), 1.0);
  float strength = sqrt(mix(previousRate.x, rate, blend));
  float pulse = sqrt(max(0.0, rate - previousRate.y)) * pulseEnvelope;
  bool dan = group == 4.0 || group == 5.0;
  vec3 active = dan ? (group == 4.0 ? vec3(1.0,.647,.408) : vec3(.933,.549,.659)) : vec3(1.0,.93,.65);
  vec3 tint = mode == 1.0 ? familyColor : mix(vec3(.60,.70,.70), active, strength);
  float alpha = (part == 1.0 ? .21 : .09) + strength * .76;
  if (mode == 1.0) alpha = .18 + strength * .64;
  if (mode == 2.0) {
    tint = dan ? active : vec3(.44,.55,.56);
    alpha = dan ? .65 + strength * .35 : .035;
  }
  if (filter >= 0.0 && population != filter) alpha *= .065;
  tint = mix(tint, active, pulse);
  alpha = min(1.0, alpha * (1.0 + pulse));
  float size = 1.0 + strength * 2.0 + pulse * 6.0;
  if (dan && (mode == 2.0 || filter == 7.0)) size = 4.0 + strength * 3.0 + pulse * 6.0;
  if (neuron == selected) { size = 8.0; tint = vec3(1.0); alpha = 1.0; }
  if ((scope == 1.0 && part != 0.0) || (scope == 2.0 && part != 1.0)) alpha = 0.0;
  gl_PointSize = size * pixelRatio;
  color = vec4(tint, alpha);
}`;
const fragment = `
precision mediump float;
varying vec4 color;
void main() {
  float radius = length(gl_PointCoord - vec2(.5)) * 2.0;
  if (radius > 1.0 || color.a == 0.0) discard;
  gl_FragColor = vec4(color.rgb, color.a * (1.0 - smoothstep(.45, 1.0, radius)));
}`;

export class AnatomyView {
  constructor(onViewChange) {
    this.canvas = $("anatomical-brain");
    this.yaw = 0;
    this.pitch = 0;
    this.zoom = 1;
    this.scope = "cns";
    this.mode = 0;
    this.filter = -1;
    this.selected = -1;
    this.visible = true;
    this.lastMs = -1;
    this.generation = 0;
    this.state = null;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)");
    this.reduced.addEventListener("change", () => this.syncMotion());
    this.onViewChange = onViewChange;
    this.setupControls();
    new ResizeObserver(() => this.draw()).observe(this.canvas);
    document.addEventListener("visibilitychange", () =>
      this.update(this.state),
    );
    this.load();
  }

  async load() {
    try {
      const response = await fetch("/api/anatomy");
      if (!response.ok)
        throw new Error(
          "Anatomical coordinates unavailable. Check the prepared MaleCNS annotations.",
        );
      this.meta = await response.json();
      const points = await fetch("/api/anatomy/points");
      if (!points.ok)
        throw new Error("Could not load the anatomical point cloud.");
      const buffer = await points.arrayBuffer();
      const digest = Array.from(
        new Uint8Array(await crypto.subtle.digest("SHA-256", buffer)),
        (b) => b.toString(16).padStart(2, "0"),
      ).join("");
      if (
        digest !== this.meta.points_sha256 ||
        buffer.byteLength !== this.meta.located_neurons * 20
      )
        throw new Error("Anatomical point cloud failed its integrity check.");
      const n = this.meta.located_neurons;
      const data = new DataView(buffer);
      this.positions = new Float32Array(n * 3);
      this.indices = new Uint32Array(n);
      this.families = new Uint8Array(n);
      this.groups = new Uint8Array(n);
      this.parts = new Uint8Array(n);
      this.motion = new ActivityMotion(n);
      this.rates = this.motion.rates;
      this.allRates = new Uint8Array(this.meta.total_neurons);
      this.colors = new Float32Array(n * 3);
      const palette = this.meta.populations.map((p) => rgb(p.color));
      for (let i = 0; i < n; i++) {
        const at = i * 20;
        this.indices[i] = data.getUint32(at, true);
        if (this.indices[i] >= this.meta.total_neurons)
          throw new Error("Anatomical neuron index is invalid.");
        for (let j = 0; j < 3; j++)
          this.positions[i * 3 + j] = data.getFloat32(at + 4 + j * 4, true);
        this.families[i] = data.getUint8(at + 16);
        this.groups[i] = data.getUint8(at + 17);
        this.parts[i] = data.getUint8(at + 18);
        this.colors.set(palette[this.families[i]], i * 3);
      }
      this.setupRenderer();
      this.setupPopulations();
      $("anatomy-coverage").textContent =
        `${fmt(n)} located / ${fmt(this.meta.total_neurons)} simulated`;
      $("anatomy-note").textContent =
        `One point per annotated cell body. ${fmt(this.meta.unlocated_neurons)} neurons lack soma coordinates and remain simulated. Colors identify cell families, not neuropil boundaries.`;
      $("anatomy-message").hidden = true;
      this.draw();
      this.update(this.state);
    } catch (error) {
      $("anatomy-message").textContent = error.message;
      $("anatomy-message").hidden = false;
    }
  }

  setupRenderer() {
    const gl = this.canvas.getContext("webgl", {
      alpha: false,
      antialias: false,
    });
    if (!gl) {
      this.ctx = this.canvas.getContext("2d");
      if (!this.ctx)
        throw new Error(
          "This browser cannot draw the anatomical view. The circuit view remains available.",
        );
      $("anatomy-renderer").textContent = "CANVAS · ALL LOCATED CELLS";
      return;
    }
    this.gl = gl;
    const shader = (type, source) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, source);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
        throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const program = gl.createProgram();
    gl.attachShader(program, shader(gl.VERTEX_SHADER, vertex));
    gl.attachShader(program, shader(gl.FRAGMENT_SHADER, fragment));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS))
      throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    this.uniforms = Object.fromEntries(
      [
        "center",
        "angle",
        "scale",
        "mode",
        "filter",
        "scope",
        "selected",
        "pixelRatio",
        "blend",
        "pulseEnvelope",
      ].map((k) => [k, gl.getUniformLocation(program, k)]),
    );
    const attribute = (
      name,
      array,
      size,
      type = gl.FLOAT,
      normalized = false,
      dynamic = false,
    ) => {
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(
        gl.ARRAY_BUFFER,
        array,
        dynamic ? gl.DYNAMIC_DRAW : gl.STATIC_DRAW,
      );
      const location = gl.getAttribLocation(program, name);
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, size, type, normalized, 0, 0);
      return buffer;
    };
    attribute("position", this.positions, 3);
    attribute("familyColor", this.colors, 3);
    attribute("population", this.families, 1, gl.UNSIGNED_BYTE);
    attribute("group", this.groups, 1, gl.UNSIGNED_BYTE);
    attribute("part", this.parts, 1, gl.UNSIGNED_BYTE);
    attribute("neuron", Float32Array.from(this.indices), 1);
    this.rateBuffer = attribute(
      "rate",
      this.rates,
      1,
      gl.UNSIGNED_BYTE,
      true,
      true,
    );
    this.previousBuffer = attribute(
      "previousRate",
      this.motion.previous,
      2,
      gl.FLOAT,
      false,
      true,
    );
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    gl.disable(gl.DEPTH_TEST);
    this.canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      this.contextLost = true;
      this.syncMotion();
      $("anatomy-message").hidden = false;
      $("anatomy-message").textContent =
        "Graphics context lost. Reload to restore the anatomical view; the simulation is still running.";
    });
  }

  setupControls() {
    $("anatomy-motion").addEventListener("change", () => this.syncMotion());
    document.querySelectorAll("[data-brain-view]").forEach((b) =>
      b.addEventListener("click", () => {
        this.visible = b.dataset.brainView === "anatomy";
        $("anatomy-view").hidden = !this.visible;
        $("circuit-view").hidden = this.visible;
        document
          .querySelectorAll("[data-brain-view]")
          .forEach((item) =>
            item.setAttribute("aria-pressed", String(item === b)),
          );
        this.onViewChange();
        this.update(this.state);
        this.draw();
      }),
    );
    $("anatomy-scope").addEventListener("change", (e) => {
      this.scope = e.target.value;
      this.zoom = 1;
      this.draw();
    });
    $("anatomy-color").addEventListener("change", (e) => {
      this.mode = Number(e.target.value);
      this.draw();
    });
    document.querySelectorAll("[data-camera]").forEach((b) =>
      b.addEventListener("click", () => {
        const view = b.dataset.camera;
        if (view === "in" || view === "out")
          this.zoom = Math.max(
            0.5,
            Math.min(5, this.zoom * (view === "in" ? 1.25 : 0.8)),
          );
        else {
          this.yaw = view === "side" ? Math.PI / 2 : 0;
          this.pitch = view === "dorsal" ? Math.PI / 2 : 0;
          this.zoom = 1;
        }
        this.draw();
      }),
    );
    this.canvas.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      this.drag = {
        x: e.clientX,
        y: e.clientY,
        startX: e.clientX,
        startY: e.clientY,
      };
      this.canvas.setPointerCapture(e.pointerId);
    });
    this.canvas.addEventListener("pointermove", (e) => {
      if (!this.drag) return;
      this.yaw += (e.clientX - this.drag.x) * 0.008;
      this.pitch = Math.max(
        -Math.PI / 2,
        Math.min(Math.PI / 2, this.pitch + (e.clientY - this.drag.y) * 0.008),
      );
      this.drag.x = e.clientX;
      this.drag.y = e.clientY;
      this.draw();
    });
    this.canvas.addEventListener("pointerup", (e) => {
      if (!this.drag) return;
      if (
        Math.hypot(e.clientX - this.drag.startX, e.clientY - this.drag.startY) <
        5
      )
        this.pick(e);
      this.drag = null;
    });
    this.canvas.addEventListener("pointercancel", () => {
      this.drag = null;
    });
    this.canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        this.zoom = Math.max(
          0.5,
          Math.min(5, this.zoom * Math.exp(-e.deltaY * 0.001)),
        );
        this.draw();
      },
      { passive: false },
    );
    this.canvas.addEventListener("keydown", (e) => {
      if (
        ![
          "ArrowLeft",
          "ArrowRight",
          "ArrowUp",
          "ArrowDown",
          "+",
          "=",
          "-",
          "0",
        ].includes(e.key)
      )
        return;
      e.preventDefault();
      if (e.key === "ArrowLeft") this.yaw -= 0.1;
      if (e.key === "ArrowRight") this.yaw += 0.1;
      if (e.key === "ArrowUp") this.pitch -= 0.1;
      if (e.key === "ArrowDown") this.pitch += 0.1;
      if (e.key === "+" || e.key === "=")
        this.zoom = Math.min(5, this.zoom * 1.2);
      if (e.key === "-") this.zoom = Math.max(0.5, this.zoom / 1.2);
      if (e.key === "0") {
        this.yaw = this.pitch = 0;
        this.zoom = 1;
      }
      this.draw();
    });
  }

  setupPopulations() {
    const container = $("anatomy-populations");
    const items = [
      {
        name: "All cells",
        color: "#e5ede8",
        located: this.meta.located_neurons,
      },
      ...this.meta.populations,
    ];
    items.forEach((population, i) => {
      const button = document.createElement("button");
      button.className = "population-filter";
      button.setAttribute("aria-pressed", String(i === 0));
      // CSS class palettes keep this compatible with the strict content security policy.
      button.classList.add(`population-${i - 1}`);
      const name = document.createElement("span");
      name.textContent = population.name;
      const value = document.createElement("b");
      value.textContent = "—";
      value.id = `population-rate-${i - 1}`;
      button.append(name, value);
      button.title = `${fmt(population.located)} located cells. Click to highlight.`;
      button.addEventListener("click", () => {
        this.filter = i - 1;
        container
          .querySelectorAll("button")
          .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
        this.draw();
      });
      container.append(button);
    });
  }

  update(state) {
    if (!state) return;
    this.state = state;
    if (this.run !== (state.activity_id || state.run_id)) {
      this.run = state.activity_id || state.run_id;
      this.lastMs = -1;
      this.generation++;
      this.allRates?.fill(0);
      this.motion?.clear();
      this.uploadRates();
      this.updateReadouts();
      this.draw();
    }
    this.connection(this.connected);
    if (
      !this.meta ||
      !this.rates ||
      !this.visible ||
      document.hidden ||
      this.fetching ||
      !state.telemetry ||
      state.telemetry.neural_ms <= this.lastMs
    )
      return;
    this.fetchActivity(this.generation);
  }

  async fetchActivity(generation) {
    this.fetching = true;
    let retry = false;
    try {
      const response = await fetch("/api/activity", { cache: "no-store" });
      if (response.status === 204) return;
      if (!response.ok) throw new Error("Neural activity stream unavailable.");
      const buffer = await response.arrayBuffer();
      if (
        generation !== this.generation ||
        response.headers.get("X-Flybet-Run") !== this.run
      )
        return;
      if (response.headers.get("X-Flybet-Ids") !== this.meta.ids_sha256)
        throw new Error("Neural activity does not match the anatomical index.");
      const data = new DataView(buffer);
      if (
        buffer.byteLength !== 16 + this.meta.total_neurons ||
        data.getUint32(0, true) !== 0x31414246 ||
        data.getUint32(4, true) !== this.meta.total_neurons
      )
        throw new Error("Invalid neural activity frame.");
      const ms = data.getFloat64(8, true);
      if (!Number.isFinite(ms) || ms <= this.lastMs) return;
      this.lastMs = ms;
      this.allRates = new Uint8Array(buffer, 16);
      const next = new Uint8Array(this.indices.length);
      for (let i = 0; i < this.indices.length; i++)
        next[i] = this.allRates[this.indices[i]];
      this.motion.set(next, performance.now(), this.canAnimate());
      this.uploadRates();
      this.updateReadouts();
      this.draw();
      this.connection(this.connected);
      this.animate();
      retry = this.state?.telemetry?.neural_ms > this.lastMs;
      $("anatomy-message").hidden = true;
    } catch (error) {
      this.stopMotion();
      $("anatomy-message").textContent = error.message;
      $("anatomy-message").hidden = false;
    } finally {
      this.fetching = false;
      // A terminal SSE update may arrive while an older frame is in flight.
      if (retry || generation !== this.generation)
        setTimeout(() => this.update(this.state), 100);
    }
  }

  connection(connected) {
    this.connected = connected;
    this.syncMotion();
    $("anatomy-live").textContent =
      connected === false
        ? "CONNECTION LOST · LAST FRAME"
        : this.state?.status === "running"
          ? "LIVE SIMULATION"
          : this.lastMs >= 0
            ? "LAST MEASURED FRAME"
            : "ANATOMY · AWAITING ACTIVITY";
  }

  canAnimate() {
    return (
      this.connected === true &&
      this.state?.status === "running" &&
      this.visible &&
      !document.hidden &&
      !this.contextLost &&
      !this.reduced.matches &&
      $("anatomy-motion").checked
    );
  }

  syncMotion() {
    if (!this.canAnimate()) this.stopMotion();
    $("anatomy-motion-note").textContent = this.reduced.matches
      ? "Reduced motion · measured frames without transitions"
      : !$("anatomy-motion").checked
        ? "Measured frames · animation off"
        : this.canAnimate()
          ? "Live transitions · halos mark increases in measured firing rate"
          : "Frozen frame · animation resumes with live activity";
  }

  stopMotion() {
    const moving = this.animationFrame != null || this.motion?.started != null;
    cancelAnimationFrame(this.animationFrame);
    this.animationFrame = null;
    this.motion?.finish();
    if (moving) this.draw();
  }

  animate() {
    if (!this.canAnimate() || !this.motion || this.animationFrame != null)
      return;
    const frame = () => {
      this.animationFrame = null;
      if (!this.canAnimate()) return this.stopMotion();
      this.draw();
      if (!this.motion.weights(performance.now()).done)
        this.animationFrame = requestAnimationFrame(frame);
    };
    this.animationFrame = requestAnimationFrame(frame);
  }

  uploadRates() {
    if (!this.gl || this.contextLost || !this.rateBuffer) return;
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.rateBuffer);
    this.gl.bufferSubData(this.gl.ARRAY_BUFFER, 0, this.rates);
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.previousBuffer);
    this.gl.bufferSubData(this.gl.ARRAY_BUFFER, 0, this.motion.previous);
  }

  updateReadouts() {
    if (!this.meta || !this.rates) return;
    const sums = new Float64Array(this.meta.populations.length);
    let total = 0;
    for (let i = 0; i < this.rates.length; i++) {
      sums[this.families[i]] += this.rates[i];
      total += this.rates[i];
    }
    const values = [
      total / this.rates.length,
      ...Array.from(
        sums,
        (s, i) => s / Math.max(1, this.meta.populations[i].located),
      ),
    ];
    values.forEach((v, i) => {
      const element = $(`population-rate-${i - 1}`);
      if (element)
        element.textContent =
          this.lastMs < 0 ? "—" : `${fmt((v * 200) / 255)} Hz`;
    });
    $("anatomy-time").textContent =
      this.lastMs < 0 ? "—" : `${(this.lastMs / 1000).toFixed(2)} s`;
    if (this.selected >= 0)
      $("neuron-rate").textContent =
        this.lastMs < 0
          ? "No activity yet"
          : `≈ ${fmt((this.allRates[this.selected] * 200) / 255)} Hz`;
  }

  camera() {
    const rect = this.canvas.getBoundingClientRect();
    const bounds = this.meta?.bounds[this.scope];
    if (!bounds || !rect.width || !rect.height) return null;
    const center = bounds[0].map((v, i) => (v + bounds[1][i]) / 2);
    const extent = bounds[0].map((v, i) => bounds[1][i] - v);
    const aspect = rect.width / rect.height;
    const span = Math.max(extent[2], extent[1], extent[0] / aspect) * 1.18;
    const sy = (2 * this.zoom) / span;
    return {
      center,
      sx: sy / aspect,
      sy,
      width: rect.width,
      height: rect.height,
    };
  }

  project(i, camera) {
    const x = this.positions[i * 3] - camera.center[0];
    const y = -(this.positions[i * 3 + 2] - camera.center[2]);
    const z = this.positions[i * 3 + 1] - camera.center[1];
    const cy = Math.cos(this.yaw),
      sy = Math.sin(this.yaw),
      cp = Math.cos(this.pitch),
      sp = Math.sin(this.pitch);
    return [
      ((1 + (cy * x + sy * z) * camera.sx) * camera.width) / 2,
      ((1 - (cp * y - sp * (-sy * x + cy * z)) * camera.sy) * camera.height) /
        2,
    ];
  }

  inScope(i) {
    return (
      this.scope === "cns" || this.parts[i] === (this.scope === "brain" ? 0 : 1)
    );
  }

  draw() {
    if (!this.visible || !this.positions || this.contextLost) return;
    const camera = this.camera();
    if (!camera) return;
    const motion = this.motion.weights(performance.now());
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const width = Math.round(camera.width * ratio),
      height = Math.round(camera.height * ratio);
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    if (this.gl) {
      const gl = this.gl,
        u = this.uniforms;
      gl.viewport(0, 0, width, height);
      gl.clearColor(0.067, 0.094, 0.09, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform3fv(u.center, camera.center);
      gl.uniform2f(u.angle, this.yaw, this.pitch);
      gl.uniform2f(u.scale, camera.sx, camera.sy);
      gl.uniform1f(u.pixelRatio, ratio);
      gl.uniform1f(u.blend, motion.mix);
      gl.uniform1f(u.pulseEnvelope, motion.pulse);
      gl.uniform1f(u.mode, this.mode);
      gl.uniform1f(u.filter, this.filter);
      gl.uniform1f(
        u.scope,
        this.scope === "cns" ? 0 : this.scope === "brain" ? 1 : 2,
      );
      gl.uniform1f(u.selected, this.selected);
      gl.drawArrays(gl.POINTS, 0, this.indices.length);
    } else if (this.ctx) {
      const c = this.ctx;
      c.setTransform(ratio, 0, 0, ratio, 0, 0);
      c.fillStyle = "#111817";
      c.fillRect(0, 0, camera.width, camera.height);
      for (let i = 0; i < this.indices.length; i++) {
        if (!this.inScope(i)) continue;
        const [x, y] = this.project(i, camera);
        if (x < 0 || x > camera.width || y < 0 || y > camera.height) continue;
        const rate = this.rates[i] / 255,
          a = Math.sqrt(
            this.motion.previous[2 * i] * (1 - motion.mix) + rate * motion.mix,
          ),
          pulse =
            Math.sqrt(Math.max(0, rate - this.motion.previous[2 * i + 1])) *
            motion.pulse,
          dan = this.groups[i] === 4 || this.groups[i] === 5;
        c.globalAlpha =
          this.mode === 1
            ? 0.18 + a * 0.64
            : (this.parts[i] === 1 ? 0.21 : 0.09) + a * 0.76;
        c.fillStyle =
          this.mode === 1
            ? this.meta.populations[this.families[i]].color
            : this.groups[i] === 4
              ? "#ffa568"
              : this.groups[i] === 5
                ? "#ee8ca8"
                : a > 0.05
                  ? "#f9eab0"
                  : "#9bb2b2";
        if (this.filter >= 0 && this.families[i] !== this.filter)
          c.globalAlpha *= 0.065;
        if (this.mode === 2 && !dan) c.globalAlpha = 0.035;
        c.globalAlpha = Math.min(1, c.globalAlpha * (1 + pulse));
        const size =
          (dan && this.mode === 2 ? 4 + a * 3 : 1 + a * 2) + pulse * 6;
        c.fillRect(x, y, size, size);
      }
      c.globalAlpha = 1;
    }
  }

  async pick(event) {
    if (!this.positions) return;
    const camera = this.camera(),
      rect = this.canvas.getBoundingClientRect();
    if (!camera) return;
    const x = event.clientX - rect.left,
      y = event.clientY - rect.top;
    let nearest = -1,
      distance = 64;
    for (let i = 0; i < this.indices.length; i++) {
      if (
        !this.inScope(i) ||
        (this.filter >= 0 && this.families[i] !== this.filter)
      )
        continue;
      if (this.mode === 2 && this.groups[i] !== 4 && this.groups[i] !== 5)
        continue;
      const [px, py] = this.project(i, camera),
        d = (x - px) ** 2 + (y - py) ** 2;
      if (d < distance) {
        distance = d;
        nearest = i;
      }
    }
    if (nearest < 0) return;
    this.selected = this.indices[nearest];
    const selected = this.selected;
    this.draw();
    try {
      const response = await fetch(`/api/anatomy/neuron/${selected}`);
      if (!response.ok) throw new Error("Cell information unavailable.");
      const cell = await response.json();
      if (this.selected !== selected) return;
      $("neuron-name").textContent = `${cell.type} · ${cell.body_id}`;
      $("neuron-family").textContent =
        `${cell.population} · soma side ${cell.soma_side}`;
      $("neuron-inspector").hidden = false;
      this.updateReadouts();
    } catch (error) {
      $("neuron-name").textContent = error.message;
      $("neuron-inspector").hidden = false;
    }
  }
}
