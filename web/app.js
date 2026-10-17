import { loadSettings, saveSettings } from "./settings.js";
import { FULL_LOCK_DEG, Steering, setSteeringReference } from "./steering.js";
import { PedalBar, HoldButton } from "./controls.js";
import { Layout } from "./layout.js";
import { Dash } from "./dash.js";
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
const dash = new Dash($(".dash"));
initRotation($("#hud"));
$("#ios-tip").hidden = !isIOS;
const vibrate = (ms) => settings.vibration && navigator.vibrate?.(ms);

const bars = {
  brake: new PedalBar($('[data-el="brake"]')),
  throttle: new PedalBar($('[data-el="throttle"]')),
};
const buttons = {
  shiftDown: new HoldButton($('[data-el="shiftDown"]'), () => vibrate(15)),
  shiftUp: new HoldButton($('[data-el="shiftUp"]'), () => vibrate(15)),
};
const layout = new Layout($("#hud"), () => {
  for (const bar of Object.values(bars)) bar.updateOrientation();
});

function releaseAll() {
  for (const bar of Object.values(bars)) bar.release();
  for (const button of Object.values(buttons)) button.release();
}

// ---------------------------------------------------------------- connection

let ws = null;
let rumble = 0;     // 0..1, strongest of the game's two rumble motors
let kicked = false;
let retries = 0;
let latency = null;
let pingId = 0;
const pings = new Map();

function connect() {
  kicked = false;
  dash.connection("connecting");
  // Plain ws:// when served from http://localhost (Android over USB).
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws`);
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
    } else if (msg.t === "binds") {
      showBindings(msg.buttons, msg.options);
    } else if (msg.t === "pong" && pings.has(msg.id)) {
      const rtt = performance.now() - pings.get(msg.id);
      pings.delete(msg.id);
      latency = latency == null ? rtt : latency * 0.7 + rtt * 0.3;
      dash.connection("open", latency);
    } else if (msg.t === "rumble") {
      rumble = Math.max(msg.l, msg.s);
    } else if (msg.t === "kicked") {
      kicked = true;
      $("#kicked").hidden = false;
    }
  };
  socket.onclose = () => {
    if (ws !== socket) return;
    ws = null;
    rumble = 0;
    dash.connection("closed");
    for (const select of bindSelects) select.disabled = true;
    if (kicked) return;
    const delay = Math.min(5000, 500 * 2 ** retries++);
    setTimeout(connect, delay);
  };
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

const round = (x) => Math.round(x * 10000) / 10000;

function currentInput(neutral = false) {
  if (neutral) return { t: "in", s: 0, th: 0, br: 0, b: 0 };
  const b = (buttons.shiftDown.pressed ? BTN_SHIFT_DOWN : 0) | (buttons.shiftUp.pressed ? BTN_SHIFT_UP : 0);
  return {
    t: "in",
    s: round(steering.value()),
    th: round(bars.throttle.value),
    br: round(bars.brake.value),
    b,
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

// Game rumble -> phone vibration. The Vibration API has no strength, so use duty cycle.
setInterval(() => {
  if (rumble > 0.05 && !document.hidden) vibrate(Math.round(20 + rumble * 100));
}, 120);

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
      "can't flip while you steer. PhoneWheel stays sideways by itself.");
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
    settings[key] = input.type === "checkbox" ? input.checked : Number(input.value);
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
