"""Web server: serves the phone UI and links its WebSocket to the pad and telemetry.

WebSocket messages (JSON):
  phone -> PC  {"t":"in","s":steer,"th":throttle,"br":brake,"b":buttons,
                "c":[custom buttons held], "a":{custom axis id: v, joystick id: [x, y]}}
               {"t":"ping","id":n}
               {"t":"bind","buttons":{"shift_up":"A",...}}   rebind (partial is fine)
               {"t":"custom","buttons":[{"id","label","bind"},...]}  replace custom buttons
               {"t":"vib","settings":{"strength":0.5,...}}   vibration motors (partial is fine)
               {"t":"vib","test":true}    buzz the motors once
               {"t":"ffb","settings":{"strength":0.5,...}}   force feedback (partial is fine)
  PC -> phone  {"t":"tel",...}            telemetry, see telemetry.Sample.to_message
               {"t":"binds","buttons":{...},"options":[...],"custom":[...],"keys":[...]}
               {"t":"pong","id":n}
               {"t":"rumble","l":0..1,"s":0..1}
               {"t":"kicked","by":ip}     another phone has control
               {"t":"vib","settings":{...},"status":"..."}   vibration motors state
               {"t":"ffb","settings":{...},"status":"..."}   force feedback state
The phone connects to /ws?id=<page id>&p=<player>, adding &auto=1 when it reconnects by
itself. Each player (config "players", default 2) has its own virtual Xbox controller; button
bindings and custom controls are shared. Game telemetry, vibration, force feedback and webcam
taps belong to Player 1 (BeamNG only reports the car the camera follows).

/cam/ws (this PC only): the webcam page (web/cam.html, experimental) reports finger taps on
the back of the phone, {"t":"tap","side":"left"|"right"}, which press shift down / up.
  PC -> page   {"t":"cam","phone":true}   whether a phone is driving
  PC -> phone  {"t":"gshift","dir":"up"|"down"}   a gesture shifted (the phone flashes it)
"""

import asyncio
import dataclasses
import json
import logging
import mimetypes
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from .config import DEFAULTS, save_config
from .custom import BIND_OPTIONS, resolve, validate_custom
from .ffb import ForceFeedback
from .vibration import Vibration
from .gamepad import Pad
from .keyboard import KEYS, Keyboard, NoKeyboard, SharedKeyboard
from .state import (BTN_SHIFT_DOWN, BTN_SHIFT_UP, NEUTRAL, XBOX_BUTTONS, parse_input,
                    validate_bindings)
from .telemetry.hub import TelemetryHub

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Windows can map .js to text/plain via the registry, which breaks ES modules.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/manifest+json", ".webmanifest")


# An automatic reconnect only takes over from a phone that has been silent this long.
BUSY_S = 1.0
# A gesture (webcam tap) holds its shift button this long.
GESTURE_PRESS_S = 0.1


class Session:
    """The one phone currently in control, plus the fail-safe watchdog."""

    def __init__(self, pad: Pad, hub: TelemetryHub, watchdog_s: float, clock=time.monotonic,
                 on_bindings=None, keyboard: Keyboard | None = None, custom_buttons=(),
                 on_custom=None, player: int = 1):
        self.pad, self.hub = pad, hub
        self.player = player
        self.keyboard = keyboard or NoKeyboard()
        self.custom = list(custom_buttons)
        self.watchdog_s = watchdog_s
        self.clock = clock
        self.on_bindings = on_bindings  # callable(bindings) to persist a rebind
        self.on_custom = on_custom      # callable(custom buttons) to persist edits
        self.ws: web.WebSocketResponse | None = None
        self.client_id = ""   # page id of the phone in control
        self.peer = ""        # and its IP address
        self.last_input = 0.0
        self.is_neutral = True
        self._gesture_until = {}  # button bit -> clock time its gesture press ends

    @property
    def driving(self) -> bool:
        return self.ws is not None and not self.is_neutral

    def _gesture_bits(self) -> int:
        now = self.clock()
        return sum(bit for bit, until in self._gesture_until.items() if until > now)

    def gesture_shift(self, side: str) -> str | None:
        """A shift from a gesture (left = down, right = up), held briefly on top of whatever
        the phone sends. Only while a phone is driving. Returns "up" / "down" or None."""
        if side not in ("left", "right") or not self.driving:
            return None
        bit = BTN_SHIFT_DOWN if side == "left" else BTN_SHIFT_UP
        self._gesture_until[bit] = self.clock() + GESTURE_PRESS_S
        state = dataclasses.replace(self.pad.state, buttons=self.pad.state.buttons | bit)
        self.pad.apply(state)
        self.hub.on_input(state)
        return "down" if side == "left" else "up"

    def bindings_message(self) -> dict:
        return {"t": "binds", "player": self.player,
                "buttons": self.pad.bindings, "options": list(XBOX_BUTTONS),
                "custom": self.custom, "keys": list(KEYS),
                "custom_binds": {kind: list(opts) for kind, opts in BIND_OPTIONS.items()}}

    def set_custom(self, buttons) -> bool:
        """Replace the custom button list from the phone. Returns False if rejected."""
        try:
            custom = validate_custom(buttons)
        except (ValueError, TypeError) as exc:
            log.warning("Ignored custom buttons: %s", exc)
            return False
        self.custom = custom
        self.go_neutral()  # nothing held may outlive the button that held it
        log.info("Custom controls: %s", ", ".join(f"{b['label']} = {b['bind']}" for b in custom) or "none")
        if self.on_custom:
            self.on_custom(custom)
        return True

    def set_bindings(self, changes) -> bool:
        """Apply a (partial) rebind from the phone. Returns False if it was rejected."""
        try:
            bindings = validate_bindings({**self.pad.bindings, **(changes or {})})
        except (ValueError, TypeError) as exc:
            log.warning("Ignored button binding: %s", exc)
            return False
        self.pad.set_bindings(bindings)
        log.info("Buttons bound: %s", ", ".join(f"{a} = {b}" for a, b in bindings.items()))
        if self.on_bindings:
            self.on_bindings(bindings)
        return True

    async def attach(self, ws, peer: str = "", client_id: str = "", auto: bool = False) -> bool:
        """Give control to a new connection; the previous phone is told and dropped.

        Tapping Start / Take control back always takes over. An automatic reconnect doesn't
        take control from another phone that is still driving, otherwise two phones would
        keep stealing it back and forth. The same page coming back after a dropout always
        gets back in. Returns False (and closes ws) when refused.
        """
        old = self.ws
        old_alive = old is not None and not old.closed
        busy = old_alive and self.clock() - self.last_input < BUSY_S
        if auto and busy and client_id != self.client_id:
            await ws.send_json({"t": "kicked", "by": self.peer})
            await ws.close()
            return False
        self.ws, self.peer, self.client_id = ws, peer, client_id
        if old_alive:
            await old.send_json({"t": "kicked", "by": peer})
            await old.close()
        self.go_neutral()
        return True

    def detach(self, ws) -> None:
        if ws is self.ws:
            self.ws = None
            self.go_neutral()

    def on_input(self, msg: dict) -> None:
        state = parse_input(msg)
        if self._gesture_until:
            state = dataclasses.replace(state, buttons=state.buttons | self._gesture_bits())
        out = resolve(self.custom, state.custom, dict(state.analog))
        state = dataclasses.replace(state, extra_buttons=out.pad_buttons, axes=out.axes)
        self.pad.apply(state)
        self.keyboard.apply(out.keys)
        self.hub.on_input(state)
        self.last_input = self.clock()
        self.is_neutral = False

    def go_neutral(self) -> None:
        self.pad.neutral()
        self.keyboard.release_all()
        self.hub.on_input(NEUTRAL)
        self.is_neutral = True

    def check_watchdog(self) -> None:
        if not self.is_neutral and self.clock() - self.last_input > self.watchdog_s:
            log.info("No input for %d ms: controls released", self.watchdog_s * 1000)
            self.go_neutral()

    async def send(self, msg: dict) -> None:
        ws = self.ws
        if ws is not None and not ws.closed:
            try:
                await ws.send_str(json.dumps(msg, separators=(",", ":")))
            except ConnectionError:
                pass


SESSION_KEY = web.AppKey("session", Session)
CERT_DIR_KEY = web.AppKey("cert_dir", Path)
VISITORS_KEY = web.AppKey("visitors", set)
HTTPS_URL_KEY = web.AppKey("https_url", str)
VIBRATION_KEY = web.AppKey("vibration", Vibration)
FFB_KEY = web.AppKey("ffb", ForceFeedback)
PLAYERS_KEY = web.AppKey("players", dict)        # player number -> Session (as they join)
JOIN_KEY = web.AppKey("join", object)            # callable(player) -> Session | None


async def _watchdog_loop(sessions: dict) -> None:
    while True:
        for session in list(sessions.values()):
            session.check_watchdog()
        await asyncio.sleep(0.05)


async def _vibration_loop(session: Session, hub: TelemetryHub, vibration: Vibration) -> None:
    status = None
    while True:
        now = time.monotonic()
        vibration.tick(now, hub.latest(now), session.driving)
        if vibration.status != status:  # tell the phone when the Arduino comes or goes
            status = vibration.status
            await session.send(vibration.message())
        await asyncio.sleep(1 / vibration.rate_hz)


async def _ffb_loop(session: Session, hub: TelemetryHub, ffb: ForceFeedback) -> None:
    status = None
    while True:
        now = time.monotonic()
        ffb.tick(now, hub.latest(now), session.pad.state.steer, session.driving)
        if ffb.status != status:  # tell the phone when the Arduino comes or goes
            status = ffb.status
            await session.send(ffb.message())
        await asyncio.sleep(1 / ffb.rate_hz)


async def _telemetry_loop(sessions: dict, hz: float) -> None:
    while True:
        for session in list(sessions.values()):
            if session.ws is not None:
                await session.send(session.hub.latest(time.monotonic()).to_message())
        await asyncio.sleep(1 / hz)


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    try:
        player = int(request.query.get("p", "1"))
    except ValueError:
        player = 1
    session: Session = request.app[JOIN_KEY](player) or request.app[SESSION_KEY]
    sessions = request.app[PLAYERS_KEY]
    ws = web.WebSocketResponse(heartbeat=5.0)
    await ws.prepare(request)
    peer = request.remote
    auto = request.query.get("auto") == "1"
    if not await session.attach(ws, peer, request.query.get("id", ""), auto):
        log.info("Kept control with %s: %s reconnected while it was driving", session.peer, peer)
        return ws
    log.info("Phone connected as Player %d: %s", session.player, peer)
    await session.send(session.bindings_message())
    vibration = request.app[VIBRATION_KEY]
    ffb = request.app[FFB_KEY]
    hardware = session.player == 1  # the mount's motors follow Player 1
    if hardware:
        await session.send(vibration.message())
        await session.send(ffb.message())

    async def everyone_rebound():
        for other in list(sessions.values()):
            await other.send(other.bindings_message())
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except ValueError:
                continue
            kind = data.get("t")
            if kind == "in" and ws is session.ws:
                session.on_input(data)
            elif kind == "ping":
                await ws.send_json({"t": "pong", "id": data.get("id")})
            elif kind == "custom" and ws is session.ws:
                session.set_custom(data.get("buttons"))
                await everyone_rebound()
            elif kind == "ffb" and ws is session.ws and hardware:
                ffb.set_settings(data.get("settings"))
                await session.send(ffb.message())
            elif kind == "vib" and ws is session.ws and hardware:
                if data.get("test"):
                    vibration.test(time.monotonic())
                if "settings" in data:
                    vibration.set_settings(data.get("settings"))
                await session.send(vibration.message())
            elif kind == "bind" and ws is session.ws:
                session.set_bindings(data.get("buttons"))
                await everyone_rebound()  # confirm, or undo a rejected pick
    finally:
        session.detach(ws)
        log.info("Player %d phone disconnected: %s", session.player, peer)
    return ws


async def _cam_ws_handler(request: web.Request) -> web.StreamResponse:
    """The webcam tap page. Only from this PC: anyone on the Wi-Fi could shift otherwise."""
    if request.remote not in ("127.0.0.1", "::1"):
        raise web.HTTPForbidden(text="The webcam page only works on the PC running PocketWheel.")
    session: Session = request.app[SESSION_KEY]
    ws = web.WebSocketResponse(heartbeat=5.0)
    await ws.prepare(request)
    log.info("Webcam tap page connected")
    await ws.send_json({"t": "cam", "phone": session.driving})
    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            data = json.loads(msg.data)
        except ValueError:
            continue
        if data.get("t") == "tap":
            direction = session.gesture_shift(data.get("side"))
            if direction:
                action = "shift_up" if direction == "up" else "shift_down"
                button = session.pad.bindings.get(action, "?")
                log.info("Webcam tap: shift %s (Xbox %s)", direction, button)
                await session.send({"t": "gshift", "dir": direction})
                await ws.send_json({"t": "tapped", "dir": direction, "button": button})
            else:
                log.info("Webcam tap ignored: no phone is driving")
                await ws.send_json({"t": "tapped", "dir": None})
            await ws.send_json({"t": "cam", "phone": session.driving})
    log.info("Webcam tap page disconnected")
    return ws


async def _cam(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "cam.html")


async def _index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def _ca_cert(request: web.Request) -> web.Response:
    body = (request.app[CERT_DIR_KEY] / "ca.crt").read_bytes()
    return web.Response(body=body, content_type="application/x-x509-ca-cert",
                        headers={"Content-Disposition": 'attachment; filename="pocketwheel-ca.crt"'})


@web.middleware
async def _no_cache(request, handler):
    # The page is tiny and served over LAN; never let the phone run stale JS.
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store"
    return response


def describe_device(user_agent: str) -> str:
    """'Android, Chrome' style summary of a User-Agent, for the connection log."""
    ua = user_agent or ""
    system = ("Android" if "Android" in ua else "iPhone/iPad" if ("iPhone" in ua or "iPad" in ua)
              else "Windows" if "Windows" in ua else "Mac" if "Mac OS" in ua else "unknown device")
    browser = ("Samsung Internet" if "SamsungBrowser" in ua else "Firefox" if "Firefox" in ua
               else "Edge" if ("EdgA" in ua or "Edg/" in ua) else "Chrome" if "Chrome" in ua
               else "Safari" if "Safari" in ua else "unknown browser")
    return f"{system}, {browser}"


@web.middleware
async def _log_visitors(request, handler):
    # One line per device and scheme, so a phone that "can't reach the page" can be told
    # apart from one whose requests never arrive at all.
    key = (request.remote, request.secure)
    if key not in request.app[VISITORS_KEY]:
        request.app[VISITORS_KEY].add(key)
        log.info("Page requested by %s over %s (%s)", request.remote,
                 "HTTPS" if request.secure else "plain HTTP",
                 describe_device(request.headers.get("User-Agent", "")))
    return await handler(request)


LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


@web.middleware
async def _https_unless_local(request, handler):
    # Plain HTTP is only a secure context (motion sensors allowed) on localhost, which is
    # how Android over USB arrives. Anyone else gets sent to the HTTPS address.
    https_url = request.app[HTTPS_URL_KEY]
    if not request.secure and https_url and request.host.rsplit(":", 1)[0] not in LOCAL_HOSTS:
        raise web.HTTPFound(https_url + request.path_qs)
    return await handler(request)


def create_app(config: dict, pad: Pad, hub: TelemetryHub, cert_dir: Path,
               config_path: Path | None = None, https_url: str | None = None,
               keyboard: Keyboard | None = None, pad_factory=None) -> web.Application:
    """pad is Player 1's controller; pad_factory(bindings) makes one for each further player
    (without it there's only Player 1)."""
    app = web.Application(middlewares=[_log_visitors, _https_unless_local, _no_cache])
    app[VISITORS_KEY] = set()
    app[HTTPS_URL_KEY] = https_url

    def persist(key):
        def save(value):
            config[key] = value
            if config_path:
                save_config(config_path, config)
        return save

    shared_keys = SharedKeyboard(keyboard or NoKeyboard())
    sessions: dict[int, Session] = {}
    max_players = config.get("players", 1) if pad_factory else 1

    # Bindings and custom controls are shared: a change from any phone applies to every pad.
    def bindings_changed(bindings):
        persist("buttons")(bindings)
        for other in sessions.values():
            if other.pad.bindings != bindings:
                other.pad.set_bindings(bindings)

    def custom_changed(custom):
        persist("custom_buttons")(custom)
        for other in sessions.values():
            other.custom = list(custom)

    def make_session(player: int, player_pad: Pad, player_hub: TelemetryHub) -> Session:
        sessions[player] = Session(
            player_pad, player_hub, config["watchdog_ms"] / 1000, on_bindings=bindings_changed,
            keyboard=shared_keys.for_player(player),
            custom_buttons=config.get("custom_buttons", []), on_custom=custom_changed,
            player=player)
        return sessions[player]

    def join(player: int) -> Session | None:
        """The session for a player number, creating that player's controller the first time."""
        if player in sessions:
            return sessions[player]
        if not 1 <= player <= max_players:
            return None
        new = make_session(player, pad_factory(dict(sessions[1].pad.bindings)),
                           TelemetryHub([]))  # the game only reports Player 1's car: estimate
        new.pad.on_rumble = lambda large, small: asyncio.ensure_future(
            new.send({"t": "rumble", "l": round(large, 2), "s": round(small, 2)}))
        log.info("Player %d joined: another virtual controller (%s)", player, new.pad.name)
        return new

    session = make_session(1, pad, hub)
    app[SESSION_KEY] = session
    app[PLAYERS_KEY] = sessions
    app[JOIN_KEY] = join
    app[CERT_DIR_KEY] = cert_dir
    vib_config = config.get("vibration", DEFAULTS["vibration"])
    vibration = Vibration(vib_config,
                          on_settings=lambda s: persist("vibration")({**vib_config, **s}))
    app[VIBRATION_KEY] = vibration
    ffb_config = config.get("ffb", DEFAULTS["ffb"])
    ffb = ForceFeedback(ffb_config, on_settings=lambda s: persist("ffb")({**ffb_config, **s}))
    app[FFB_KEY] = ffb

    # Called on the event loop (the pad hops threads before calling it).
    def on_rumble(large, small):
        vibration.rumble = (large, small)
        ffb.rumble = max(large, small)
        asyncio.ensure_future(
            session.send({"t": "rumble", "l": round(large, 2), "s": round(small, 2)}))
    pad.on_rumble = on_rumble

    app.router.add_get("/", _index)
    app.router.add_get("/ws", _ws_handler)
    app.router.add_get("/cam", _cam)
    app.router.add_get("/cam/ws", _cam_ws_handler)
    app.router.add_get("/ca.crt", _ca_cert)
    app.router.add_static("/", WEB_DIR)

    async def background(app):
        await hub.start()
        tasks = [asyncio.create_task(_watchdog_loop(sessions)),
                 asyncio.create_task(_telemetry_loop(sessions, config["telemetry_hz"])),
                 asyncio.create_task(_vibration_loop(session, hub, vibration)),
                 asyncio.create_task(_ffb_loop(session, hub, ffb))]
        yield
        for task in tasks:
            task.cancel()
        vibration.close()
        ffb.close()
        hub.stop()
        shared_keys.release_all()
        for player_session in sessions.values():
            player_session.pad.close()

    app.cleanup_ctx.append(background)
    return app
