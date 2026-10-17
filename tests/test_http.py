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
    assert status == 200 and "PhoneWheel" in body


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
