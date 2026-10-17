// Touch controls: pedal bars and shift buttons.
//
// Each control captures the pointer that touched it, so every thumb drives its own
// control independently (brake + throttle + shift at once), and a thumb that slides
// off a bar keeps controlling it until lifted.

import { hudPoint } from "./orientation.js";

const clamp01 = (x) => Math.min(1, Math.max(0, x));

// A small dead band at each end: resting a thumb at the bottom reads 0, and full
// throttle/brake doesn't need the very top pixel.
const END_BAND = 0.04;
const pedalCurve = (raw) => clamp01((raw - END_BAND) / (1 - 2 * END_BAND));

const isEditing = () => document.body.classList.contains("editing");

export class PedalBar {
  constructor(el, onChange) {
    this.el = el;
    this.value = 0;
    this.pointerId = null;
    this.onChange = onChange;
    this.valueText = el.querySelector(".bar-value");

    el.addEventListener("pointerdown", (e) => {
      if (isEditing() || this.pointerId !== null) return;
      e.preventDefault();
      this.pointerId = e.pointerId;
      el.setPointerCapture(e.pointerId);
      el.classList.add("active");
      this._track(e);  // touching jumps the bar straight to the finger
    });
    el.addEventListener("pointermove", (e) => {
      if (e.pointerId === this.pointerId) this._track(e);
    });
    const release = (e) => {
      if (e.pointerId !== this.pointerId) return;
      this.pointerId = null;
      el.classList.remove("active");
      this.set(0);  // snap back like a real pedal
    };
    el.addEventListener("pointerup", release);
    el.addEventListener("pointercancel", release);
    el.addEventListener("lostpointercapture", release);
  }

  _track(e) {
    // HUD coordinates, so this also works when the HUD is drawn rotated.
    const p = hudPoint(e.clientX, e.clientY);
    const { offsetLeft: l, offsetTop: t, offsetWidth: w, offsetHeight: h } = this.el;
    const raw = w > h ? (p.x - l) / w : (t + h - p.y) / h;
    this.set(pedalCurve(clamp01(raw)));
  }

  set(v) {
    if (v === this.value) return;
    this.value = v;
    this.el.style.setProperty("--v", v);
    this.valueText.textContent = Math.round(v * 100);
    this.onChange?.(v);
  }

  updateOrientation() {
    this.el.classList.toggle("horizontal", this.el.offsetWidth > this.el.offsetHeight);
  }

  release() {
    this.pointerId = null;
    this.el.classList.remove("active");
    this.set(0);
  }
}

// A button. `pressed` is what gets sent; how it follows the finger depends on `mode`:
//   hold    pressed while the finger is down
//   toggle  each tap flips it on / off (shown with .latched)
//   tap     a 100 ms press, however long the finger stays
//   repeat  rapid fire: on/off at `rate` presses per second while held
const TAP_MS = 100;

export class HoldButton {
  constructor(el, onPress, onRelease) {
    this.el = el;
    this.mode = "hold";
    this.rate = 8;
    this.onPress = onPress;      // haptic hooks
    this.onRelease = onRelease;
    this.pressed = false;
    this.pointerId = null;
    this._timer = null;

    el.addEventListener("pointerdown", (e) => {
      if (isEditing() || this.pointerId !== null) return;
      e.preventDefault();
      this.pointerId = e.pointerId;
      el.setPointerCapture(e.pointerId);
      el.classList.add("active");
      this._down();
      this.onPress?.();
    });
    const up = (e) => {
      if (e.pointerId !== this.pointerId) return;
      this.pointerId = null;
      el.classList.remove("active");
      if (this.mode === "hold" || this.mode === "repeat") this._set(false);
      clearInterval(this._timer);
      this.onRelease?.();
    };
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.addEventListener("lostpointercapture", up);
  }

  _down() {
    clearTimeout(this._timer);
    clearInterval(this._timer);
    if (this.mode === "toggle") {
      this._set(!this.pressed);
    } else if (this.mode === "tap") {
      this._set(true);
      this._timer = setTimeout(() => this._set(false), TAP_MS);
    } else if (this.mode === "repeat") {
      this._set(true);
      // Half the period pressed, half released, so the game sees separate presses.
      this._timer = setInterval(() => this._set(!this.pressed), 500 / this.rate);
    } else {
      this._set(true);
    }
  }

  _set(on) {
    this.pressed = on;
    this.el.classList.toggle("latched", on && this.mode === "toggle");
  }

  // Lets go of everything, toggles included (settings opened, page hidden, rebinds).
  release() {
    clearTimeout(this._timer);
    clearInterval(this._timer);
    this.pointerId = null;
    this.el.classList.remove("active");
    this._set(false);
  }
}

// Shared pointer handling for analog controls: one finger owns the control while it's
// down (captured, so sliding off keeps control), and it springs back on release unless
// opts.spring is off. opts: spring, deadzone, invert (Y for joysticks), sensitivity.
class AnalogControl {
  constructor(el) {
    this.el = el;
    this.value = null;  // null while untouched, so the PC leaves that axis alone
    this.pointerId = null;
    this.opts = {};
    this.onPress = null;  // haptic hooks
    this.onEdge = null;
    this.onCenter = null;
    el.addEventListener("pointerdown", (e) => {
      if (isEditing() || this.pointerId !== null) return;
      e.preventDefault();
      this.pointerId = e.pointerId;
      el.setPointerCapture(e.pointerId);
      el.classList.add("active");
      this.onPress?.();
      this._track(e);
    });
    el.addEventListener("pointermove", (e) => {
      if (e.pointerId === this.pointerId) this._track(e);
    });
    const end = (e) => {
      if (e.pointerId !== this.pointerId) return;
      if (this.opts.spring === false) {  // stay where the finger left it
        this.pointerId = null;
        el.classList.remove("active");
      } else {
        this.release();
      }
    };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
    el.addEventListener("lostpointercapture", end);
  }

  release() {
    this.pointerId = null;
    this.value = null;
    this.el.classList.remove("active");
    this._show(null);
  }
}

// Two-axis thumbstick: [x, y] in -1..1 (y up), within a circle.
export class Joystick extends AnalogControl {
  constructor(el) {
    super(el);
    this.knob = el.querySelector(".stick-knob");
  }

  _track(e) {
    const p = hudPoint(e.clientX, e.clientY);
    const { offsetLeft: l, offsetTop: t, offsetWidth: w, offsetHeight: h } = this.el;
    const radius = Math.min(w, h) * 0.32;
    const reach = radius / (this.opts.sensitivity ?? 1);  // finger travel for full deflection
    let x = (p.x - (l + w / 2)) / reach;
    let y = -(p.y - (t + h / 2)) / reach;
    const mag = Math.hypot(x, y);
    if (mag > 1) [x, y] = [x / mag, y / mag];
    const atEdge = mag >= 0.98;
    if (atEdge && !this._atEdge) this.onEdge?.();
    this._atEdge = atEdge;
    // Dead zone so a resting thumb is still.
    const sendY = this.opts.invert ? -y : y;
    this.value = mag < (this.opts.deadzone ?? 0.08) ? [0, 0] : [x, sendY];
    this._show([x, y], radius);
  }

  _show(v, radius = 0) {
    this.knob.style.transform = v ? `translate(${v[0] * radius}px, ${-v[1] * radius}px)` : "";
  }
}

// One-axis slider. Centered (-1..1, springs to the middle) for stick axes, or 0..1 from
// the start for triggers. Horizontal or vertical, whichever way it's laid out.
export class AxisSlider extends AnalogControl {
  constructor(el, centered) {
    super(el);
    this.centered = centered;
    this._show(null);
  }

  _track(e) {
    const p = hudPoint(e.clientX, e.clientY);
    const { offsetLeft: l, offsetTop: t, offsetWidth: w, offsetHeight: h } = this.el;
    const raw = clamp01(w > h ? (p.x - l) / w : (t + h - p.y) / h);
    if (this.centered) {
      const v = raw * 2 - 1;
      const side = Math.sign(v);
      if (this._side != null && side && side !== this._side) this.onCenter?.();  // crossed the middle
      if (side) this._side = side;
      const out = Math.abs(v) < (this.opts.deadzone ?? 0.06) ? 0 : v;
      this.value = this.opts.invert ? -out : out;
    } else {
      const out = pedalCurve(raw);
      this.value = this.opts.invert ? 1 - out : out;
    }
    this._show(raw);
  }

  _show(raw) {
    if (raw == null) this._side = null;
    this.el.classList.toggle("horizontal", this.el.offsetWidth > this.el.offsetHeight);
    this.el.style.setProperty("--p", raw ?? (this.centered ? 0.5 : 0));
  }
}
