"""Web server: serves the phone UI and links its WebSocket to the pad and telemetry.

WebSocket messages (JSON):
  phone -> PC  {"t":"in","s":steer,"th":throttle,"br":brake,"b":buttons,
                "c":[custom buttons held], "a":{custom axis id: v, joystick id: [x, y]}}
               {"t":"ping","id":n}
               {"t":"bind","buttons":{"shift_up":"A",...}}   rebind (partial is fine)
               {"t":"custom","buttons":[{"id","label","bind"},...]}  replace custom buttons
  PC -> phone  {"t":"tel",...}            telemetry, see telemetry.Sample.to_message
               {"t":"binds","buttons":{...},"options":[...],"custom":[...],"keys":[...]}
               {"t":"pong","id":n}
               {"t":"rumble","l":0..1,"s":0..1}
               {"t":"kicked"}             another phone took over
"""

import asyncio
import dataclasses
import json
import logging
import mimetypes
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from .config import save_config
from .custom import BIND_OPTIONS, resolve, validate_custom
from .gamepad import Pad
from .keyboard import KEYS, Keyboard, NoKeyboard
from .state import NEUTRAL, XBOX_BUTTONS, parse_input, validate_bindings
from .telemetry.hub import TelemetryHub

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Windows can map .js to text/plain via the registry, which breaks ES modules.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/manifest+json", ".webmanifest")


class Session:
    """The one phone currently in control, plus the fail-safe watchdog."""

    def __init__(self, pad: Pad, hub: TelemetryHub, watchdog_s: float, clock=time.monotonic,
                 on_bindings=None, keyboard: Keyboard | None = None, custom_buttons=(),
                 on_custom=None):
        self.pad, self.hub = pad, hub
        self.keyboard = keyboard or NoKeyboard()
        self.custom = list(custom_buttons)
        self.watchdog_s = watchdog_s
        self.clock = clock
        self.on_bindings = on_bindings  # callable(bindings) to persist a rebind
        self.on_custom = on_custom      # callable(custom buttons) to persist edits
        self.ws: web.WebSocketResponse | None = None
        self.last_input = 0.0
        self.is_neutral = True

    def bindings_message(self) -> dict:
        return {"t": "binds", "buttons": self.pad.bindings, "options": list(XBOX_BUTTONS),
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

    async def attach(self, ws) -> None:
        old, self.ws = self.ws, ws
        if old is not None and not old.closed:
            await old.send_json({"t": "kicked"})
            await old.close()
        self.go_neutral()

    def detach(self, ws) -> None:
        if ws is self.ws:
            self.ws = None
            self.go_neutral()

    def on_input(self, msg: dict) -> None:
        state = parse_input(msg)
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


async def _watchdog_loop(session: Session) -> None:
    while True:
        session.check_watchdog()
        await asyncio.sleep(0.05)


async def _telemetry_loop(session: Session, hub: TelemetryHub, hz: float) -> None:
    while True:
        if session.ws is not None:
            await session.send(hub.latest(time.monotonic()).to_message())
        await asyncio.sleep(1 / hz)


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    session: Session = request.app[SESSION_KEY]
    ws = web.WebSocketResponse(heartbeat=5.0)
    await ws.prepare(request)
    peer = request.remote
    log.info("Phone connected: %s", peer)
    await session.attach(ws)
    await session.send(session.bindings_message())
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
                await session.send(session.bindings_message())
            elif kind == "bind" and ws is session.ws:
                session.set_bindings(data.get("buttons"))
                await session.send(session.bindings_message())  # confirm, or undo a rejected pick
    finally:
        session.detach(ws)
        log.info("Phone disconnected: %s", peer)
    return ws


async def _index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def _ca_cert(request: web.Request) -> web.Response:
    body = (request.app[CERT_DIR_KEY] / "ca.crt").read_bytes()
    return web.Response(body=body, content_type="application/x-x509-ca-cert",
                        headers={"Content-Disposition": 'attachment; filename="phonewheel-ca.crt"'})


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
               keyboard: Keyboard | None = None) -> web.Application:
    app = web.Application(middlewares=[_log_visitors, _https_unless_local, _no_cache])
    app[VISITORS_KEY] = set()
    app[HTTPS_URL_KEY] = https_url

    def persist(key):
        def save(value):
            config[key] = value
            if config_path:
                save_config(config_path, config)
        return save

    session = Session(pad, hub, config["watchdog_ms"] / 1000, on_bindings=persist("buttons"),
                      keyboard=keyboard, custom_buttons=config.get("custom_buttons", []),
                      on_custom=persist("custom_buttons"))
    app[SESSION_KEY] = session
    app[CERT_DIR_KEY] = cert_dir

    # Called on the event loop (the pad hops threads before calling it).
    pad.on_rumble = lambda large, small: asyncio.ensure_future(
        session.send({"t": "rumble", "l": round(large, 2), "s": round(small, 2)}))

    app.router.add_get("/", _index)
    app.router.add_get("/ws", _ws_handler)
    app.router.add_get("/ca.crt", _ca_cert)
    app.router.add_static("/", WEB_DIR)

    async def background(app):
        await hub.start()
        tasks = [asyncio.create_task(_watchdog_loop(session)),
                 asyncio.create_task(_telemetry_loop(session, hub, config["telemetry_hz"]))]
        yield
        for task in tasks:
            task.cancel()
        hub.stop()
        session.keyboard.release_all()
        pad.close()

    app.cleanup_ctx.append(background)
    return app
