"""On-demand serving: the server exits itself after an idle period."""

from __future__ import annotations

import socket
import threading
import time
import urllib.request

from renv import db, web


def test_server_shuts_down_when_idle(tmp_path):
    db.connect(tmp_path).close()
    # pick a free port
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    t = threading.Thread(
        target=web.serve, args=(str(tmp_path),),
        kwargs={"port": port, "idle_exit": 2}, daemon=True)
    t.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    # traffic resets the idle clock — the server must still be alive after 1.5s
    urllib.request.urlopen(base + "/api/overview")
    time.sleep(1.5)
    urllib.request.urlopen(base + "/api/overview")
    # now go quiet: watchdog (interval 1s, idle 2s) should end serve_forever
    t.join(timeout=8)
    assert not t.is_alive(), "server did not exit after the idle period"
