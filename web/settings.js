// User settings, persisted in localStorage (per phone).

const KEY = "pocketwheel.settings.v1";
const OLD_KEY = "phonewheel.settings.v1";  // before the rename; read once so nothing is lost

export const DEFAULT_SETTINGS = {
  sensitivity: 1,     // ×1 = full lock at 50° of tilt each way; ×2 = at 25°
  smoothing: 0.2,     // 0 = most responsive .. 1 = smoothest
  deadzone: 0.02,     // fraction of full lock ignored around center
  curve: 1,           // response exponent: 1 = linear, >1 = gentler near center
  invert: false,
  lockSteering: false,
  vibration: true,    // haptics: taps on buttons, plus the ones below
  shiftHaptic: "light", // click on the shift buttons: "off" | "light" | "medium" | "heavy"
  hapticShift: true,  // pulse at the shift point
  hapticAbs: true,    // buzz while ABS is working (Android)
  gearD: "auto",      // show "D" for automatic gearboxes: "auto" (detect) | "on" | "off"
  revStyle: "leds",   // rev lights: "leds" (F1-style bulbs) | "bar" | "both"
  center: 0,          // calibrated straight-ahead angle, degrees
  gravitySign: null,  // 1 / -1 once learned: which way this phone reports gravity
};

export function loadSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(KEY) || localStorage.getItem(OLD_KEY) || "{}") };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    // Private mode or storage blocked: settings just won't persist.
  }
}
