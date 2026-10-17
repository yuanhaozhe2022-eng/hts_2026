"""HTTPS for the phone page.

Phone browsers only expose motion sensors on secure pages, so we serve HTTPS with
our own small certificate authority (kept between runs) and a server certificate
for the PC's current LAN IP (re-issued when the IP changes).

By default the phone just accepts a one-time warning. Installing ca.crt on the
phone (served at /ca.crt) removes the warning entirely.
"""

import datetime as dt
import ipaddress
import socket
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def lan_ip() -> str:
    """The IP other devices on the LAN reach this PC at (no packets are sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _name(common_name: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PocketWheel"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])


def _write_key(path: Path, key) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))


def _load_or_create_ca(folder: Path):
    key_path, cert_path = folder / "ca.key", folder / "ca.crt"
    if key_path.exists() and cert_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        return key, x509.load_pem_x509_certificate(cert_path.read_bytes())

    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    name = _name("PocketWheel Local CA")
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_key(key_path, key)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def _cert_covers(cert_path: Path, ip: str) -> bool:
    if not cert_path.exists():
        return False
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    if cert.not_valid_after_utc < dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7):
        return False
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    return ipaddress.ip_address(ip) in san.get_values_for_type(x509.IPAddress)


def server_ssl_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    """TLS settings for the phone page, chosen for compatibility over a LAN.

    Key exchange is pinned to classic X25519. OpenSSL 3.5 would otherwise pick the
    post-quantum X25519MLKEM768, whose ~1.8 kB handshake some managed Wi-Fi gear
    mishandles (seen as Android Chrome failing with ERR_TOO_MANY_RETRIES while an iPhone
    works). Chrome, Safari and Firefox all offer X25519 up front, so nothing is lost.
    """
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(cert_path, key_path)
    ctx.set_ecdh_curve("X25519")
    return ctx


def ensure_certs(folder: Path, ip: str) -> tuple[Path, Path]:
    """Return (cert_path, key_path) for a server cert valid for `ip`."""
    folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = folder / "server.crt", folder / "server.key"
    if _cert_covers(cert_path, ip) and key_path.exists():
        return cert_path, key_path

    ca_key, ca_cert = _load_or_create_ca(folder)
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(ip)).issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        # Apple rejects server certs valid for more than 825 days; stay well under.
        .not_valid_after(now + dt.timedelta(days=397))
        .add_extension(x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.ip_address(ip)),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.DNSName("localhost"),
        ]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                       critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(key_path, key)
    # Send the CA along so phones that installed ca.crt can build the chain.
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM)
                          + ca_cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
