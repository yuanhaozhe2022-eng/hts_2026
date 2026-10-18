// EXPERIMENTAL: cover the rear camera with a finger to shift.
//
// A tiny, low-rate video from the rear camera; its average brightness is followed slowly.
// A finger over the lens drops it far below that in a frame or two, which counts as one
// tap; it re-arms once the picture brightens again.

const SAMPLE_MS = 50;
const COVERED = 0.35;   // brightness below this fraction of normal = finger on the lens
const UNCOVERED = 0.6;
const MIN_LIGHT = 20;   // 0..255: darker than this and covering can't be seen

export class LensTap {
  constructor(onCover) {
    this.onCover = onCover;
    this.enabled = () => true;
    this.stream = null;
    this.status = "off";
    this._baseline = null;
    this._covered = false;
    this._timer = null;
    this._video = Object.assign(document.createElement("video"), { muted: true, playsInline: true });
    this._video.setAttribute("playsinline", "");
    this._canvas = Object.assign(document.createElement("canvas"), { width: 16, height: 12 });
    this._ctx = this._canvas.getContext("2d", { willReadFrequently: true });
  }

  async start() {
    if (this.stream) return this.status;
    if (!navigator.mediaDevices?.getUserMedia) return (this.status = "No camera access in this browser.");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 160 }, height: { ideal: 120 },
                 frameRate: { ideal: 20 } },
        audio: false,
      });
    } catch (err) {
      return (this.status = `Camera blocked (${err.name}). Allow camera access for this site.`);
    }
    this._video.srcObject = this.stream;
    await this._video.play().catch(() => {});
    this._baseline = null;
    this._covered = false;
    this._timer = setInterval(() => this._sample(), SAMPLE_MS);
    return (this.status = "Watching the rear camera.");
  }

  stop() {
    clearInterval(this._timer);
    this._timer = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.status = "off";
  }

  _sample() {
    if (this._video.readyState < 2) return;
    this._ctx.drawImage(this._video, 0, 0, 16, 12);
    const px = this._ctx.getImageData(0, 0, 16, 12).data;
    let sum = 0;
    for (let i = 0; i < px.length; i += 4) sum += px[i] * 0.3 + px[i + 1] * 0.59 + px[i + 2] * 0.11;
    const light = sum / (px.length / 4);
    if (this._baseline == null) this._baseline = light;

    if (this._covered) {
      if (light > this._baseline * UNCOVERED) this._covered = false;
      return;  // don't learn "normal" from the dark frames
    }
    if (this._baseline > MIN_LIGHT && light < this._baseline * COVERED) {
      this._covered = true;
      if (this.enabled()) this.onCover();
      return;
    }
    this._baseline += (light - this._baseline) * 0.05;  // follows slow lighting changes
  }
}
