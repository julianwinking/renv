"""The web cockpit — API endpoints over the store (handler-level + a live server)."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from renv import web
from renv.research import claim, db, experiment, finding, review


def _seed(tmp_path):
    con = db.connect(tmp_path)
    db.ensure_project(con, "p", title="P")
    (tmp_path / "projects" / "p" / "text").mkdir(parents=True)
    (tmp_path / "projects" / "p" / "text" / "paper.tex").write_text(
        "\\begin{abstract}recall 0.990\\end{abstract}\n\\bibliography{references}\n")
    experiment.create_experiment(con, "p", "001", hypothesis="h")
    entry = tmp_path / "e.py"
    entry.write_text("import json,os\njson.dump({'r':0.5},open(os.environ['RENV_RUN_DIR']+'/metrics.json','w'))\n")
    experiment.run_experiment(con, "p", "001", entrypoint=str(entry), root=str(tmp_path))
    claim.add_claim(con, "p", "key contribution", kind="contribution")
    review.review(con, str(tmp_path), "p")  # produces findings
    return con


def test_overview_and_project_payloads(tmp_path):
    _seed(tmp_path)
    con = db.connect(tmp_path)
    o = web._overview(con)
    assert o["counts"]["experiment"] == 1 and o["counts"]["claim"] == 1
    assert o["projects"][0]["slug"] == "p"
    proj = web._project(con, "p")
    assert proj["experiments"] and proj["findings"] and proj["claims"]


def test_live_server_get_and_post(tmp_path):
    _seed(tmp_path)
    web.Handler.root = str(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        # index served
        assert b"cockpit" in urllib.request.urlopen(base + "/").read()
        # api read
        ov = json.loads(urllib.request.urlopen(base + "/api/overview").read())
        assert ov["counts"]["paper"] == 0
        proj = json.loads(urllib.request.urlopen(base + "/api/project/p").read())
        fid = proj["findings"][0]["id"]
        # api write goes through the domain layer (adjudicate a finding)
        req = urllib.request.Request(
            base + "/api/finding/adjudicate", method="POST",
            data=json.dumps({"id": fid, "verdict": "reject", "reasoning": "intended prose"}).encode(),
            headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req).read())
        assert res["status"] == "rejected"
        # the verdict persisted in the store
        assert finding.get_finding(db.connect(tmp_path), fid)["status"] == "rejected"
    finally:
        httpd.shutdown()


# --- no cockpit build: the server explains itself instead of shipping a
# second, drifting mini-UI ----------------------------------------------------
def test_unbuilt_cockpit_serves_build_instructions(tmp_path, monkeypatch):
    from renv import web
    monkeypatch.setattr(web, "DIST", tmp_path / "nowhere" / "dist")
    web.Handler.root = str(tmp_path)
    db.connect(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_port}"
        body = urllib.request.urlopen(f"{base}/").read().decode()
        assert "npm run build" in body and "cockpit" in body
        # deep links still resolve to the instructions page, assets stay honest 404s
        assert "npm run build" in urllib.request.urlopen(f"{base}/overview").read().decode()
        try:
            urllib.request.urlopen(f"{base}/assets/app-abc123.js")
            raise AssertionError("missing asset must 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown()
