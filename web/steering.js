// Steering from the phone's motion sensors.
//
// The phone is held sideways like a wheel, so steering is rotation about the axis
// pointing out of the screen (device z). Two estimates of that angle are fused:
//   - gravity (accelerationIncludingGravity): absolute, but noisy and disturbed by bumps
//   - gyro (rotationRate): smooth and instant, but drifts when integrated
// A complementary filter takes the gyro's short-term motion and the gravity's long-term
// level, then an adaptive (One Euro) filter removes jitter without adding lag in turns.

const GYRO_WEIGHT = 0.98;    // per ~16 ms sample; the gravity correction has a ~0.8 s time constant
const MIN_GRAVITY = 3;       // m/s²: phone lying flat -> no usable roll from gravity, trust the gyro
const MAX_DT = 0.1;          // s: ignore gaps (tab switch) when integrating the gyro
export const FULL_LOCK_DEG = 50;  // tilt (each way) for full lock at sensitivity ×1

const RAD = 180 / Math.PI;
const AXES = ["alpha", "beta", "gamma"];
const wrap = (deg) => ((deg + 540) % 360) - 180;   // -> [-180, 180)
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

// Screen rotation in degrees (0, 90, 180, 270). iOS < 16.4 only has window.orientation.
function screenAngle() {
  if (screen.orientation && typeof screen.orientation.angle === "number") return screen.orientation.angle;
  return (window.orientation || 0) + 0;
}

// The landscape rotation we steer relative to (90 or -90). It only follows landscape
// changes: iOS can't lock orientation and may flip to portrait on a hard turn, and the
// straight-ahead reference must not jump when that happens.
let landscape = 90;
let reference = null;

// While the page draws its own sideways HUD on a portrait screen, the screen angle says
// nothing about how the phone is held; the HUD's rotation (90 / -90) is used instead.
export function setSteeringReference(angle) {
  reference = angle;
}

function landscapeAngle() {
  if (reference != null) return reference;
  const a = wrap(screenAngle());
  if (a === 90 || a === -90) landscape = a;
  return landscape;
}

// Map a wheel angle (degrees, + = right) to the stick value in [-1, 1].
export function shapeSteering(deg, { sensitivity, deadzone, curve, invert }) {
  let v = clamp(deg * sensitivity / FULL_LOCK_DEG, -1, 1);
  const mag = Math.abs(v);
  v = mag <= deadzone ? 0 : Math.sign(v) * Math.pow((mag - deadzone) / (1 - deadzone), curve);
  return invert ? -v : v;
}

// One Euro filter (Casiez et al. 2012) for an angle: a low cutoff while the phone is
// still (no jitter) that rises with turning speed (no lag in a quick turn).
class OneEuro {
  constructor() {
    this.reset();
  }

  reset() {
    this.x = null;
    this.dx = 0;
  }

  filter(x, dt, minCutoff, beta) {
    if (this.x == null || dt <= 0) return (this.x = x);
    const smoothing = (cutoff) => 1 / (1 + 1 / (2 * Math.PI * cutoff * dt));
    this.dx += smoothing(1) * (wrap(x - this.x) / dt - this.dx);
    const cutoff = minCutoff + beta * Math.abs(this.dx);
    return (this.x = wrap(this.x + smoothing(cutoff) * wrap(x - this.x)));
  }
}

// Browsers disagree about the gyro: which rotationRate field is the turn about the screen,
// its sign, and deg/s versus rad/s. Trusting a wrong guess makes the steering trail your
// hands (only the slow gravity correction moves it). So each field is matched against how
// the gravity angle really changes over short windows, and the gyro is only used once one
// field clearly tracks it.
class GyroMatch {
  constructor() {
    this.reset();
  }

  reset() {
    this.sxy = { alpha: 0, beta: 0, gamma: 0 };
    this.sxx = { alpha: 0, beta: 0, gamma: 0 };
    this.syy = 0;
    this.windows = 0;
    this.axis = null;   // matched rotationRate field, or null: gravity only
    this.gain = 0;      // multiplies that field to get deg/s about the screen (±1 or ±57.3)
    this.fit = 0;       // correlation of the match, for the settings readout
  }

  // gyroTurn: integrated rotationRate per field over the window; gravityTurn: degrees.
  add(gyroTurn, gravityTurn) {
    const keep = 0.97;  // ~30 windows (a few seconds of steering) of memory
    for (const a of AXES) {
      this.sxy[a] = this.sxy[a] * keep + gyroTurn[a] * gravityTurn;
      this.sxx[a] = this.sxx[a] * keep + gyroTurn[a] * gyroTurn[a];
    }
    this.syy = this.syy * keep + gravityTurn * gravityTurn;
    if (++this.windows >= 8) this._decide();
  }

  _decide() {
    let best = null, r = 0;
    for (const a of AXES) {
      const ra = this.sxy[a] / Math.sqrt(this.sxx[a] * this.syy || Infinity);
      if (Math.abs(ra) > Math.abs(r)) [best, r] = [a, ra];
    }
    if (Math.abs(r) < 0.7) return;  // nothing clearly fits (yet): keep the current choice
    const gain = this.sxy[best] / this.sxx[best];
    const unit = Math.abs(gain) > 0.5 && Math.abs(gain) < 2 ? 1        // deg/s, as specified
      : Math.abs(gain) > 25 && Math.abs(gain) < 115 ? RAD : null;          // rad/s
    if (unit == null) return;
    this.axis = best;
    this.gain = Math.sign(gain) * unit;
    this.fit = Math.abs(r);
  }
}

const GYRO_WINDOW_S = 0.1;
const MIN_WINDOW_TURN = 2;  // degrees: windows with less motion are mostly noise

export class Steering {
  constructor(settings) {
    this.settings = settings;
    this.angle = null;       // filtered roll of the device about z, degrees, CCW positive
    this.gravitySign = 1;    // -1 on platforms that report gravity flipped
    this.gyro = new GyroMatch();
    this._smooth = new OneEuro();
    this._fused = null;
    this._window = null;
    this._lastT = null;
    this.onMotion = this.onMotion.bind(this);
  }

  start() {
    window.addEventListener("devicemotion", this.onMotion);
  }

  // Forget the current estimate, e.g. after the gravity convention changed.
  reset() {
    this.angle = null;
    this._fused = null;
    this._window = null;
    this._smooth.reset();
    this.gyro.reset();
  }

  // Short description of what drives the steering, for the settings panel.
  sensorInfo() {
    if (this.angle == null) return "no motion data yet";
    if (!this.gyro.axis) return "gravity only (steer left and right a few times to bring in the gyro)";
    return `gyro + gravity (match ${Math.round(this.gyro.fit * 100)}%)`;
  }

  // Raw roll from gravity, or null if the phone is too flat to tell.
  _gravityRoll(e) {
    const g = e.accelerationIncludingGravity;
    if (!g || g.x == null || g.y == null) return null;
    const x = g.x * this.gravitySign, y = g.y * this.gravitySign;
    if (Math.hypot(x, y) < MIN_GRAVITY) return null;
    return Math.atan2(x, y) * RAD;
  }

  // Per spec the reading points "up", so in landscape x should have the sign of the screen
  // rotation; some browsers report it the other way round. Returns true once decided.
  detectGravitySign(e) {
    const g = e.accelerationIncludingGravity;
    const rot = wrap(screenAngle());
    if (!g || g.x == null || Math.abs(g.x) < 5 || (rot !== 90 && rot !== -90)) return false;
    const expected = rot === 90 ? 1 : -1;
    const sign = Math.sign(g.x) === expected ? 1 : -1;
    if (sign !== this.gravitySign) {
      this.gravitySign = sign;
      this.reset();  // re-seed from corrected gravity
    }
    return true;
  }

  onMotion(e) {
    const now = performance.now() / 1000;
    const dt = this._lastT == null ? 0 : Math.min(now - this._lastT, MAX_DT);
    this._lastT = now;

    const accel = this._gravityRoll(e);
    const rr = e.rotationRate;
    const rate = rr ? { alpha: rr.alpha || 0, beta: rr.beta || 0, gamma: rr.gamma || 0 } : null;

    if (this._fused == null) {
      if (accel == null) return;
      this._fused = this.angle = accel;
      return;
    }

    if (rate && dt > 0) this._learnGyro(rate, accel, dt);

    const gyroRate = rate && this.gyro.axis ? this.gyro.gain * rate[this.gyro.axis] : null;
    if (gyroRate != null && dt > 0) {
      const predicted = this._fused + gyroRate * dt;
      this._fused = accel == null ? wrap(predicted)
        : wrap(predicted + (1 - GYRO_WEIGHT) * wrap(accel - predicted));
    } else if (accel != null) {
      this._fused = accel;  // gravity only: the One Euro filter below does the smoothing
    }

    // Smoothing setting 0..1 -> resting cutoff ~6.4 Hz (snappy) .. 0.4 Hz (very smooth).
    const s = clamp(this.settings.smoothing, 0, 1);
    this.angle = this._smooth.filter(this._fused, dt, 0.4 + 6 * (1 - s) ** 2, 0.05);
  }

  _learnGyro(rate, accel, dt) {
    if (accel == null) {
      this._window = null;
      return;
    }
    const w = this._window;
    if (!w) {
      this._window = { start: accel, t: 0, turn: { alpha: 0, beta: 0, gamma: 0 } };
      return;
    }
    for (const a of AXES) w.turn[a] += rate[a] * dt;
    w.t += dt;
    if (w.t < GYRO_WINDOW_S) return;
    const gravityTurn = wrap(accel - w.start);
    const gyroMoved = Math.max(...AXES.map((a) => Math.abs(w.turn[a])));
    if (Math.abs(gravityTurn) > MIN_WINDOW_TURN || gyroMoved > MIN_WINDOW_TURN) {
      this.gyro.add(w.turn, gravityTurn);
    }
    this._window = { start: accel, t: 0, turn: { alpha: 0, beta: 0, gamma: 0 } };
  }

  // Wheel angle in degrees relative to straight ahead, + = turning right.
  wheelAngle() {
    if (this.angle == null) return 0;
    // Level in landscape reads as the screen rotation; turning right (clockwise as you
    // look at the screen) lowers the device roll.
    return -wrap(this.angle - landscapeAngle() - this.settings.center);
  }

  // Make the current pose straight ahead.
  calibrate() {
    if (this.angle == null) return;
    this.settings.center = wrap(this.angle - landscapeAngle());
  }

  value() {
    if (this.settings.lockSteering) return 0;
    return shapeSteering(this.wheelAngle(), this.settings);
  }
}
