"""Plain-HTTP side: localhost (Android over USB) gets the app, LAN visitors go to HTTPS."""

import asyncio
import logging

from aiohttp.test_utils import TestClient, TestServer

from server.app import create_app, describe_device
from server.gamepad import DryRunPad
from server.telemetry.hub import TelemetryHub

CONFIG = {"watchdog_ms": 300, "telemetry_hz": 30}
HTTPS_URL = "https://10.0.0.2:8443"


async def fetch(host: str | None, path: str = "/"):
    app = create_app(dict(CONFIG), DryRunPad(), TelemetryHub([]), cert_dir=None, https_url=HTTPS_URL)
    async with TestClient(TestServer(app)) as client:
        headers = {"Host": host} if host else {}
        headers["User-Agent"] = "Mozilla/5.0 (Linux; Android 15) Chrome/140.0 Mobile Safari/537.36"
        resp = await client.get(path, headers=headers, allow_redirects=False)
        return resp.status, resp.headers.get("Location"), await resp.text()


def test_localhost_gets_the_app_over_plain_http():
    status, _, body = asyncio.run(fetch("localhost:8080"))
    assert status == 200 and "PocketWheel" in body


def test_lan_visitor_is_sent_to_https():
    status, location, _ = asyncio.run(fetch("10.0.0.2:8080", "/app.js?x=1"))
    assert status == 302 and location == HTTPS_URL + "/app.js?x=1"


def test_each_device_is_logged_once(caplog):
    with caplog.at_level(logging.INFO, logger="server.app"):
        asyncio.run(fetch("localhost:8080"))
    lines = [r.getMessage() for r in caplog.records if "Page requested" in r.getMessage()]
    assert len(lines) == 1 and "plain HTTP" in lines[0] and "Android, Chrome" in lines[0]


def test_describe_device():
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit Version/18.0 Safari/604.1"
    samsung = "Mozilla/5.0 (Linux; Android 14) SamsungBrowser/25.0 Chrome/121.0 Mobile Safari/537.36"
    assert describe_device(iphone) == "iPhone/iPad, Safari"
    assert describe_device(samsung) == "Android, Samsung Internet"


def test_webcam_page_taps_shift_the_driving_phone():
    async def run():
        pad = DryRunPad({"shift_up": "RIGHT_SHOULDER", "shift_down": "LEFT_SHOULDER"})
        app = create_app(dict(CONFIG), pad, TelemetryHub([]), cert_dir=None, https_url=HTTPS_URL)
        async with TestClient(TestServer(app)) as client:
            page = await client.get("/cam", headers={"Host": "localhost:8080"})
            assert page.status == 200 and "Webcam taps" in await page.text()
            phone = await client.ws_connect("/ws?id=p")
            cam = await client.ws_connect("/cam/ws")
            assert (await cam.receive_json()) == {"t": "cam", "phone": False}
            await phone.send_json({"t": "in", "s": 0, "th": 0.5, "br": 0, "b": 0})
            await asyncio.sleep(0.05)
            await cam.send_json({"t": "tap", "side": "right"})
            assert (await cam.receive_json()) == {"t": "tapped", "dir": "up", "button": "RIGHT_SHOULDER"}
            assert (await cam.receive_json()) == {"t": "cam", "phone": True}
            got = []
            while not got or got[-1].get("t") != "gshift":
                got.append(await phone.receive_json())
            assert got[-1] == {"t": "gshift", "dir": "up"}
            await cam.close()
            await phone.close()
    asyncio.run(run())


def test_two_players_drive_their_own_controllers_and_share_bindings():
    async def run():
        made = []

        def factory(bindings):
            made.append(DryRunPad(bindings))
            return made[-1]

        p1_pad = DryRunPad({"shift_up": "RIGHT_SHOULDER", "shift_down": "LEFT_SHOULDER"})
        app = create_app({**CONFIG, "players": 2}, p1_pad, TelemetryHub([]), cert_dir=None,
                         https_url=HTTPS_URL, pad_factory=factory)
        async with TestClient(TestServer(app)) as client:
            one = await client.ws_connect("/ws?id=a&p=1")
            two = await client.ws_connect("/ws?id=b&p=2")
            assert (await one.receive_json())["player"] == 1
            assert (await two.receive_json())["player"] == 2
            assert len(made) == 1                        # Player 2's controller, made on joining
            await one.send_json({"t": "in", "s": 0.5, "th": 1.0, "br": 0, "b": 0})
            await two.send_json({"t": "in", "s": -0.5, "th": 0, "br": 0.7, "b": 2})
            await asyncio.sleep(0.05)
            assert p1_pad.state.steer == 0.5 and p1_pad.state.throttle == 1.0
            assert made[0].state.steer == -0.5 and made[0].state.brake == 0.7
            assert made[0].state.pressed("shift_up") and not p1_pad.state.pressed("shift_up")
            assert not one.closed                        # Player 2 didn't kick Player 1
            # A rebind from Player 2's phone applies to both controllers and both phones hear it.
            await two.send_json({"t": "bind", "buttons": {"shift_up": "A"}})
            for ws in (one, two):
                while (msg := await ws.receive_json())["t"] != "binds":
                    pass
                assert msg["buttons"]["shift_up"] == "A"
            assert p1_pad.bindings["shift_up"] == "A" and made[0].bindings["shift_up"] == "A"
            # No Player 3: falls back to Player 1's slot.
            three = await client.ws_connect("/ws?id=c&p=3")
            while (msg := await three.receive_json())["t"] != "binds":
                pass
            assert msg["player"] == 1 and len(made) == 1
            for ws in (one, two, three):
                await ws.close()
    asyncio.run(run())
