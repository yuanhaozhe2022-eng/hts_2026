// Movable / resizable HUD layout. Boxes are fractions of the HUD so a layout
// carries over between screen sizes. Saved per phone in localStorage.

import { hudPoint } from "./orientation.js";

const KEY = "phonewheel.layout.v1";
const MIN_SIZE = 0.05;

// Landscape defaults: pedals along the edges under the thumbs, shift buttons just
// inside them, dashboard in the middle.
export const DEFAULT_LAYOUT = {
  brake:       { x: 0.015, y: 0.18, w: 0.13, h: 0.78 },
  throttle:    { x: 0.855, y: 0.18, w: 0.13, h: 0.78 },
  shiftDown:   { x: 0.165, y: 0.50, w: 0.13, h: 0.30 },
  shiftUp:     { x: 0.705, y: 0.50, w: 0.13, h: 0.30 },
  dash:        { x: 0.30,  y: 0.03, w: 0.40, h: 0.76 },
  settingsBtn: { x: 0.475, y: 0.84, w: 0.05, h: 0.10 },
};

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

export class Layout {
  constructor(hud, onChange) {
    this.hud = hud;
    this.onChange = onChange;
    this.elements = new Map([...hud.querySelectorAll("[data-el]")].map((el) => [el.dataset.el, el]));
    this.boxes = this._load();
    this.editing = false;

    for (const [name, el] of this.elements) {
      const handle = document.createElement("div");
      handle.className = "handle";
      el.appendChild(handle);
      this._makeEditable(name, el, handle);
    }
    this.apply();
  }

  _load() {
    let saved = {};
    try {
      saved = JSON.parse(localStorage.getItem(KEY) || "{}");
    } catch {}
    const boxes = {};
    for (const name of Object.keys(DEFAULT_LAYOUT)) boxes[name] = { ...DEFAULT_LAYOUT[name], ...saved[name] };
    return boxes;
  }

  save() {
    try {
      localStorage.setItem(KEY, JSON.stringify(this.boxes));
    } catch {}
  }

  reset() {
    for (const name of Object.keys(DEFAULT_LAYOUT)) this.boxes[name] = { ...DEFAULT_LAYOUT[name] };
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
    this.onChange?.();
  }

  setEditing(on) {
    this.editing = on;
    document.body.classList.toggle("editing", on);
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
      this.boxes[name] = b;
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
