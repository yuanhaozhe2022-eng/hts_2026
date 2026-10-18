// EXPERIMENTAL: thumb (or finger) taps on the phone, seen by the laptop's webcam.
//
// Holding the phone like a wheel in front of the laptop, the webcam sees the hands from the
// back: the thumbs resting along the phone's top long edge, and the fingers on its back.
// MediaPipe gives 21 joints per hand in 3D ("world" landmarks, centred on the hand and in
// metres, so turning the phone to steer doesn't change them). We track how bent the thumb
// (or each back finger) is; a tap is that bend quickly changing (it lifts off the phone) and
// coming back (it lands again).

const WRIST = 0;
// Thumb: base (CMC), knuckle (MCP), joint (IP), tip. Bend is measured at all three joints.
const THUMB = [WRIST, 1, 2, 3, 4];
// Back fingers: [knuckle (MCP), middle joint (PIP), fingertip] for index, middle, ring.
const FINGERS = [[5, 6, 8], [9, 10, 12], [13, 14, 16]];
export const TIPS = { thumb: [4], fingers: [8, 12, 16] };

const sub = (a, b) => [a.x - b.x, a.y - b.y, a.z - b.z];
function angle(u, v) {
  const dot = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  const len = Math.hypot(...u) * Math.hypot(...v);
  return len ? (Math.acos(Math.max(-1, Math.min(1, dot / len))) * 180) / Math.PI : 0;
}

// Degrees of bend per tracked digit. part: "thumb" (one value) or "fingers" (three).
export function bends(world, part = "thumb") {
  if (part === "thumb") {
    // Lifting the thumb off the edge swings it away from the palm (the index knuckle line)...
    let total = angle(sub(world[2], world[1]), sub(world[5], world[WRIST]));
    // ...and straightens or bends its joints.
    for (let i = 1; i < THUMB.length - 1; i++) {
      total += angle(sub(world[THUMB[i]], world[THUMB[i - 1]]), sub(world[THUMB[i + 1]], world[THUMB[i]]));
    }
    return [total];
  }
  return FINGERS.map(([mcp, pip, tip]) => {
    const palm = sub(world[mcp], world[WRIST]);
    const base = sub(world[pip], world[mcp]);
    const end = sub(world[tip], world[pip]);
    return angle(palm, base) + angle(base, end);
  });
}

// One hand. update() returns true on the frame a tap completes.
export class TapDetector {
  constructor() {
    this.threshold = 18;    // degrees of bend change that count as a lift
    this.minMs = 50;        // quicker than this is tracking noise
    this.maxMs = 700;       // slower than this is a change of grip, not a tap
    this.refractoryMs = 200;
    this.reset();
  }

  reset() {
    this.fingers = [];
    this.lastTap = -Infinity;
    this.level = 0;  // 0..1+, how close to a tap right now (for the on-screen meter)
  }

  update(bends, now) {
    let tapped = false;
    this.level = 0;
    bends.forEach((bend, i) => {
      const f = (this.fingers[i] ??= { rest: bend, liftedAt: null });
      const change = Math.abs(bend - f.rest);
      this.level = Math.max(this.level, change / this.threshold);
      if (f.liftedAt == null) {
        if (change > this.threshold) f.liftedAt = now;
        else f.rest += (bend - f.rest) * 0.1;  // follow the grip slowly
      } else if (change < this.threshold * 0.4) {  // back down: that's the tap
        const held = now - f.liftedAt;
        f.liftedAt = null;
        if (held >= this.minMs && held <= this.maxMs && now - this.lastTap > this.refractoryMs) {
          this.lastTap = now;
          tapped = true;
        }
      } else if (now - f.liftedAt > this.maxMs) {  // stayed moved: new resting grip
        f.liftedAt = null;
        f.rest = bend;
      }
    });
    return tapped;
  }
}

// Which of the driver's hands each detected hand is. The webcam faces the driver, so in its
// (unmirrored) picture their left hand is on the right. swap: for webcams that mirror.
export function handSides(wristXs, swap = false) {
  let sides;
  if (wristXs.length >= 2) {
    const rightmost = wristXs[0] > wristXs[1] ? 0 : 1;
    sides = wristXs.map((_, i) => (i === rightmost ? "left" : "right"));
  } else {
    sides = wristXs.map((x) => (x > 0.5 ? "left" : "right"));
  }
  return swap ? sides.map((s) => (s === "left" ? "right" : "left")) : sides;
}
