# PhoneWheel (hts_2026)

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
the screen stays portrait and PhoneWheel draws its controls sideways by itself, following which
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

Keys go to whichever window has focus on the PC, i.e. the game. Alt and the Windows key aren't
offered, and everything held is released by the same 300 ms safety cut-off as the pedals.

**Rev lights.** Settings → *Rev lights*: F1-style LED bulbs (5 green, 5 red, 5 blue, all
blinking at the shift point), the classic bar, or both. They're a separate element from the
gear/speed dash, so Edit layout can move and resize them on their own.

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
  Neutral (BeamNG sends 0 for both), so PhoneWheel includes a tiny BeamNG mod that sends the real
  gear name and the engine's redline. Install it once with `python main.py --install-beamng-mod`,
  restart BeamNG, then tick **Options → Other → Other protocols** (keep OutGauge on too).
- The dash badge says **BEAMNG** or **AC** when live data arrives. **EST** means none is: the gear
  is then counted from your shift presses and RPM follows the throttle.
- Only one copy of PhoneWheel can receive BeamNG data at a time (it owns UDP port 4444).

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
