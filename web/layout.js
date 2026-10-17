// Movable / resizable HUD layout. Boxes are fractions of the HUD so a layout
// carries over between screen sizes. Saved per phone in localStorage.

import { hudPoint } from "./orientation.js";

const KEY = "pocketwheel.layout.v1";
const OLD_KEY = "phonewheel.layout.v1";  // before the rename; read once so nothing is lost
const MIN_SIZE = 0.05;

// Landscape defaults: pedals along the edges under the thumbs, shift buttons just
// inside them, rev lights and dashboard in the middle.
export const DEFAULT_LAYOUT = {
  brake:       { x: 0.015, y: 0.18, w: 0.13, h: 0.78 },
  throttle:    { x: 0.855, y: 0.18, w: 0.13, h: 0.78 },
  shiftDown:   { x: 0.165, y: 0.50, w: 0.13, h: 0.30 },
  shiftUp:     { x: 0.705, y: 0.50, w: 0.13, h: 0.30 },
  revs:        { x: 0.30,  y: 0.03, w: 0.40, h: 0.10 },
  dash:        { x: 0.30,  y: 0.14, w: 0.40, h: 0.65 },
  settingsBtn: { x: 0.475, y: 0.84, w: 0.05, h: 0.10 },
};

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

// The settings button can never be covered: nothing may be dragged or resized into this
// margin around it (and it can't be dragged onto anything), so it always stays tappable.
const SETTINGS = "settingsBtn";
const KEEP_OUT = { x: 0.02, y: 0.04 };
const overlaps = (a, b) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const padded = (b) => ({ x: b.x - KEEP_OUT.x, y: b.y - KEEP_OUT.y,
                         w: b.w + 2 * KEEP_OUT.x, h: b.h + 2 * KEEP_OUT.y });

export class Layout {
  constructor(hud, onChange) {
    this.hud = hud;
    this.onChange = onChange;
    this.elements = new Map();
    this.defaults = { ...DEFAULT_LAYOUT };  // grows with custom buttons
    this.saved = this._load();
    // Layouts saved before the rev lights were split out of the dash: give them the dash's
    // top strip, where they used to be, so nothing overlaps.
    const d = this.saved.dash;
    if (d && !this.saved.revs) {
      this.saved.revs = { x: d.x, y: d.y, w: d.w, h: d.h * 0.13 };
      this.saved.dash = { ...d, y: d.y + d.h * 0.15, h: d.h * 0.85 };
    }
    this.boxes = {};
    this.editing = false;
    // Shows the keep-out zone around the settings button while editing.
    this.keepOut = document.createElement("div");
    this.keepOut.className = "keep-out";
    hud.appendChild(this.keepOut);
    for (const el of hud.querySelectorAll("[data-el]")) this._register(el.dataset.el, el);
    this.apply();
  }

  _load() {
    try {
      return JSON.parse(localStorage.getItem(KEY) || localStorage.getItem(OLD_KEY) || "{}");
    } catch {
      return {};
    }
  }

  _register(name, el) {
    this.elements.set(name, el);
    this.boxes[name] = { ...this.defaults[name], ...this.saved[name] };
    const handle = document.createElement("div");
    handle.className = "handle";
    el.appendChild(handle);
    this._makeEditable(name, el, handle);
  }

  // Elements created later (custom buttons). Their position is remembered by name.
  add(name, el, defaultBox) {
    this.defaults[name] = defaultBox;
    this._register(name, el);
    this.apply();
  }

  remove(name) {
    this.elements.get(name)?.remove();
    this.elements.delete(name);
    delete this.boxes[name];
    delete this.defaults[name];
    delete this.saved[name];
    this.save();
  }

  // Merged into what was stored, so positions of custom buttons that haven't been
  // created yet (they arrive from the PC after connecting) aren't lost.
  save() {
    this.saved = { ...this.saved, ...this.boxes };
    try {
      localStorage.setItem(KEY, JSON.stringify(this.saved));
    } catch {}
  }

  reset() {
    for (const name of this.elements.keys()) this.boxes[name] = { ...this.defaults[name] };
    this.save();
    this.apply();
  }

  apply() {
    for (const [name, el] of this.elements) {
      const b = this.boxes[name];
      if (!b) continue;
      el.style.left = `${b.x * 100}%`;
      el.style.top = `${b.y * 100}%`;
      el.style.width = `${b.w * 100}%`;
      el.style.height = `${b.h * 100}%`;
    }
    const z = this.boxes[SETTINGS] && padded(this.boxes[SETTINGS]);
    if (z) {
      Object.assign(this.keepOut.style, {
        left: `${z.x * 100}%`, top: `${z.y * 100}%`, width: `${z.w * 100}%`, height: `${z.h * 100}%` });
    }
    this.onChange?.();
  }

  setEditing(on) {
    this.editing = on;
    document.body.classList.toggle("editing", on);
  }

  // Would this box for `name` cover the settings button (or, for the button, cover anything)?
  _blocked(name, box) {
    if (name === SETTINGS) {
      const zone = padded(box);
      return [...this.elements.keys()].some((n) => n !== SETTINGS && overlaps(zone, this.boxes[n]));
    }
    return overlaps(box, padded(this.boxes[SETTINGS]));
  }

  _makeEditable(name, el, handle) {
    let drag = null;

    el.addEventListener("pointerdown", (e) => {
      if (!this.editing || drag) return;
      e.preventDefault();
      e.stopPropagation();
      el.setPointerCapture(e.pointerId);
      drag = {
        id: e.pointerId,
        mode: e.target === handle ? "resize" : "move",
        start: hudPoint(e.clientX, e.clientY),
        box: { ...this.boxes[name] },
      };
    });

    el.addEventListener("pointermove", (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      // HUD coordinates and size, so dragging follows the finger when the HUD is rotated.
      const p = hudPoint(e.clientX, e.clientY);
      const dx = (p.x - drag.start.x) / this.hud.offsetWidth;
      const dy = (p.y - drag.start.y) / this.hud.offsetHeight;
      const b = { ...drag.box };
      if (drag.mode === "move") {
        b.x = clamp(b.x + dx, 0, 1 - b.w);
        b.y = clamp(b.y + dy, 0, 1 - b.h);
      } else {
        b.w = clamp(b.w + dx, MIN_SIZE, 1 - b.x);
        b.h = clamp(b.h + dy, MIN_SIZE, 1 - b.y);
      }
      // Into the keep-out zone: slide along its edge (keep whichever axis is still allowed)
      // or stay put.
      const now = this.boxes[name];
      const tries = drag.mode === "move"
        ? [b, { ...b, y: now.y }, { ...b, x: now.x }]
        : [b, { ...b, h: now.h }, { ...b, w: now.w }];
      const ok = tries.find((t) => !this._blocked(name, t));
      if (!ok) return;
      this.boxes[name] = ok;
      this.apply();
    });

    const end = (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      drag = null;
      this.save();
    };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
  }
}
