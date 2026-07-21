"""Phase B: the stdlib stdio MCP server — protocol handshake + tool dispatch."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from renv.mcp_server import TOOLS_BY_NAME, handle
from renv.research import db


def _call(root, name, args):
    """Invoke a tool via the JSON-RPC dispatcher; return the parsed result."""
    resp = handle(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": name, "arguments": args}})
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


# --- protocol ----------------------------------------------------------------
def test_initialize_echoes_protocol(tmp_path):
    resp = handle(tmp_path, {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                             "params": {"protocolVersion": "2025-06-18"}})
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert resp["result"]["serverInfo"]["name"] == "renv"


def test_notifications_get_no_reply(tmp_path):
    assert handle(tmp_path, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_exposes_no_handlers(tmp_path):
    resp = handle(tmp_path, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = resp["result"]["tools"]
    assert {t["name"] for t in tools} == set(TOOLS_BY_NAME)
    assert all("handler" not in t for t in tools)   # handler never leaves the process


def test_unknown_method_is_jsonrpc_error(tmp_path):
    resp = handle(tmp_path, {"jsonrpc": "2.0", "id": 3, "method": "bogus"})
    assert resp["error"]["code"] == -32601


# --- tool dispatch over the real store ---------------------------------------
def test_full_research_loop_via_tools(tmp_path):
    db.connect(tmp_path).close()
    _call(tmp_path, "create_project", {"slug": "p", "title": "P"})
    _call(tmp_path, "create_experiment", {"project": "p", "slug": "001", "title": "base"})

    entry = tmp_path / "e.py"
    entry.write_text(
        "import json,os\n"
        "d=os.environ['RENV_RUN_DIR']\n"
        "json.dump({'recall':0.7}, open(d+'/metrics.json','w'))\n")
    run = _call(tmp_path, "run_experiment",
                {"project": "p", "slug": "001", "entrypoint": str(entry), "seed": 1})
    assert run["status"] == "done"
    assert run["metrics"][0]["name"] == "recall"

    # §0 invariant surfaces as a tool error, not a crash
    bad = handle(tmp_path, {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                            "params": {"name": "log_decision",
                                       "arguments": {"project": "p", "type": "result",
                                                     "body": "recall 0.7"}}})
    assert bad["result"]["isError"] is True
    assert "must link" in bad["result"]["content"][0]["text"]

    # with a run it is accepted
    _call(tmp_path, "log_decision", {"project": "p", "type": "result",
                                     "body": "recall 0.7", "runs": [run["id"]]})
    assert _call(tmp_path, "check_invariants", {}) == []


def test_query_tool_is_read_only(tmp_path):
    db.connect(tmp_path).close()
    _call(tmp_path, "create_project", {"slug": "p"})
    rows = _call(tmp_path, "query", {"sql": "SELECT slug FROM project"})
    assert rows == [{"slug": "p"}]
    # a write is refused before it ever reaches the DB
    resp = handle(tmp_path, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                             "params": {"name": "query",
                                        "arguments": {"sql": "DELETE FROM project"}}})
    assert resp["result"]["isError"] is True


# --- end-to-end stdio handshake (real subprocess) ----------------------------
def test_stdio_handshake_subprocess(tmp_path):
    root = Path(__file__).resolve().parents[2]
    msgs = (
        json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    )
    proc = subprocess.run(
        [sys.executable, "-m", "renv.cli", "--corpus", str(tmp_path), "mcp"],
        input=msgs, capture_output=True, text=True, cwd=str(root), timeout=30)
    lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    assert lines[0]["result"]["serverInfo"]["name"] == "renv"   # initialize reply
    assert any("tools" in (l.get("result") or {}) for l in lines)  # tools/list reply
