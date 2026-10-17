// Dashboard: gear, RPM bar with shift light, speed, fuel / temperature / boost, warning
// lights, lap times, steering meter, connection status.

const SHIFT_AT = 0.92;  // fraction of max RPM where the shift light starts flashing
// F1-style rev lights: 5 green, 5 red, 5 blue bulbs filling between LED_START and SHIFT_AT.
const LED_COLORS = ["g", "g", "g", "g", "g", "r", "r", "r", "r", "r", "b", "b", "b", "b", "b"];
const LED_START = 0.55;

// m:ss.mmm, or a placeholder when there's no time yet.
export function lapTime(ms) {
  if (ms == null) return "-:--.---";
  const m = Math.floor(ms / 60000), s = Math.floor(ms / 1000) % 60, rest = ms % 1000;
  return `${m}:${String(s).padStart(2, "0")}.${String(rest).padStart(3, "0")}`;
}

function show(el, visible, update) {
  el.hidden = !visible;
  if (visible) update();
}

export function gearLabel(gear) {
  if (gear <= 0) return "R";
  if (gear === 1) return "N";
  return String(gear - 1);
}

export class Dash {
  constructor(root, settings) {
    this.root = root;
    this.settings = settings;
    this.gear = root.querySelector("#gear");
    this.speed = root.querySelector("#speed");
    this.rpmText = root.querySelector("#rpm-text");
    this.revs = document.querySelector(".revs");  // separate HUD element
    this.rpmBar = this.revs.querySelector(".rpm");
    this.needle = root.querySelector("#steer-needle");
    this.dot = root.querySelector("#conn-dot");
    this.connText = root.querySelector("#conn-text");
    this.badge = root.querySelector("#src-badge");
    this.fuelInfo = root.querySelector("#fuel-info");
    this.tempInfo = root.querySelector("#temp-info");
    this.boostInfo = root.querySelector("#boost-info");
    this.lightsRow = root.querySelector("#lights");
    this.lights = new Map([...root.querySelectorAll("[data-light]")].map((el) => [el.dataset.light, el]));
    this.lapRow = root.querySelector("#lap");
    this.revLeds = this.revs.querySelector(".rev-leds");
    this.bulbs = LED_COLORS.map((color) => {
      const bulb = document.createElement("i");
      bulb.className = color;
      return bulb;
    });
    this.revLeds.replaceChildren(...this.bulbs);
  }

  // Settings > Rev lights: "leds" (F1 bulbs), "bar", or "both".
  _revLights(ratio, shift) {
    const style = this.settings.revStyle;
    const leds = style !== "bar";
    this.rpmBar.hidden = style === "leds";
    this.revLeds.hidden = !leds;
    this.revs.classList.toggle("both", style === "both");
    if (!leds) return;
    const n = this.bulbs.length;
    const lit = shift ? n
      : Math.max(0, Math.min(n, Math.ceil((ratio - LED_START) / (SHIFT_AT - LED_START) * n)));
    this.bulbs.forEach((bulb, i) => bulb.classList.toggle("on", i < lit));
  }

  // Fuel %, engine temperature, boost, warning lights and lap info: each part is hidden
  // when the game doesn't report it (e.g. no lap times from BeamNG, no engine temp from AC).
  _extras(t) {
    show(this.fuelInfo, t.f != null, () => {
      this.fuelInfo.querySelector("#fuel").textContent = Math.round(t.f * 100);
      this.fuelInfo.style.setProperty("--f", t.f.toFixed(3));
      this.fuelInfo.classList.toggle("low", t.f < 0.1);
    });
    show(this.tempInfo, t.et != null, () => (this.tempInfo.querySelector("#temp").textContent = Math.round(t.et)));
    show(this.boostInfo, t.bo != null, () => (this.boostInfo.querySelector("#boost").textContent = t.bo.toFixed(1)));

    const lights = t.li || {};
    show(this.lightsRow, Object.keys(lights).length > 0, () => {
      for (const [name, el] of this.lights) {
        el.classList.toggle("has", name in lights);
        el.classList.toggle("on", !!lights[name]);
      }
    });

    show(this.lapRow, t.lp != null, () => {
      const lp = t.lp, q = (sel) => this.lapRow.querySelector(sel);
      q("#lap-pos").textContent = lp.p ? `P${lp.p}` : "";
      q("#lap-no").textContent = lp.n ? `Lap ${lp.n}` : "";
      q("#lap-cur").textContent = lapTime(lp.c);
      q("#lap-last").textContent = lapTime(lp.l);
      q("#lap-best").textContent = lapTime(lp.b);
    });
  }

  // The gear as the car's own dash shows it when the game says (BeamNG mod: P, R, N, D3,
  // S2, M4); otherwise from the number, with "D" + the actual gear for automatics.
  _gear(t) {
    const mode = this.settings.gearD;
    let big = gearLabel(t.g), small = null;
    if (t.gl && !(mode === "off" && /^[DSM]$/.test(t.gl))) {
      [big, small] = [t.gl, t.gs];
    } else if (t.g >= 2 && (mode === "on" || (mode === "auto" && t.au === true))) {
      [big, small] = ["D", String(t.g - 1)];
    }
    if (small) {
      const el = document.createElement("small");
      el.textContent = small;
      this.gear.replaceChildren(big, el);
    } else {
      this.gear.textContent = big;
    }
  }

  telemetry(t) {
    const ratio = t.m > 0 ? Math.min(1, t.r / t.m) : 0;
    const shift = t.sl || ratio >= SHIFT_AT;
    this.rpmBar.style.setProperty("--r", ratio.toFixed(3));
    this.root.classList.toggle("redline", shift);
    this.revs.classList.toggle("redline", shift);
    this._revLights(ratio, shift);
    this._gear(t);
    this.rpmText.textContent = t.r;
    this.speed.textContent = t.v == null ? "--" : Math.round(t.v);
    const live = t.src !== "est";
    this.badge.textContent = live ? (t.src === "beamng" ? "BEAMNG" : "AC") : "EST";
    this.badge.classList.toggle("live", live);
    this._extras(t);
  }

  steering(value, locked) {
    this.needle.style.setProperty("--s", value.toFixed(3));
    this.root.classList.toggle("steer-locked", locked);
  }

  connection(state, latencyMs) {
    this.dot.className = "dot " + (state === "open" ? "ok" : state === "closed" ? "bad" : "");
    this.connText.textContent =
      state === "open" ? (latencyMs == null ? "connected" : `${Math.round(latencyMs)} ms`) :
      state === "closed" ? "disconnected" : "connecting";
  }
}
