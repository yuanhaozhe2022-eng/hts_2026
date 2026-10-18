// EXPERIMENTAL: shift by tapping the back of the phone.
//
// A tap on the back jolts the phone along the screen axis (z) far more sharply than any
// steering movement, so a high-passed accelerometer spike marks it. Which end was tapped
// shows in the gyro: that end kicks forward, a quick twist around the phone's short axis
// (rotationRate.beta in landscape) whose sign depends on the side.
// Phones and browsers disagree on the signs, so learn() records a few taps on each side once.
// Taps on the screen jolt the phone the other way and are also ignored for a moment after
// any touch, so pedal and button presses don't count.

const WINDOW_MS = 70;        // collect the twist for this long after the jolt
const REFRACTORY_MS = 180;   // one tap, one shift (a double tap is ~150-250 ms apart)
const TOUCH_QUIET_MS = 150;  // ignore jolts right after a screen touch
const DOUBLE_MS = 380;       // second tap within this = double tap
const LEARN_TAPS = 3;

const highPass = () => {
  let low = null;
  return (x) => {
    if (low == null) low = x;
    low += (x - low) * 0.12;
    return x - low;
  };
};

export class BackTap {
  // settings.backTap: "off" | "sides" | "double"; backTapSensitivity 0..1; backTapCal
  // onTap("left" | "right" | "single" | "double")
  constructor(settings, onTap) {
    this.settings = settings;
    this.onTap = onTap;
    this.enabled = () => true;   // set by the app: false while settings are open, etc.
    this._z = highPass();
    this._beta = highPass();
    this._event = null;          // jolt being measured
    this._lastTap = 0;
    this._lastTouch = 0;
    this._pendingSingle = null;
    this._learn = null;          // { side, taps: {left: [], right: []}, onStep }
    this.onMotion = this.onMotion.bind(this);
    window.addEventListener("devicemotion", this.onMotion);
    const touched = () => (this._lastTouch = performance.now());
    document.addEventListener("pointerdown", touched, true);
    document.addEventListener("pointerup", touched, true);
  }

  get threshold() {  // m/s², lower = more sensitive
    return 7 - 5.5 * (this.settings.backTapSensitivity ?? 0.5);
  }

  onMotion(e) {
    const now = performance.now();
    const acc = e.acceleration ?? e.accelerationIncludingGravity;
    const z = this._z(acc?.z ?? 0);
    const beta = this._beta(e.rotationRate?.beta ?? 0);
    const listening = this._learn || (this.settings.backTap !== "off" && this.enabled());
    if (!listening) return;

    if (this._event) {
      if (Math.abs(beta) > Math.abs(this._event.beta)) this._event.beta = beta;
      if (now - this._event.t >= WINDOW_MS) {
        const event = this._event;
        this._event = null;
        this._finish(event);
      }
      return;
    }
    if (Math.abs(z) < this.threshold || now - this._lastTap < REFRACTORY_MS ||
        now - this._lastTouch < TOUCH_QUIET_MS) return;
    this._lastTap = now;
    // The leading edge of the jolt says which way the phone was pushed.
    this._event = { t: now, z: Math.sign(z), beta };
  }

  _finish(event) {
    if (this._learn) return this._learnTap(event);
    const cal = this.settings.backTapCal;
    if (cal && event.z !== cal.zSign) return;  // pushed away: a touch on the screen
    if (this.settings.backTap === "double") return this._singleOrDouble();
    if (!cal?.separable) return;
    if (Math.abs(event.beta) < cal.minBeta) return;  // no clear twist: can't tell the side
    this.onTap(Math.sign(event.beta) === cal.leftSign ? "left" : "right");
  }

  _singleOrDouble() {
    if (this._pendingSingle) {
      clearTimeout(this._pendingSingle);
      this._pendingSingle = null;
      this.onTap("double");
    } else {
      this._pendingSingle = setTimeout(() => {
        this._pendingSingle = null;
        this.onTap("single");
      }, DOUBLE_MS);
    }
  }

  // Record LEARN_TAPS taps on the left, then on the right. onStep(text, done) reports progress.
  learn(onStep) {
    this._learn = { side: "left", taps: { left: [], right: [] }, onStep };
    onStep(`Tap the back on the LEFT side ${LEARN_TAPS} times.`, false);
  }

  cancelLearning() {
    this._learn = null;
  }

  _learnTap(event) {
    const l = this._learn;
    l.taps[l.side].push(event);
    const n = l.taps[l.side].length;
    if (l.side === "left" && n >= LEARN_TAPS) {
      l.side = "right";
      l.onStep(`Good. Now tap the RIGHT side ${LEARN_TAPS} times.`, false);
    } else if (l.side === "right" && n >= LEARN_TAPS) {
      this._learn = null;
      l.onStep(...this._calibrate(l.taps), true);
    } else {
      l.onStep(`${l.side === "left" ? "LEFT" : "RIGHT"} side: ${n} of ${LEARN_TAPS}…`, false);
    }
  }

  _calibrate({ left, right }) {
    const all = [...left, ...right];
    const zSign = Math.sign(all.reduce((s, e) => s + e.z, 0)) || 1;
    const mean = (taps) => taps.reduce((s, e) => s + e.beta, 0) / taps.length;
    const l = mean(left), r = mean(right);
    // Separable when every left twist has one sign and every right twist the other.
    const consistent = (taps, sign) => taps.every((e) => Math.sign(e.beta) === sign);
    const separable = Math.sign(l) !== 0 && Math.sign(l) === -Math.sign(r) &&
      consistent(left, Math.sign(l)) && consistent(right, Math.sign(r));
    const minBeta = 0.3 * Math.min(Math.abs(l), Math.abs(r));
    this.settings.backTapCal = { zSign, leftSign: Math.sign(l) || 1, separable, minBeta };
    return [separable
      ? "Learned ✓ Left side = shift down, right side = shift up."
      : "Learned the tap, but this phone can't tell left from right reliably. " +
        "Use \"Tap = up, double tap = down\" instead."];
  }
}
