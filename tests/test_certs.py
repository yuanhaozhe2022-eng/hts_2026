import ipaddress

from cryptography import x509

from server.certs import ensure_certs


def test_server_cert_covers_ip_and_is_reissued_when_ip_changes(tmp_path):
    cert_path, key_path = ensure_certs(tmp_path, "192.168.1.50")
    assert key_path.exists() and (tmp_path / "ca.crt").exists()
    first = cert_path.read_bytes()

    leaf = x509.load_pem_x509_certificate(first)
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("192.168.1.50") in san.get_values_for_type(x509.IPAddress)

    ensure_certs(tmp_path, "192.168.1.50")
    assert cert_path.read_bytes() == first  # same IP: reused

    ca_before = (tmp_path / "ca.crt").read_bytes()
    ensure_certs(tmp_path, "10.0.0.7")
    assert cert_path.read_bytes() != first  # new IP: new server cert...
    assert (tmp_path / "ca.crt").read_bytes() == ca_before  # ...from the same CA
