"""One sweep over every parameter-free (or seedable) read endpoint: each must
answer 200 with parseable, non-error JSON. Catches wiring regressions (a moved
module, a renamed function) in one assertion per route — exactly the failure
class a package restructure produces."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from renv import web
from renv.research import claim, db, experiment


def test_every_read_endpoint_answers(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p")
    experiment.create_experiment(con, "p", "001", title="t")
    claim.add_claim(con, "p", "a claim")
    con.close()
    web.Handler.root = str(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    routes = [
        "/api/overview", "/api/papers", "/api/metric_defs", "/api/remotes",
        "/api/sources", "/api/rubric", "/api/connections", "/api/inbox",
        "/api/project/p", "/api/project/p/runs", "/api/graph/p",
        "/api/argument/p", "/api/plan/p", "/api/phases/p", "/api/regions/p",
        "/api/health/p", "/api/search?q=claim",
    ]
    try:
        for r in routes:
            body = json.loads(urllib.request.urlopen(base + r).read())
            assert not (isinstance(body, dict) and body.get("error")), (r, body)
    finally:
        httpd.shutdown()
