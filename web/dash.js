// Dashboard: gear, RPM bar with shift light, speed, fuel / temperature / boost, warning
// lights, lap times, steering meter, connection status.

const SHIFT_AT = 0.92;  // fraction of max RPM where the shift light starts flashing

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
  constructor(root) {
    this.root = root;
    this.gear = root.querySelector("#gear");
    this.speed = root.querySelector("#speed");
    this.rpmText = root.querySelector("#rpm-text");
    this.rpmBar = root.querySelector(".rpm");
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

  telemetry(t) {
    const ratio = t.m > 0 ? Math.min(1, t.r / t.m) : 0;
    this.rpmBar.style.setProperty("--r", ratio.toFixed(3));
    this.root.classList.toggle("redline", t.sl || ratio >= SHIFT_AT);
    this.gear.textContent = gearLabel(t.g);
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
