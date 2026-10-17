// Phone haptics.
// Android: the Vibration API (any length, no strength, so strength is played as duty cycle).
// iPhone: Safari has no Vibration API, but since iOS 18 toggling an <input switch> plays the
// system haptic tick, so a hidden switch is toggled instead. iOS only plays it reliably while
// handling a touch, so taps always tick and the rest is best effort.
import { isIOS } from "./orientation.js";

const canVibrate = typeof navigator.vibrate === "function";

let iosSwitch = null;
function iosTick() {
  if (!iosSwitch) {
    iosSwitch = document.createElement("label");
    iosSwitch.setAttribute("aria-hidden", "true");
    iosSwitch.style.display = "none";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.setAttribute("switch", "");
    iosSwitch.append(input);
    document.body.append(iosSwitch);
  }
  iosSwitch.click();
}

export const hapticsKind = canVibrate ? "vibrate" : isIOS ? "ios-switch" : "none";

// One short pulse: "light" (button), "medium" (gear change), "heavy".
// Returns false when the browser refused it (e.g. Chrome before the first tap).
export function tap(strength = "light") {
  if (canVibrate) return navigator.vibrate({ light: 12, medium: 28, heavy: 45 }[strength] ?? 12);
  if (!isIOS) return false;
  iosTick();
  if (strength === "heavy") setTimeout(iosTick, 70);
  return true;
}

// Continuous buzz at 0..1 strength; call it every BUZZ_MS. Android only (iOS can't sustain one).
export const BUZZ_MS = 120;
export function buzz(strength) {
  if (!canVibrate || strength <= 0.05) return;
  navigator.vibrate(Math.round(20 + Math.min(1, strength) * (BUZZ_MS - 20)));
}

export function stop() {
  if (canVibrate) navigator.vibrate(0);
}
