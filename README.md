# PocketWheel (hts_2026)

Use your phone as a steering wheel + pedals for **BeamNG.drive** and **Assetto Corsa / ACC**.

- **Steer** by tilting the phone like a wheel (gyro + accelerometer).
- **Brake** (left) and **throttle** (right) bars: touch anywhere on a bar and it jumps to your finger,
  drag to adjust, lift to release.
- **Shift down** (left) and **shift up** (right) buttons.
- **Dashboard** with live gear, RPM bar and shift light, read from the game's telemetry.
- Every control can be moved and resized (Settings → Edit layout), saved on the phone.

The PC runs a small server that creates a virtual Xbox 360 controller; the phone just opens a web
page, so there's nothing to install on it (Android and iPhone).

## Setup (Windows)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Installing `vgamepad` opens the **ViGEmBus driver** installer. Accept it; that driver is what
lets Windows see the virtual controller. Without it the server still runs, in dry-run mode.

## Run

```bash
python main.py
```

1. Connect the phone to the **same Wi-Fi** as the PC and scan the QR code shown in the terminal.
2. The phone warns about the certificate (it's generated locally for your PC). Choose
   *Advanced → Proceed* on Android, or *Show Details → visit this website* on iPhone.
   To get rid of the warning permanently, open Settings on the phone page and install the CA.
3. Tap **Start driving**, hold the phone level, and press **Center steering** in Settings.
4. If Windows Firewall asks, allow Python on private networks.

**Android over USB (most reliable, lowest lag).** Campus and other managed Wi-Fi often blocks
phones from reaching a PC (Android Chrome then shows errors like `ERR_TOO_MANY_RETRIES` or
"can't be reached"). A USB cable avoids the network and the certificate altogether:
1. Download [Android platform-tools](https://developer.android.com/tools/releases/platform-tools)
   and unzip it next to `main.py` (so `platform-tools/adb.exe` exists), or put `adb` on PATH.
2. On the phone: Settings → About phone → tap *Build number* 7 times, then Developer options →
   **USB debugging** on. Plug it in and tap *Allow* when asked.
3. Run `python main.py --usb` and open **http://localhost:8080** in Chrome on the phone.

**Can't connect at all?** The PC logs every device that reaches it ("Page requested by ...").
If your phone never appears there, the network is blocking it: use USB (above), or turn on the
phone's hotspot and connect the PC to it. For the full picture, stop `main.py` and run
`python tools/net_check.py`: open the address it prints on the phone and tap both test links.
It logs every connection attempt and exactly how it ended.

**iPhone:** turn on **Rotation Lock** (Control Center → lock button) before you start. A web page
can't lock landscape on iPhone, so without it a hard turn can flip the screen. With the lock on,
the screen stays portrait and PocketWheel draws its controls sideways by itself, following which
way round you hold the phone. If they ever come out upside down, tap **Upside down? Flip** in
Settings (shown only in this mode).

## Game setup

Bind controls in the game's menu like any Xbox controller:

| Phone            | Xbox controller   |
|------------------|-------------------|
| Steering         | Left stick X      |
| Throttle bar     | Right trigger     |
| Brake bar        | Left trigger      |
| Shift up         | RB (changeable)   |
| Shift down       | LB (changeable)   |

To make the shift buttons press something else (e.g. shift up = A, shift down = X), open
Settings on the phone → **Controller buttons**. The PC applies it immediately and saves it in
`config.json`, so it sticks for every phone. Each shift button shows its Xbox button, e.g. "UP · A".

**Custom controls.** Settings → **Custom controls** adds up to 12 extra on-screen controls; move
and resize them with Edit layout.

| Add        | On the phone                          | Bind to |
|------------|---------------------------------------|---------|
| + Button   | Tap / hold                            | A controller button, or a keyboard key (letters, numbers, F1–F12, arrows, Space, Enter, Esc, Shift, Ctrl, numpad, ...) |
| + Joystick | Thumbstick, springs back to center    | Right stick (camera), Left stick (walking; replaces steering only while held), W A S D or arrow keys |
| + Axis     | Slider, springs back                  | Right stick X / Y (look around), Left stick Y, Left / Right trigger |

**Per-control settings (⚙).** Each custom control has a cog next to it in Settings:
- **Vibration click:** off / light / medium / heavy when touched (iPhone and Android), plus an
  optional click on release.
- **Buttons:** *hold*, *toggle* (tap on, tap off), *tap* (one short press), or *rapid fire* with a
  rate.
- **Joysticks / axes:** spring back or stay where released, dead zone, sensitivity, invert, a
  click at full tilt (joystick) or when crossing the middle (axis).
- **Look:** color and opacity.

The shift buttons' click strength is under Settings → Haptics.

Keys go to whichever window has focus on the PC, i.e. the game. Alt and the Windows key aren't
offered, and everything held is released by the same 300 ms safety cut-off as the pedals.

**Rev lights.** Settings → *Rev lights*: F1-style LED bulbs (5 green, 5 red, 5 blue, all
blinking at the shift point), the classic bar, or both. They're a separate element from the
gear/speed dash, so Edit layout can move and resize them on their own.

**Haptics.** Settings → *Haptics / vibration* (with a **Test** button that says what's wrong if
you feel nothing). The phone ticks on button presses and thumps on gear changes, pulses at the
shift point, and buzzes while ABS is working. These come from the telemetry, so they work in any
game; rumble a game sends to the virtual Xbox controller is added on top.
- **Android:** full vibration. If Test says "Sent" but nothing happens, turn on Settings →
  Sound & vibration → *Vibration & haptics* on the phone, and leave Do Not Disturb / Battery Saver.
- **iPhone:** Safari has no vibration API. On iOS 18+ PocketWheel uses the system haptic tick
  (the one a toggle switch makes) instead: button taps always tick; gear-change and shift-point
  ticks are up to iOS and may not fire. No continuous buzz. Needs Settings → Sounds & Haptics →
  *System Haptics* on.

Tip: turn on **Lock steering at center** in the phone's Settings while binding pedals and
buttons, so tilting the phone doesn't get picked up instead.

**Steering feel.** Use the phone's **Steering sensitivity** (×1 = full lock at 50° of tilt, ×2 = 25°),
**smoothing**, deadzone and curve, and switch off the game's own gamepad steering aids, which
add lag and fight the phone:
- **BeamNG.drive:** set the steering binding's filter to *Direct* (the gamepad filter smooths and
  slows steering).
- **Assetto Corsa / ACC:** in the gamepad/controller settings, set steering filter / steering
  speed / speed sensitivity to 0 (or their most direct setting), deadzone 0, gamma 1.

Ports and the safety timeout are in `config.json` (created on first run).

**Telemetry for the dashboard.** The phone shows the car's real state, read from the game:

| Shown on the phone          | BeamNG.drive | Assetto Corsa / ACC |
|-----------------------------|:------------:|:-------------------:|
| Gear, RPM (+ shift light), speed | ✓ | ✓ |
| Fuel %                      | ✓ | ✓ |
| Engine temperature          | ✓ | – |
| Turbo boost                 | ✓ | ✓ |
| Warning lights              | ABS, TC, handbrake, high beam, turn signals, oil, battery | pit limiter |
| Position, lap, current / last / best lap | – | ✓ |

- **BeamNG.drive:** Options → Other → Protocols → enable **OutGauge**, IP `127.0.0.1`, port `4444`.
- **Assetto Corsa / ACC:** nothing to set up (read from the game's shared memory).
- Automatic gearboxes show **D** with the actual gear beside it (e.g. D3). Assetto Corsa reports
  its auto-shifter directly; for BeamNG it's detected when the gear changes without you pressing
  a shift button. Settings → *Show "D" for automatic* can force it on or off.
- **BeamNG P / R / N / D / S / M exactly like the car's dash:** OutGauge can't tell Park from
  Neutral (BeamNG sends 0 for both), so PocketWheel includes a tiny BeamNG mod that sends the real
  gear name and the engine's redline. Install it once with `python main.py --install-beamng-mod`,
  restart BeamNG, then tick **Options → Other → Other protocols** (keep OutGauge on too).
- The dash badge says **BEAMNG** or **AC** when live data arrives. **EST** means none is: the gear
  is then counted from your shift presses and RPM follows the throttle.
- Only one copy of PocketWheel can receive BeamNG data at a time (it owns UDP port 4444).

## Two players

Two phones can drive at once, each as its own Xbox controller. On the start screen (or in
Settings → **Player**), one phone picks **Player 1** and the other **Player 2**. Player 2's
virtual controller appears on the PC the first time a phone joins as Player 2.

- Each player has their own steering, pedals and buttons, and their own safety cut-off; a phone
  only takes over the slot it picked, so the two never kick each other.
- Button bindings and custom controls are shared: a change on either phone applies to both.
- Player 1 gets the game's telemetry on the dash, the vibration motors, force feedback and
  webcam taps. Player 2's dash is estimated (EST): BeamNG only reports the car the camera follows.
- **In BeamNG:** turn on **Multiseat** in the controls options so each controller drives its own
  car, spawn a second vehicle, and have each player switch into theirs. BeamNG itself has no
  split-screen view: both cars share one screen, with the camera on one of them.
- Change `"players"` in `config.json` to allow more (or 1 to turn it off).

## Experimental: shift without buttons

Settings → **Experimental**:
- **Tap the back of the phone.** The accelerometer picks up the sharp jolt of a finger tapping
  the back, and the gyro feels which end was hit: left side = shift down, right side = up. Press
  **Learn my taps** once (3 taps left, 3 right), because phones differ. If yours can't tell the
  sides apart, use *Tap = up, double tap = down*. Taps on the screen don't count, and nothing
  fires while Settings are open. Raise or lower *Back tap sensitivity* if it misses taps or
  shifts on bumps.
- **Cover the rear camera** with a finger to shift up (or down). The page watches the camera's
  brightness and never records or sends video. It needs some light and uses more battery.

**Laptop webcam taps.** Hold the phone like a wheel in front of the laptop with your thumbs
resting along its top long edge: the webcam above the laptop screen sees both thumbs. On the PC
running PocketWheel, run `python main.py --cam` (or open **http://localhost:8080/cam**), press
*Start webcam*, then **click into BeamNG**. The game only reads the controller while it's the
focused window, and an ordinary browser tab pauses itself once the game covers it; the `--cam`
window is set up to keep watching behind the game.
- Lift a thumb and tap it back down on the edge: **left thumb** = shift down, **right thumb** =
  shift up. (*Tap with → Fingers on the back* switches to finger taps on the phone's back.)
- MediaPipe tracks both hands' joints in 3D. A tap is the thumb quickly lifting and landing
  again; turning the phone to steer, small twitches and slowly changing your grip don't count.
- Taps only shift while a phone is driving. Only "tap left / right" goes to PocketWheel: video
  never leaves the browser, and only this PC can connect.
- Needs internet the first time (the hand tracker loads from the web), decent light, and both
  hands in view. Use the *Sensitivity* slider if it misses taps or fires on its own, and *Swap
  left / right* if your webcam mirrors the picture.

## Vibration motors in the phone mount (optional)

Two small vibration motors in the phone mount (left and right, like an Xbox controller's rumble)
buzz for what the car is doing. An Arduino on the PC's USB drives them.

1. Open [arduino/pocketwheel_vibration/pocketwheel_vibration.ino](arduino/pocketwheel_vibration/pocketwheel_vibration.ino)
   in the Arduino IDE and upload it (Uno / Nano). The wiring is at the top of the file: each
   motor through a small MOSFET or transistor (never straight from a pin), with a diode across
   it. It can also drive the RC ESC with a small motor that has an off-centre weight.
2. `pip install pyserial`, plug in the Arduino, and test without a game:
   `python tools/vibration_test.py` (left, right, both, then a ramp).
3. Run `python main.py`, then on the phone turn on Settings → **Vibration motors** and press
   **Test** (left, then right, then both).

| Effect | When |
|---|---|
| Game rumble | whatever the game sends to the controller (left = large motor, right = small) |
| Thump | every gear change |
| Pulses | at the shift point |
| Buzz | while ABS is working |
| Engine hum (off by default) | a light buzz that rises with RPM |

Strength and each effect are set on the phone (saved in `config.json` under `vibration`). The
motors stop within 200 ms if the PC stops sending, and whenever no phone is driving.

## Force feedback base (optional)

Clip the phone onto a base turned by a geared motor (about 1:4). An RC-style ESC with its own
battery drives the motor, and an Arduino on the PC's USB turns PocketWheel's steering force into
ESC pulses: 1500 µs = stop, 1000–2000 µs = full force either way, like an RC car. It can be used
together with the vibration motors (each has its own Arduino; PocketWheel tells them apart).

1. Open [arduino/pocketwheel_ffb/pocketwheel_ffb.ino](arduino/pocketwheel_ffb/pocketwheel_ffb.ino)
   in the Arduino IDE and upload it (Uno / Nano). The wiring and ESC setup are at the top of the
   file. The ESC must reverse straight away (forward/reverse mode, no brake). A brushed motor
   works best.
2. `pip install pyserial`, plug in the Arduino, and test without a game:
   `python tools/ffb_test.py --amp 0.15` (push left, stop, push right). Keep your hands clear.
3. Run `python main.py`, then turn on Settings → **Force feedback** on the phone. Tilt the phone
   off center while driving: the motor should push it back. If it pushes away, tick
   **Invert direction**.

Where the force comes from:
- **Assetto Corsa / ACC:** the game's own force feedback (read from shared memory).
- **BeamNG and other games:** an estimate. A centering spring that firms up with speed, plus road
  feel from game rumble and ABS.
- **Damping**, from how fast the wheel turns, keeps it from wobbling around center. Raise it if
  it oscillates.

Tune strength, spring, damping and road feel on the phone while you drive (saved in
`config.json` under `ffb`). The motor stops within 200 ms if the PC stops sending, and the force
is 0 whenever no phone is driving.

## Safety

If the phone stops sending for 300 ms (Wi-Fi drop, screen off, tab closed), the controller
releases throttle, brake and buttons and centers the steering.

## Development

```bash
python -m pytest                    # unit tests
python main.py --dry-run            # no virtual controller needed
python tools/fake_outgauge.py       # fake BeamNG telemetry to test the dashboard
python tools/fake_assetto.py        # fake Assetto Corsa telemetry (laps, position); not while AC runs
```

Layout: `main.py` (entry), `server/` (web server, pad, telemetry, certificates),
`web/` (phone UI, plain HTML/CSS/JS modules, no build step), `tests/`.
