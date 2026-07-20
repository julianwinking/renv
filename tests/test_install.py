"""The one-command installer's pure logic: domain safety, /etc/hosts editing,
dual-stack standalone serving. (launchd + sudo paths need a real machine.)"""

from __future__ import annotations

import socket
import ssl
import subprocess
import threading
import time
import urllib.request

import pytest

from reref import db, web


def test_safe_domain():
    assert web.is_safe_domain("research.test")
    assert web.is_safe_domain("cockpit.localhost")
    assert web.is_safe_domain("foo.local")
    assert not web.is_safe_domain("research.com")
    assert not web.is_safe_domain("example.org")


def test_compose_hosts_idempotent_dedup_and_preserve():
    domains = ["research.test", "research.com"]
    start = ("127.0.0.1 localhost\n"
             "::1 localhost\n"
             "127.0.0.1 research.com\n"      # a stray + duplicate we should absorb
             "127.0.0.1 research.com\n"
             "10.0.0.9 fileserver\n")
    once = web.compose_hosts(start, domains)
    twice = web.compose_hosts(once, domains)
    assert once == twice                                   # idempotent
    assert "10.0.0.9 fileserver" in once                   # unrelated line kept
    assert "127.0.0.1 localhost" in once                   # other loopback kept
    assert once.count("127.0.0.1 research.com") == 1       # dedup
    assert "::1 research.test" in once and "::1 research.com" in once
    assert once.count(web._HOSTS_BEGIN) == 1
    # managed block removal (uninstall path) leaves no marker
    body = once.split(web._HOSTS_BEGIN)[0]
    assert web._HOSTS_BEGIN not in body and web._HOSTS_END not in body


def test_hosts_block_has_both_stacks():
    block = web.hosts_block(["x.test"])
    assert "127.0.0.1 x.test" in block and "::1 x.test" in block


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_standalone_serves_both_ip_stacks(tmp_path):
    """serve() binds 127.0.0.1 AND ::1 — the fix that makes Safari (IPv6-first)
    reach the local override, not just Chrome."""
    db.connect(tmp_path).close()
    # a throwaway self-signed cert so we exercise the TLS + dual-stack path
    key = tmp_path / "k.pem"
    crt = tmp_path / "c.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(crt), "-days", "1",
         "-subj", "/CN=localhost",
         "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1"],
        check=True, capture_output=True)
    port = _free_port()
    t = threading.Thread(
        target=web.serve, args=(str(tmp_path),),
        kwargs={"port": port, "tls_cert": str(crt), "tls_key": str(key),
                "idle_exit": 6}, daemon=True)
    t.start()
    time.sleep(0.6)

    noverify = ssl.create_default_context()
    noverify.check_hostname = False
    noverify.verify_mode = ssl.CERT_NONE
    for addr in ("127.0.0.1", "::1"):
        host = f"[{addr}]" if ":" in addr else addr
        try:
            r = urllib.request.urlopen(
                f"https://{host}:{port}/api/overview", context=noverify, timeout=3)
        except OSError as e:
            if addr == "::1":
                pytest.skip(f"no IPv6 loopback on this host: {e}")
            raise
        assert r.status == 200, f"{addr} did not serve"
