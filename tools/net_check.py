"""Find out why a phone can't open the PhoneWheel page over Wi-Fi.

    python tools/net_check.py

Stop main.py first. Then open the printed http:// address on the phone and tap both
test links. This window shows every connection attempt and how it ended, which the
real server can't (failed TLS handshakes are silent in Python's web stack):

  - nothing at all          -> the Wi-Fi never delivers the phone's traffic to this PC
  - plain HTTP works only   -> traffic arrives; the problem is TLS
  - one TLS link works      -> that key-exchange setting is the one to use
"""

import socket
import ssl
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.certs import ensure_certs, lan_ip  # noqa: E402

HTTP_PORT, PQ_PORT, CLASSIC_PORT = 8446, 8444, 8445
lock = threading.Lock()


def log(msg: str) -> None:
    with lock:
        print(time.strftime("%H:%M:%S"), msg, flush=True)


def read_request(conn) -> tuple[str, str]:
    conn.settimeout(10)
    data = b""
    while b"\r\n\r\n" not in data and len(data) < 16384:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    lines = data.decode("latin-1").split("\r\n")
    ua = next((l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("user-agent:")), "?")
    return lines[0] if lines else "", ua


def respond(conn, body: str) -> None:
    raw = body.encode()
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                 b"Cache-Control: no-store\r\nConnection: close\r\n"
                 + f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)


def page(title: str, extra: str = "") -> str:
    return (f"<!doctype html><meta name=viewport content='width=device-width'>"
            f"<body style='font:18px system-ui;padding:20px'><h2>{title}</h2>{extra}</body>")


def serve_http(ip: str) -> None:
    srv = socket.create_server(("0.0.0.0", HTTP_PORT))
    while True:
        conn, (peer, _) = srv.accept()
        try:
            line, ua = read_request(conn)
            log(f"[plain HTTP]  {peer}  {line}  | {ua}")
            links = (f"<p><a href='https://{ip}:{PQ_PORT}/'>Test 1: HTTPS, post-quantum key exchange "
                     f"(what the server used before)</a></p>"
                     f"<p><a href='https://{ip}:{CLASSIC_PORT}/'>Test 2: HTTPS, classic X25519 "
                     f"(what the server uses now)</a></p>"
                     "<p>Accept the certificate warning if one appears, then come back and try the other.</p>")
            respond(conn, page("Plain HTTP works: the phone reaches the PC.", links))
        except OSError as exc:
            log(f"[plain HTTP]  {peer}  error: {exc}")
        finally:
            conn.close()


def serve_tls(port: int, label: str, ctx: ssl.SSLContext) -> None:
    srv = socket.create_server(("0.0.0.0", port))
    while True:
        conn, (peer, _) = srv.accept()
        threading.Thread(target=handle_tls, args=(conn, peer, label, ctx), daemon=True).start()


def handle_tls(conn, peer: str, label: str, ctx: ssl.SSLContext) -> None:
    tag = f"[{label}]"
    log(f"{tag}  {peer}  TCP connected")
    try:
        conn.settimeout(10)
        try:
            first = conn.recv(5, socket.MSG_PEEK)
        except OSError as exc:
            log(f"{tag}  {peer}  nothing received ({exc})")
            return
        if not first:
            log(f"{tag}  {peer}  closed before sending anything")
            return
        if first[0] != 0x16:
            log(f"{tag}  {peer}  not a TLS handshake (starts with {first!r})")
            return
        tls = ctx.wrap_socket(conn, server_side=True)
        log(f"{tag}  {peer}  TLS OK: {tls.version()} {tls.cipher()[0]}")
        line, ua = read_request(tls)
        log(f"{tag}  {peer}  {line}  | {ua}")
        respond(tls, page(f"{label}: this works."))
        tls.close()
    except ssl.SSLError as exc:
        if exc.reason == "SSLV3_ALERT_CERTIFICATE_UNKNOWN":
            log(f"{tag}  {peer}  phone rejected the certificate (normal until you accept the warning)")
        else:
            log(f"{tag}  {peer}  TLS handshake failed: {exc.reason or exc}")
    except OSError as exc:
        log(f"{tag}  {peer}  connection error: {exc}")
    finally:
        conn.close()


def main() -> None:
    ip = lan_ip()
    root = Path(__file__).resolve().parent.parent
    cert, key = ensure_certs(root / "certs", ip)

    pq = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)       # OpenSSL default: ML-KEM first
    pq.load_cert_chain(cert, key)
    classic = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    classic.load_cert_chain(cert, key)
    classic.set_ecdh_curve("X25519")

    for target, args in [(serve_http, (ip,)), (serve_tls, (PQ_PORT, "TLS post-quantum", pq)),
                         (serve_tls, (CLASSIC_PORT, "TLS classic", classic))]:
        threading.Thread(target=target, args=args, daemon=True).start()

    print(f"\n  On the phone, open:  http://{ip}:{HTTP_PORT}")
    print("  then tap Test 1 and Test 2. Every attempt is logged below. Ctrl+C to stop.\n", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
