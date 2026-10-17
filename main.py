import argparse
import asyncio
import logging
import sys
from pathlib import Path

from aiohttp import web

from server.app import create_app
from server.beamng_mod import install_mod
from server.certs import ensure_certs, lan_ip, server_ssl_context
from server.config import DEFAULTS, load_config
from server.custom import validate_custom
from server.gamepad import DryRunPad, create_pad
from server.keyboard import create_keyboard
from server.state import validate_bindings
from server.telemetry.assetto import AssettoSource
from server.telemetry.beamng import BeamNGSource
from server.telemetry.hub import TelemetryHub
from server.usb import PLATFORM_TOOLS_URL, find_adb, keep_reverse

ROOT = Path(__file__).resolve().parent


def print_banner(url: str, http_url: str | None, pad_name: str, dry_run: bool, usb_port) -> None:
    print()
    print("  PhoneWheel is running")
    print(f"  Controller : {pad_name}")
    if usb_port:
        print(f"  Android over USB: http://localhost:{usb_port}  (see the USB status line below)")
    print(f"  Open on your phone (same Wi-Fi): {url}")
    if http_url:
        print(f"  (or type {http_url}, which forwards there)")
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except ImportError:
        print("  (pip install qrcode to show a QR code here)")
    print("  First visit: your phone warns about the certificate. Choose 'Advanced' >")
    print("  'Proceed' (Android) or 'Show Details' > 'visit this website' (iOS).")
    print("  If Windows Firewall asks, allow Python on private networks.")
    print("  In-game: set steering deadzone to 0 and linearity/gamma to 1 (the phone handles it).")
    print("  Phone can't connect? Each device that reaches this PC is logged below. If yours")
    print("  never shows up, the Wi-Fi blocks it: use --usb (Android) or the phone's hotspot.")
    if dry_run:
        print("  DRY RUN: inputs are received but no controller is created.")
    print("  Ctrl+C to stop.")
    print(flush=True)


async def run(args) -> None:
    config_path = Path(args.config) if args.config else ROOT / "config.json"
    config = load_config(config_path)
    try:
        config["buttons"] = validate_bindings(config["buttons"])
    except ValueError as exc:
        logging.warning("config.json buttons: %s. Using the defaults.", exc)
        config["buttons"] = dict(DEFAULTS["buttons"])
    try:
        config["custom_buttons"] = validate_custom(config["custom_buttons"])
    except ValueError as exc:
        logging.warning("config.json custom_buttons: %s. Starting without them.", exc)
        config["custom_buttons"] = []
    port = args.port or config["port"]
    ip = lan_ip()
    cert_dir = ROOT / "certs"
    cert_path, key_path = ensure_certs(cert_dir, ip)

    pad = create_pad(config["buttons"], asyncio.get_running_loop(), dry_run=args.dry_run)

    sources = []
    if config["beamng"]["enabled"]:
        sources.append(BeamNGSource(config["beamng"]["host"], config["beamng"]["port"],
                                    config["beamng"]["gear_port"]))
    if config["assetto"]["enabled"]:
        sources.append(AssettoSource())
    hub = TelemetryHub(sources)

    https_url = f"https://{ip}:{port}"
    http_port = config["http_port"]
    keyboard = create_keyboard(args.dry_run)
    app = create_app(config, pad, hub, cert_dir, config_path, https_url, keyboard)
    ssl_ctx = server_ssl_context(cert_path, key_path)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, config["host"], port, ssl_context=ssl_ctx).start()
    if http_port:
        try:
            await web.TCPSite(runner, config["host"], http_port).start()
        except OSError as exc:
            # Optional extra port: don't take the whole server down over it.
            logging.warning("Plain HTTP port %d unavailable (%s); USB mode and the short "
                            "http:// address are off. Is another copy of PhoneWheel running?",
                            http_port, exc.strerror or exc)
            http_port = 0

    usb_task = None
    if args.usb:
        adb = find_adb(ROOT)
        if not http_port:
            logging.error("--usb needs http_port in config.json (e.g. 8080).")
        elif adb is None:
            logging.error("--usb: adb not found. Download Android platform-tools from %s and "
                          "unzip it next to main.py (as platform-tools/), or add adb to PATH.",
                          PLATFORM_TOOLS_URL)
        else:
            usb_task = asyncio.create_task(keep_reverse(adb, http_port))

    print_banner(https_url, f"http://{ip}:{http_port}" if http_port else None, pad.name,
                 isinstance(pad, DryRunPad), http_port if usb_task else None)
    try:
        await asyncio.Event().wait()
    finally:
        if usb_task:
            usb_task.cancel()
        await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Phone as a steering wheel for driving sims")
    parser.add_argument("--port", type=int, help="HTTPS port (default from config.json, 8443)")
    parser.add_argument("--config", help="settings file to use instead of config.json")
    parser.add_argument("--dry-run", action="store_true", help="don't create a virtual controller")
    parser.add_argument("--usb", action="store_true",
                        help="Android over USB (adb reverse): no Wi-Fi or certificate needed")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--install-beamng-mod", action="store_true",
                        help="install the BeamNG mod that adds real gear names (P, D, S...) and exit")
    args = parser.parse_args()

    if args.install_beamng_mod:
        try:
            target = install_mod(ROOT)
        except OSError as exc:
            sys.exit(f"Could not install the BeamNG mod: {exc}")
        print(f"Installed the PhoneWheel BeamNG mod to:\n  {target}\n")
        print("In BeamNG: restart the game, then Options > Other > tick 'Other protocols'")
        print("(keep OutGauge on too). The phone then shows P, R, N, D, S... like the car's dash.")
        return

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # QR code block characters
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
