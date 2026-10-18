// Laptop webcam page: tracks both hands with MediaPipe and reports finger taps to the PC
// server, which turns them into shift presses for the phone that's driving.
import { TIPS, TapDetector, bends, handSides } from "./handtap.js";

const MEDIAPIPE = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
const MODEL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const PREFS = "pocketwheel.cam.v1";

const $ = (s) => document.querySelector(s);
const video = $("#video");
const overlay = $("#overlay");
const ctx = overlay.getContext("2d");
const detectors = { left: new TapDetector(), right: new TapDetector() };
const cards = Object.fromEntries([...document.querySelectorAll(".hand")].map((el) => [el.dataset.side, el]));

let prefs = { sensitivity: 0.5, swap: false, part: "thumb" };
try { prefs = { ...prefs, ...JSON.parse(localStorage.getItem(PREFS) || "{}") }; } catch {}
const savePrefs = () => { try { localStorage.setItem(PREFS, JSON.stringify(prefs)); } catch {} };
const applySensitivity = () => {
  for (const d of Object.values(detectors)) d.threshold = 30 - 22 * prefs.sensitivity;  // 30..8°
};
$("#sensitivity").value = prefs.sensitivity;
$("#swap").checked = prefs.swap;
$("#part").value = prefs.part;
$("#part").addEventListener("change", (e) => {
  prefs.part = e.target.value;
  for (const d of Object.values(detectors)) d.reset();
  savePrefs();
});
applySensitivity();
$("#sensitivity").addEventListener("input", (e) => {
  prefs.sensitivity = Number(e.target.value);
  applySensitivity();
  savePrefs();
});
$("#swap").addEventListener("change", (e) => {
  prefs.swap = e.target.checked;
  for (const d of Object.values(detectors)) d.reset();
  savePrefs();
});

// ---------------------------------------------------------------- link to the PC server

let ws = null;
function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/cam/ws`);
  ws = socket;
  socket.onopen = () => setLink(true, "PocketWheel: connected");
  socket.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.t === "cam") setLink(true, msg.phone ? "PocketWheel: connected, phone driving"
      : "PocketWheel: connected (taps only shift while a phone is driving)");
    if (msg.t === "tapped") {
      showResult(msg.dir
        ? `Shift ${msg.dir} sent: Xbox ${msg.button} pressed on the virtual controller.`
        : "Tap seen, but PocketWheel ignored it: no phone is driving (start it on the phone).",
        !!msg.dir);
    }
  };
  socket.onclose = () => {
    setLink(false, "PocketWheel: not connected (is main.py running?)");
    setTimeout(connect, 2000);
  };
}
function setLink(ok, text) {
  $("#link-dot").className = "dot " + (ok ? "ok" : "bad");
  $("#link").textContent = text;
}
connect();

function showResult(text, ok) {
  const el = $("#result");
  el.textContent = text;
  el.className = ok ? "ok" : "bad";
}

function sendTap(side) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ t: "tap", side }));
  } else {
    showResult("Tap seen, but NOT sent: this page isn't connected to PocketWheel. Open it as " +
      "http://localhost:8080/cam on the PC running main.py.", false);
  }
  const card = cards[side];
  card.classList.add("tap");
  setTimeout(() => card.classList.remove("tap"), 180);
}

// ---------------------------------------------------------------- webcam + hand tracking

let landmarker = null;
let lastVideoTime = -1;

$("#start").addEventListener("click", async () => {
  const button = $("#start");
  button.disabled = true;
  const status = $("#status");
  try {
    status.textContent = "Loading the hand tracker…";
    const vision = await import(`${MEDIAPIPE}/vision_bundle.mjs`);
    const files = await vision.FilesetResolver.forVisionTasks(`${MEDIAPIPE}/wasm`);
    landmarker = await vision.HandLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: MODEL, delegate: "GPU" },
      runningMode: "VIDEO",
      numHands: 2,
      minHandDetectionConfidence: 0.4,
      minHandPresenceConfidence: 0.4,
      minTrackingConfidence: 0.4,
    });
    status.textContent = "Starting the webcam…";
    video.srcObject = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 960 }, height: { ideal: 720 }, frameRate: { ideal: 60 } }, audio: false,
    });
    await video.play();
    $(".stage").hidden = false;
    button.hidden = true;
    status.textContent = "";
    // A timer, not requestAnimationFrame: rAF stops whenever the page is hidden, e.g. behind
    // the game. (A normal browser window also slows timers then; main.py --cam opens one that
    // doesn't.)
    setInterval(loop, 15);
  } catch (err) {
    button.disabled = false;
    status.textContent = `Couldn't start: ${err.message || err.name}. ` +
      "Open this page as http://localhost:8080/cam on the PC running PocketWheel, allow the " +
      "camera, and check the internet connection (the hand tracker loads from the web).";
  }
});

const BONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10],
  [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18],
  [18, 19], [19, 20]];

function loop() {
  if (video.paused) video.play().catch(() => {});
  if (video.currentTime === lastVideoTime || video.readyState < 2) return;
  lastVideoTime = video.currentTime;
  const now = performance.now();
  const result = landmarker.detectForVideo(video, now);
  const hands = result.landmarks ?? [];
  const sides = handSides(hands.map((h) => h[0].x), prefs.swap);
  const seen = new Set();
  hands.forEach((hand, i) => {
    const side = sides[i];
    if (seen.has(side)) return;  // two hands on one side this frame: trust the first
    seen.add(side);
    if (detectors[side].update(bends(result.worldLandmarks[i], prefs.part), now)) sendTap(side);
  });
  for (const side of ["left", "right"]) {
    const card = cards[side];
    if (!seen.has(side)) {
      detectors[side].reset();
      card.querySelector("[data-info]").textContent = "not seen";
    } else {
      card.querySelector("[data-info]").textContent = "tracking";
    }
    card.querySelector(".meter div").style.width = `${Math.min(100, detectors[side].level * 100)}%`;
  }
  if (!document.hidden) draw(hands, sides);
}

function draw(hands, sides) {
  const w = (overlay.width = overlay.clientWidth * devicePixelRatio);
  const h = (overlay.height = overlay.clientHeight * devicePixelRatio);
  // Same box as the video's object-fit: contain, mirrored like the video.
  const scale = Math.min(w / video.videoWidth, h / video.videoHeight);
  const vw = video.videoWidth * scale, vh = video.videoHeight * scale;
  const ox = (w - vw) / 2, oy = (h - vh) / 2;
  const at = (p) => [ox + (1 - p.x) * vw, oy + p.y * vh];
  ctx.lineWidth = 3 * devicePixelRatio;
  hands.forEach((hand, i) => {
    const color = sides[i] === "left" ? "#f97316" : "#38bdf8";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    for (const [a, b] of BONES) {
      ctx.beginPath();
      ctx.moveTo(...at(hand[a]));
      ctx.lineTo(...at(hand[b]));
      ctx.stroke();
    }
    for (const tip of TIPS[prefs.part]) {
      ctx.beginPath();
      ctx.arc(...at(hand[tip]), 6 * devicePixelRatio, 0, Math.PI * 2);
      ctx.fill();
    }
    const [x, y] = at(hand[0]);
    ctx.font = `${14 * devicePixelRatio}px system-ui`;
    ctx.fillText(sides[i] === "left" ? "LEFT" : "RIGHT", x - 20 * devicePixelRatio, y + 22 * devicePixelRatio);
  });
}
