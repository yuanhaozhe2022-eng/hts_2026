import { loadSettings, saveSettings } from "./settings.js";
import { FULL_LOCK_DEG, Steering, setSteeringReference } from "./steering.js";
import { AxisSlider, HoldButton, Joystick, PedalBar } from "./controls.js";
import { Layout } from "./layout.js";
import { Dash, SHIFT_AT } from "./dash.js";
import { BUZZ_MS, buzz, hapticsKind, stop as stopHaptics, tap } from "./haptics.js";
import { applyRotation, initRotation, isIOS } from "./orientation.js";

const $ = (sel) => document.querySelector(sel);

// Bits of the "b" field; must match server/state.py.
const BTN_SHIFT_DOWN = 1 << 0;
const BTN_SHIFT_UP = 1 << 1;
const SEND_INTERVAL_MS = 15;   // ~60 Hz
const PING_INTERVAL_MS = 1000;

const settings = loadSettings();
const steering = new Steering(settings);
// Learned from a landscape session on this phone; until then guess (iOS reports gravity
// the other way round from Android). Only matters for the sideways HUD on a locked screen.
steering.gravitySign = settings.gravitySign ?? (isIOS ? -1 : 1);
const dash = new Dash($(".dash"), settings);
initRotation($("#hud"));
$("#ios-tip").hidden = !isIOS;
const haptic = (strength) => settings.vibration && strength !== "off" && tap(strength);

const bars = {
  brake: new PedalBar($('[data-el="brake"]')),
  throttle: new PedalBar($('[data-el="throttle"]')),
};
const buttons = {
  shiftDown: new HoldButton($('[data-el="shiftDown"]'), () => haptic(settings.shiftHaptic)),
  shiftUp: new HoldButton($('[data-el="shiftUp"]'), () => haptic(settings.shiftHaptic)),
};
const customControls = new Map();  // id -> HoldButton / Joystick / AxisSlider (user's own)
const layout = new Layout($("#hud"), () => {
  for (const bar of Object.values(bars)) bar.updateOrientation();
});

function releaseAll() {
  for (const bar of Object.values(bars)) bar.release();
  for (const button of Object.values(buttons)) button.release();
  for (const control of customControls.values()) control.release();
}

// ---------------------------------------------------------------- connection

let ws = null;
let rumble = 0;     // 0..1, strongest of the game's two rumble motors
let kicked = false;
let retries = 0;
let latency = null;
let pingId = 0;
const pings = new Map();

// Identifies this page to the PC, so its own reconnects after a dropout always get back in.
const clientId = Math.random().toString(36).slice(2, 10);

// auto: reconnecting by itself, which never takes control from another phone that's driving.
function connect(auto = false) {
  kicked = false;
  dash.connection("connecting");
  // Plain ws:// when served from http://localhost (Android over USB).
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws?id=${clientId}${auto ? "&auto=1" : ""}`);
  ws = socket;

  socket.onopen = () => {
    retries = 0;
    dash.connection("open", latency);
  };
  socket.onmessage = (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    if (msg.t === "tel") {
      dash.telemetry(msg);
      feelTelemetry(msg);
    } else if (msg.t === "binds") {
      showBindings(msg.buttons, msg.options);
      showCustom(msg.custom || [], msg.options, msg.keys || [], msg.custom_binds || {});
    } else if (msg.t === "pong" && pings.has(msg.id)) {
      const rtt = performance.now() - pings.get(msg.id);
      pings.delete(msg.id);
      latency = latency == null ? rtt : latency * 0.7 + rtt * 0.3;
      dash.connection("open", latency);
    } else if (msg.t === "rumble") {
      rumble = Math.max(msg.l, msg.s);
    } else if (msg.t === "kicked") {
      kicked = true;
      releaseAll();
      $("#kicked-by").textContent = msg.by ? ` (${msg.by})` : "";
      $("#kicked").hidden = false;
    }
  };
  socket.onclose = () => {
    if (ws !== socket) return;
    ws = null;
    rumble = 0;
    shiftPulse = absActive = false;
    stopHaptics();
    dash.connection("closed");
    for (const select of bindSelects) select.disabled = true;
    setCustomEditorEnabled(false);
    if (kicked) return;
    const delay = Math.min(5000, 500 * 2 ** retries++);
    setTimeout(() => connect(true), delay);
  };
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

const round = (x) => Math.round(x * 10000) / 10000;

function currentInput(neutral = false) {
  if (neutral) return { t: "in", s: 0, th: 0, br: 0, b: 0, c: [], a: {} };
  const b = (buttons.shiftDown.pressed ? BTN_SHIFT_DOWN : 0) | (buttons.shiftUp.pressed ? BTN_SHIFT_UP : 0);
  return {
    t: "in",
    s: round(steering.value()),
    th: round(bars.throttle.value),
    br: round(bars.brake.value),
    b,
    c: [...customControls].filter(([, c]) => c.kind === "button" && c.pressed).map(([id]) => id),
    // Joysticks [x, y] and axes v, only while touched.
    a: Object.fromEntries([...customControls]
      .filter(([, c]) => c.kind !== "button" && c.value != null)
      .map(([id, c]) => [id, Array.isArray(c.value) ? c.value.map(round) : round(c.value)])),
  };
}

// ---------------------------------------------------------------- sideways HUD

let holdDir = 90;        // 90: phone's top points left, -90: points right
let holdKnown = false;
let holdSince = 0;
let rotationMode = 0;

function updateRotation() {
  const mode = applyRotation(document.body.classList.contains("driving"), holdDir);
  if (mode !== rotationMode) releaseAll();  // fingers' positions mean something else now
  rotationMode = mode;
  setSteeringReference(mode === 0 ? null : mode);
  $("#flip-btn").hidden = mode === 0;
  layout.apply();
}

// On a portrait screen, work out which way round the phone is held from its roll
// (+90 = top to the left). Turning the other way round only takes effect after half a
// second past upright, so even a hard turn can't flip the HUD.
function trackHold(now) {
  if (window.innerHeight <= window.innerWidth || steering.angle == null) return;
  const want = steering.angle >= 0 ? 90 : -90;
  if (want === holdDir) {
    holdKnown = true;
    holdSince = 0;
  } else if (!holdKnown || (holdSince && now - holdSince > 500)) {
    holdDir = want;
    holdKnown = true;
    holdSince = 0;
    updateRotation();
  } else if (!holdSince) {
    holdSince = now;
  }
}

window.addEventListener("resize", updateRotation);

// ---------------------------------------------------------------- main loop

let lastSend = 0;
let lastPing = 0;

function frame(now) {
  requestAnimationFrame(frame);
  if (now - lastSend < SEND_INTERVAL_MS) return;
  lastSend = now;
  trackHold(now);

  // While editing the layout, hold everything neutral so nothing reaches the game.
  const editing = layout.editing;
  const msg = currentInput(editing);
  send(msg);
  dash.steering(editing ? 0 : msg.s, settings.lockSteering);

  if (now - lastPing > PING_INTERVAL_MS) {
    lastPing = now;
    if (!panel.hidden) $("#sensor-info").textContent = steering.sensorInfo();
    pings.set(++pingId, now);
    if (pings.size > 10) pings.delete(pings.keys().next().value);
    send({ t: "ping", id: pingId });
  }
}

// ---------------------------------------------------------------- haptics
// Feel the car from telemetry, so it works in every game (few games rumble a gamepad):
// a thump on each gear change, pulses at the shift point, a buzz while ABS works.
// Rumble the game does send to the virtual controller is added on top.
let lastGear = null;
let shiftPulse = false;
let absActive = false;

function feelTelemetry(t) {
  // The estimator's gear just follows your own presses, which already tick.
  if (t.src !== "est" && lastGear != null && t.g !== lastGear) haptic("medium");
  lastGear = t.g;
  shiftPulse = settings.hapticShift && t.src !== "est" && (t.sl || (t.m > 0 && t.r / t.m >= SHIFT_AT));
  absActive = settings.hapticAbs && t.li?.abs === true;
}

let hapticTick = 0;
setInterval(() => {
  if (!settings.vibration || document.hidden) return;
  hapticTick++;
  const strength = Math.max(rumble, absActive ? 0.45 : 0);
  if (strength > 0.05) buzz(strength);
  else if (shiftPulse && hapticTick % 2 === 0) tap("light");
}, BUZZ_MS);

$("#haptic-test").addEventListener("click", () => {
  const result = $("#haptic-result");
  if (hapticsKind === "none") {
    result.textContent = "This browser has no vibration.";
  } else if (hapticsKind === "ios-switch") {
    tap("heavy");
    result.textContent = "Felt a tick? If not: iOS 18 or newer is needed, and Settings → Sounds & Haptics → System Haptics must be on.";
  } else {
    const ok = navigator.vibrate([60, 80, 60]);
    result.textContent = ok
      ? "Sent. Felt nothing? On the phone: Settings → Sound & vibration → Vibration & haptics on, and not in Do Not Disturb or Battery Saver."
      : "Chrome blocked it. Tap the page once and try again.";
  }
});

// ---------------------------------------------------------------- start / lifecycle

async function keepAwake() {
  try {
    await navigator.wakeLock?.request("screen");
  } catch {
    // Not supported or refused: the phone may dim; harmless.
  }
}

function showToast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.hidden = false;
  setTimeout(() => (el.hidden = true), 6000);
}

function showStartError(text) {
  const el = $("#start-error");
  el.textContent = text;
  el.hidden = false;
}

async function start() {
  if (!window.isSecureContext) {
    showStartError("This page must be opened over https:// (use the address the PC prints), " +
      "otherwise the browser blocks the motion sensors.");
    return;
  }

  // Fullscreen and the iOS permission prompt both need this tap, so start them before any await.
  const fullscreen = document.documentElement.requestFullscreen?.({ navigationUI: "hide" });
  const permission = typeof DeviceMotionEvent !== "undefined" &&
    typeof DeviceMotionEvent.requestPermission === "function"
    ? DeviceMotionEvent.requestPermission()
    : Promise.resolve("granted");

  try {
    if ((await permission) !== "granted") throw new Error("denied");
  } catch {
    showStartError("Motion access was denied, so steering can't work. On iPhone: close this tab, " +
      "reopen the page and tap Allow (or enable Settings > Safari > Motion & Orientation Access).");
    return;
  }
  try {
    await fullscreen;
    await screen.orientation?.lock?.("landscape");
  } catch {
    // iOS has no fullscreen/orientation lock; a portrait screen gets the sideways HUD.
  }
  keepAwake();

  $("#start-screen").hidden = true;
  $("#hud").hidden = false;
  document.body.classList.add("driving");
  updateRotation();
  if (isIOS && window.innerWidth > window.innerHeight) {
    // Still landscape means Rotation Lock is off, so a hard turn could flip the screen.
    showToast("Reminder: turn on Rotation Lock (Control Center → lock button) so the screen " +
      "can't flip while you steer. PocketWheel stays sideways by itself.");
  }

  steering.start();
  // Learn this phone's gravity convention whenever the screen is truly landscape.
  const detect = (e) => {
    if (!steering.detectGravitySign(e)) return;
    settings.gravitySign = steering.gravitySign;
    saveSettings(settings);
    window.removeEventListener("devicemotion", detect);
  };
  window.addEventListener("devicemotion", detect);
  setTimeout(() => {
    if (steering.angle == null) {
      showToast("No motion sensor data: steering won't work. Hold the phone upright, " +
        "and check motion access is allowed for this site.");
    }
  }, 2000);

  connect();
  requestAnimationFrame(frame);
}

$("#start-btn").addEventListener("click", start);

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    // Lift everything immediately rather than waiting for the PC's watchdog.
    releaseAll();
    send(currentInput(true));
  } else if (document.body.classList.contains("driving")) {
    keepAwake();
  }
});

$("#reclaim-btn").addEventListener("click", () => {
  $("#kicked").hidden = true;
  connect();
});

// Block iOS pinch-zoom and double-tap zoom, which ignore user-scalable=no.
document.addEventListener("gesturestart", (e) => e.preventDefault());
document.addEventListener("dblclick", (e) => e.preventDefault());
document.addEventListener("contextmenu", (e) => e.preventDefault());

// ---------------------------------------------------------------- settings panel

const panel = $("#settings");
const formats = {
  sensitivity: (v) => `×${Number(v).toFixed(1)} · full lock at ±${Math.round(FULL_LOCK_DEG / v)}°`,
  smoothing: (v) => `${Math.round(v * 100)}%`,
  deadzone: (v) => `${Math.round(v * 100)}%`,
  curve: (v) => Number(v).toFixed(1),
};

for (const input of panel.querySelectorAll("[data-setting]")) {
  const key = input.dataset.setting;
  const output = panel.querySelector(`output[data-for="${key}"]`);
  const show = () => output && (output.textContent = formats[key](settings[key]));
  if (input.type === "checkbox") input.checked = settings[key];
  else input.value = settings[key];
  show();
  input.addEventListener("input", () => {
    settings[key] = input.type === "checkbox" ? input.checked
      : input.tagName === "SELECT" ? input.value : Number(input.value);
    saveSettings(settings);
    show();
  });
}

$("#settings-btn").addEventListener("click", () => {
  if (layout.editing) return;
  releaseAll();
  $("#sensor-info").textContent = steering.sensorInfo();
  panel.hidden = false;
});

// ---------------------------------------------------------------- button bindings (kept on the PC)

const BUTTON_LABELS = {
  A: "A", B: "B", X: "X", Y: "Y",
  LEFT_SHOULDER: "LB", RIGHT_SHOULDER: "RB",
  LEFT_THUMB: "LS (stick click)", RIGHT_THUMB: "RS (stick click)",
  START: "Start", BACK: "Back",
  DPAD_UP: "D-pad up", DPAD_DOWN: "D-pad down", DPAD_LEFT: "D-pad left", DPAD_RIGHT: "D-pad right",
};
const label = (name) => BUTTON_LABELS[name] || name;
const bindSelects = [...panel.querySelectorAll("select[data-bind]")];
const shiftLabels = {
  shift_up: [$('[data-el="shiftUp"] .shift-label'), "UP"],
  shift_down: [$('[data-el="shiftDown"] .shift-label'), "DOWN"],
};

function showBindings(bindings, options) {
  for (const select of bindSelects) {
    const action = select.dataset.bind;
    if (select.options.length !== options.length) {
      select.replaceChildren(...options.map((name) => new Option(label(name), name)));
    }
    select.value = bindings[action];
    select.disabled = false;
    const [el, text] = shiftLabels[action];
    el.textContent = `${text} · ${label(bindings[action]).split(" ")[0]}`;
  }
}

for (const select of bindSelects) {
  select.addEventListener("change", () => {
    // The PC applies it, saves it to config.json, and answers with the bindings now in effect.
    send({ t: "bind", buttons: { [select.dataset.bind]: select.value } });
  });
}
$("#settings-close").addEventListener("click", () => (panel.hidden = true));

// ---------------------------------------------------------------- custom controls (kept on the PC)
// Buttons (Xbox button or keyboard key), joysticks (a stick or WASD / arrow keys) and axes
// (one stick axis or a trigger). The PC keeps the list in config.json.

const KEY_LABELS = {
  SPACE: "Space", ENTER: "Enter", TAB: "Tab", ESCAPE: "Esc", BACKSPACE: "Backspace",
  UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→", INSERT: "Insert", DELETE: "Delete", HOME: "Home",
  END: "End", PAGEUP: "PgUp", PAGEDOWN: "PgDn", LSHIFT: "Shift", LCTRL: "Ctrl",
};
const keyLabel = (k) => KEY_LABELS[k] || k.replace(/^NUMPAD(\d)$/, "Num $1");
const ANALOG_LABELS = {
  "stick:right": ["Right stick (camera)", "R-stick"],
  "stick:left": ["Left stick (walk; replaces steering while held)", "L-stick"],
  "keys:wasd": ["W A S D keys", "WASD"],
  "keys:arrows": ["Arrow keys", "Arrows"],
  "axis:RX": ["Right stick X (look left/right)", "R-stick X"],
  "axis:RY": ["Right stick Y (look up/down)", "R-stick Y"],
  "axis:LY": ["Left stick Y", "L-stick Y"],
  "axis:LT": ["Left trigger", "LT"],
  "axis:RT": ["Right trigger", "RT"],
};
// [long text for the settings list, short text shown on the control itself]
const bindText = (bind) => {
  if (ANALOG_LABELS[bind]) return ANALOG_LABELS[bind];
  const [target, name] = bind.split(":");
  return target === "pad" ? [label(name), label(name).split(" ")[0]] : [`Key ${keyLabel(name)}`, keyLabel(name)];
};
const isCentered = (bind) => bind !== "axis:LT" && bind !== "axis:RT";
const KINDS = {
  button:   { name: "Button",   label: "BTN",  bind: "pad:Y" },
  joystick: { name: "Joystick", label: "Cam",  bind: "stick:right" },
  axis:     { name: "Axis",     label: "Look", bind: "axis:RX" },
};
// Where new controls go: free spots around the shift buttons and the dash.
const CUSTOM_SLOTS = [
  { x: 0.165, y: 0.16, w: 0.13, h: 0.28 }, { x: 0.705, y: 0.16, w: 0.13, h: 0.28 },
  { x: 0.165, y: 0.83, w: 0.13, h: 0.14 }, { x: 0.705, y: 0.83, w: 0.13, h: 0.14 },
  { x: 0.33, y: 0.83, w: 0.12, h: 0.14 }, { x: 0.55, y: 0.83, w: 0.12, h: 0.14 },
];
const MAX_CUSTOM = 12;
let customDefs = [];
let customBindOptions = {};
const customList = $("#custom-list");
const customAddButtons = [...document.querySelectorAll("[data-add-kind]")];

function freeSlot() {
  const taken = [...customControls.keys()].map((id) => layout.boxes[`custom:${id}`]);
  const slot = CUSTOM_SLOTS.find((s) => !taken.some((b) => b && b.x === s.x && b.y === s.y));
  return { ...(slot || { x: 0.44, y: 0.42, w: 0.12, h: 0.22 }) };
}

// Axes start shaped like what they control: wide for left/right, tall for up/down and triggers.
const WIDE_SLOTS = [  // along the bottom, either side of the settings button
  { x: 0.29, y: 0.82, w: 0.17, h: 0.13 }, { x: 0.54, y: 0.82, w: 0.17, h: 0.13 },
];
function defaultBox(def) {
  if (def.kind === "axis" && def.bind.endsWith("X")) {
    const taken = [...customControls.keys()].map((id) => layout.boxes[`custom:${id}`]);
    const slot = WIDE_SLOTS.find((s) => !taken.some((b) => b && b.x === s.x && b.y === s.y));
    if (slot) return { ...slot };
  }
  const box = freeSlot();
  if (def.kind !== "axis") return box;
  const w = 0.07;  // tall and narrow, centred in the slot
  return { ...box, x: box.x + (box.w - w) / 2, w, h: Math.max(box.h, 0.28) };
}

const CONTROL_HTML = {
  button: '<span class="custom-name"></span><span class="shift-label"></span>',
  joystick: '<div class="stick-base"><div class="stick-knob"></div></div>' +
            '<span class="custom-name"></span><span class="shift-label"></span>',
  axis: '<div class="axis-track"><div class="axis-knob"></div></div>' +
        '<span class="custom-name"></span><span class="shift-label"></span>',
};

// ⚙ per-control settings, kept with the control on the PC ("opts").
const OPTION_DEFAULTS = {
  haptic: "light", releaseHaptic: false, mode: "hold", rate: 8, spring: true, sensitivity: 1,
  invert: false, edgeHaptic: false, centerHaptic: true, color: "default", opacity: 1,
};
const optsOf = (def) => ({
  ...OPTION_DEFAULTS, deadzone: def.kind === "joystick" ? 0.08 : 0.06, ...def.opts });
const COLORS = {
  red: "#ef4444", orange: "#f97316", green: "#22c55e", blue: "#3b82f6", purple: "#a855f7" };
const pct = (v) => `${Math.round(v * 100)}%`;
const ALL_KINDS = ["button", "joystick", "axis"];
const ANALOG = ["joystick", "axis"];
// What the cog shows, per kind. `when` hides options that don't apply right now.
const OPTION_UI = [
  { key: "haptic", label: "Vibration click", kinds: ALL_KINDS,
    choices: [["off", "Off"], ["light", "Light"], ["medium", "Medium"], ["heavy", "Heavy"]] },
  { key: "releaseHaptic", label: "Click on release too", kinds: ["button"], check: true },
  { key: "mode", label: "Mode", kinds: ["button"], choices: [
    ["hold", "Hold (pressed while touched)"], ["toggle", "Toggle (tap on, tap off)"],
    ["tap", "Tap (one short press)"], ["repeat", "Rapid fire (while held)"]] },
  { key: "rate", label: "Rapid-fire rate", kinds: ["button"], range: [2, 15, 1],
    format: (v) => `${v} /s`, when: (o) => o.mode === "repeat" },
  { key: "spring", label: "Spring back when released", kinds: ANALOG, check: true },
  { key: "deadzone", label: "Dead zone", kinds: ANALOG, range: [0, 0.4, 0.01], format: pct },
  { key: "sensitivity", label: "Sensitivity", kinds: ["joystick"], range: [0.5, 3, 0.1],
    format: (v) => `×${Number(v).toFixed(1)}` },
  { key: "invert", label: "Invert", kinds: ANALOG, check: true },
  { key: "edgeHaptic", label: "Click at full tilt", kinds: ["joystick"], check: true },
  { key: "centerHaptic", label: "Click when crossing the middle", kinds: ["axis"], check: true,
    when: (o, def) => isCentered(def.bind) },
  { key: "color", label: "Color", kinds: ALL_KINDS, choices: [["default", "Default"],
    ...Object.keys(COLORS).map((c) => [c, c[0].toUpperCase() + c.slice(1)])] },
  { key: "opacity", label: "Opacity", kinds: ALL_KINDS, range: [0.3, 1, 0.05], format: pct },
];
const openCogs = new Set();  // ids whose ⚙ box is open, kept across re-renders

function applyOpts(control, def) {
  const o = optsOf(def);
  control.onPress = () => haptic(o.haptic);
  if (def.kind === "button") {
    control.mode = o.mode;
    control.rate = o.rate;
    control.onRelease = o.releaseHaptic ? () => haptic("light") : null;
  } else {
    control.opts = { spring: o.spring, deadzone: o.deadzone, invert: o.invert, sensitivity: o.sensitivity };
    control.onEdge = def.kind === "joystick" && o.edgeHaptic ? () => haptic("light") : null;
    control.onCenter = def.kind === "axis" && o.centerHaptic ? () => haptic("light") : null;
  }
  const el = control.el;
  if (COLORS[o.color]) el.style.setProperty("--accent", COLORS[o.color]);
  else el.style.removeProperty("--accent");
  el.classList.toggle("colored", !!COLORS[o.color]);
  el.style.opacity = o.opacity < 1 ? o.opacity : "";
}

function optionsBox(def, update) {
  const o = optsOf(def);
  const box = document.createElement("div");
  box.className = "custom-opts";
  const set = (key, value) => update({ opts: { ...def.opts, [key]: value } });
  for (const ui of OPTION_UI) {
    if (!ui.kinds.includes(def.kind) || (ui.when && !ui.when(o, def))) continue;
    const label = Object.assign(document.createElement("label"), { textContent: ui.label });
    let input;
    if (ui.check) {
      input = Object.assign(document.createElement("input"), { type: "checkbox", checked: o[ui.key] });
      input.addEventListener("change", () => set(ui.key, input.checked));
      label.prepend(input);
      label.className = "opt-check";
      box.append(label);
      continue;
    }
    if (ui.choices) {
      input = document.createElement("select");
      input.append(...ui.choices.map(([v, text]) => new Option(text, v)));
      input.value = o[ui.key];
      input.addEventListener("change", () => set(ui.key, input.value));
    } else {
      const [min, max, step] = ui.range;
      input = Object.assign(document.createElement("input"), { type: "range", min, max, step, value: o[ui.key] });
      const out = document.createElement("output");
      out.textContent = ui.format(o[ui.key]);
      label.append(" ", out);
      input.addEventListener("input", () => (out.textContent = ui.format(Number(input.value))));
      input.addEventListener("change", () => set(ui.key, Number(input.value)));
    }
    box.append(label, input);
  }
  return box;
}

function createControl(def) {
  const el = document.createElement("div");
  el.className = `el custom custom-${def.kind}` + (def.kind === "button" ? " shift" : "");
  el.dataset.el = `custom:${def.id}`;
  el.innerHTML = CONTROL_HTML[def.kind];
  $("#hud").insertBefore(el, $("#toast"));
  const control = def.kind === "joystick" ? new Joystick(el)
    : def.kind === "axis" ? new AxisSlider(el, isCentered(def.bind))
    : new HoldButton(el);
  control.kind = def.kind;
  return control;
}

// Bring the HUD and the settings editor in line with the PC's list.
function showCustom(defs, padOptions, keys, bindOptions) {
  customDefs = defs;
  customBindOptions = bindOptions;
  const ids = new Map(defs.map((d) => [d.id, d]));
  for (const [id, control] of [...customControls]) {
    if (ids.get(id)?.kind !== control.kind) {  // removed (kinds never change for an id)
      customControls.delete(id);
      layout.remove(`custom:${id}`);
    }
  }
  for (const def of defs) {
    let control = customControls.get(def.id);
    if (!control) {
      control = createControl(def);
      customControls.set(def.id, control);
      layout.add(`custom:${def.id}`, control.el, defaultBox(def));  // a saved position wins
      layout.save();  // remember where it went
    }
    if (def.kind === "axis") control.centered = isCentered(def.bind);
    control.release();
    applyOpts(control, def);
    control.el.querySelector(".custom-name").textContent = def.label;
    control.el.querySelector(".shift-label").textContent = bindText(def.bind)[1];
  }
  renderCustomEditor(padOptions, keys);
}

function bindSelect(def, padOptions, keys) {
  const select = document.createElement("select");
  const group = (title, options) => {
    const g = document.createElement("optgroup");
    g.label = title;
    g.append(...options.map(([v, text]) => new Option(text, v)));
    return g;
  };
  if (def.kind === "button") {
    select.append(
      group("Controller button", padOptions.map((b) => [`pad:${b}`, label(b)])),
      group("Keyboard key", keys.map((k) => [`key:${k}`, `Key ${keyLabel(k)}`])),
    );
  } else {
    select.append(...(customBindOptions[def.kind] || []).map((b) => new Option(bindText(b)[0], b)));
  }
  select.value = def.bind;
  return select;
}

function renderCustomEditor(padOptions, keys) {
  const sendList = (list) => send({ t: "custom", buttons: list });
  customList.replaceChildren(...customDefs.map((def, i) => {
    const row = document.createElement("div");
    row.className = "custom-row";
    const kind = Object.assign(document.createElement("span"), {
      className: "custom-kind", textContent: KINDS[def.kind].name });
    const name = Object.assign(document.createElement("input"), { value: def.label, maxLength: 12 });
    name.setAttribute("aria-label", "Label");
    const bind = bindSelect(def, padOptions, keys);
    const cog = Object.assign(document.createElement("button"), {
      textContent: "⚙", title: "Settings for this control", className: "cog" });
    const del = Object.assign(document.createElement("button"), { textContent: "✕", title: "Remove" });
    const update = (change) => sendList(customDefs.map((d, j) => (j === i ? { ...d, ...change } : d)));
    name.addEventListener("change", () => update({ label: name.value.trim() || def.label }));
    bind.addEventListener("change", () => update({ bind: bind.value }));
    del.addEventListener("click", () => {
      openCogs.delete(def.id);
      sendList(customDefs.filter((_, j) => j !== i));
    });
    row.append(kind, name, bind, cog, del);

    const item = document.createElement("div");
    item.className = "custom-item";
    const box = optionsBox(def, update);
    const showBox = (open) => {
      box.hidden = !open;
      cog.classList.toggle("open", open);
    };
    showBox(openCogs.has(def.id));
    cog.addEventListener("click", () => {
      const open = !openCogs.has(def.id);
      if (open) openCogs.add(def.id); else openCogs.delete(def.id);
      showBox(open);
    });
    item.append(row, box);
    return item;
  }));
  for (const add of customAddButtons) {
    const kind = add.dataset.addKind;
    add.onclick = () => sendList([...customDefs, {
      id: "c" + Math.random().toString(36).slice(2, 8),
      label: `${KINDS[kind].label} ${customDefs.filter((d) => d.kind === kind).length + 1}`,
      kind,
      bind: KINDS[kind].bind,
    }]);
  }
  setCustomEditorEnabled(true);
}

function setCustomEditorEnabled(on) {
  for (const el of customList.querySelectorAll("input, select, button")) el.disabled = !on;
  for (const add of customAddButtons) add.disabled = !on || customDefs.length >= MAX_CUSTOM;
}

$("#calibrate-btn").addEventListener("click", (e) => {
  steering.calibrate();
  saveSettings(settings);
  const btn = e.currentTarget;
  btn.textContent = steering.angle == null ? "No motion data" : "Centered ✓";
  setTimeout(() => (btn.textContent = "Center steering"), 1200);
});

$("#edit-layout-btn").addEventListener("click", () => {
  panel.hidden = true;
  releaseAll();
  layout.setEditing(true);
  $("#edit-bar").hidden = false;
});
$("#layout-done").addEventListener("click", () => {
  layout.setEditing(false);
  $("#edit-bar").hidden = true;
});
$("#layout-reset").addEventListener("click", () => layout.reset());

// Sideways HUD upside down: this phone reports gravity the other way round than guessed.
$("#flip-btn").addEventListener("click", () => {
  steering.gravitySign = -steering.gravitySign;
  steering.reset();  // re-seed from the corrected gravity
  settings.gravitySign = steering.gravitySign;
  saveSettings(settings);
  holdKnown = false;
});
