// Sideways HUD on a portrait screen.
//
// A web page can't lock landscape on iPhone, and iOS Rotation Lock only locks portrait.
// So whenever the screen is portrait while driving, the HUD is drawn rotated 90° to match
// how the phone is held. With Rotation Lock on, the screen then never flips mid-corner.

export const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

let hud = null;
let mode = 0;  // 0 = native landscape, 90 = HUD turned clockwise, -90 = counter-clockwise

export function initRotation(el) {
  hud = el;
}

// direction: 90 when the phone's top points left, -90 when it points right.
// Returns the mode now in effect.
export function applyRotation(enabled, direction) {
  const W = window.innerWidth, H = window.innerHeight;
  mode = enabled && H > W ? direction : 0;
  hud.classList.toggle("rotated", mode !== 0);
  if (mode === 0) {
    hud.style.width = hud.style.height = hud.style.transform = "";
  } else {
    hud.style.width = `${H}px`;
    hud.style.height = `${W}px`;
    hud.style.transform = mode === 90
      ? `translateX(${W}px) rotate(90deg)`
      : `translateY(${H}px) rotate(-90deg)`;
  }
  return mode;
}

// A pointer position in the HUD's own (unrotated) pixel coordinates, the same space
// as the elements' offsetLeft / offsetTop.
export function hudPoint(clientX, clientY) {
  if (mode === 90) return { x: clientY, y: window.innerWidth - clientX };
  if (mode === -90) return { x: window.innerHeight - clientY, y: clientX };
  const r = hud.getBoundingClientRect();
  return { x: clientX - r.left, y: clientY - r.top };
}
