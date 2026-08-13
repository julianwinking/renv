"""Parse SyncTeX (gzip) and answer tex↔PDF queries.

Compile writes ``paper.synctex.gz`` next to the PDF when the engine supports
it (``-synctex=1`` / tectonic ``-Z synctex``). The cockpit uses this for
Overleaf-style jumps; if the file is missing we fall back to searching the
``.tex`` for the clicked snippet (``locate_snippet``).

The ``synctex`` CLI is preferred when it is on PATH (same TeX install that
compiled). The parser here covers the common gzip record format so a machine
without the CLI still jumps.
"""

from __future__ import annotations

import gzip
import re
import shutil
import subprocess
from pathlib import Path

# Input:1:./paper.tex
_INPUT = re.compile(r"^Input:(\d+):(.+)$")
# x<tag>,<line>:<h>,<v>:<W>,<H>,<D>   (optional column after line)
_X = re.compile(
    r"^x(\d+),(\d+)(?::\d+)?:(-?\d+),(-?\d+):"
)


def _alnum(s: str) -> tuple[str, list[int]]:
    norm, idx = [], []
    for i, ch in enumerate(s.lower()):
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            norm.append(ch)
            idx.append(i)
    return "".join(norm), idx


def synctex_path(text_dir: Path, main: str = "paper.tex") -> Path:
    return Path(text_dir) / (Path(main).stem + ".synctex.gz")


def _rel_key(name: str) -> str:
    p = Path(str(name).strip())
    parts = [x for x in p.parts if x not in (".",)]
    return "/".join(parts).lstrip("/")


class SyncTeX:
    """In-memory index of x-records: (path, line) ↔ (page, x_pt, y_pt)."""

    def __init__(self, records: list[dict], files: dict[int, str],
                 unit: float = 1.0, mag: float = 1000.0,
                 xoff: float = 0.0, yoff: float = 0.0):
        self.records = records
        self.files = files
        self.unit = unit or 1.0
        self.mag = mag or 1000.0
        self.xoff = xoff
        self.yoff = yoff

    def _pt(self, h: int, v: int) -> tuple[float, float]:
        scale = (self.unit / 65536.0) * (self.mag / 1000.0)
        return h * scale - self.xoff, v * scale - self.yoff

    def view(self, path: str, line: int) -> dict | None:
        """tex → PDF: first x-record on that source line."""
        want = _rel_key(path)
        tag = None
        for t, name in self.files.items():
            if _rel_key(name) == want or Path(name).name == Path(path).name:
                tag = t
                break
        if tag is None:
            return None
        hits = [r for r in self.records if r["tag"] == tag and r["line"] == line]
        if not hits:
            near = [r for r in self.records if r["tag"] == tag]
            if not near:
                return None
            hits = [min(near, key=lambda r: abs(r["line"] - line))]
        r = hits[0]
        x, y = self._pt(r["h"], r["v"])
        return {"ok": True, "page": r["page"], "x": x, "y": y,
                "path": self.files.get(tag, path), "line": r["line"]}

    def edit(self, page: int, x_pt: float, y_pt: float) -> dict | None:
        """PDF → tex: nearest x-record on that page."""
        on = [r for r in self.records if r["page"] == page]
        if not on:
            return None

        def dist(r):
            px, py = self._pt(r["h"], r["v"])
            return (px - x_pt) ** 2 + (py - y_pt) ** 2

        r = min(on, key=dist)
        x, y = self._pt(r["h"], r["v"])
        return {"ok": True, "page": r["page"], "x": x, "y": y,
                "path": _rel_key(self.files.get(r["tag"], "")),
                "line": r["line"]}


def parse(data: bytes) -> SyncTeX:
    if data[:2] == b"\x1f\x8b":
        text = gzip.decompress(data).decode("utf-8", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace")
    files: dict[int, str] = {}
    records: list[dict] = []
    unit, mag, xoff, yoff = 1.0, 1000.0, 0.0, 0.0
    page = 0
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Input:"):
            m = _INPUT.match(line)
            if m:
                files[int(m.group(1))] = m.group(2).strip()
        elif line.startswith("Unit:"):
            try:
                unit = float(line.split(":", 1)[1])
            except ValueError:
                pass
        elif line.startswith("Magnification:"):
            try:
                mag = float(line.split(":", 1)[1])
            except ValueError:
                pass
        elif line.startswith("X Offset:"):
            try:
                xoff = float(line.split(":", 1)[1])
            except ValueError:
                pass
        elif line.startswith("Y Offset:"):
            try:
                yoff = float(line.split(":", 1)[1])
            except ValueError:
                pass
        elif line.startswith("{") and line[1:].split()[0].isdigit():
            page = int(re.match(r"\{(\d+)", line).group(1))
        elif line.startswith("}"):
            continue
        else:
            m = _X.match(line)
            if m and page:
                records.append({
                    "tag": int(m.group(1)), "line": int(m.group(2)),
                    "h": int(m.group(3)), "v": int(m.group(4)),
                    "page": page,
                })
    return SyncTeX(records, files, unit=unit, mag=mag, xoff=xoff, yoff=yoff)


def load(path: Path) -> SyncTeX | None:
    p = Path(path)
    if not p.is_file():
        return None
    return parse(p.read_bytes())


def _run_cli(args: list[str], cwd: Path) -> dict | None:
    exe = shutil.which("synctex")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, *args], cwd=str(cwd), capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = {}
    for line in (proc.stdout or "").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip().lower()] = v.strip()
    if "page" not in out and "input" not in out:
        return None
    return out


def view_cli(text_dir: Path, path: str, line: int, main: str = "paper.tex") -> dict | None:
    pdf = Path(main).stem + ".pdf"
    raw = _run_cli(["view", "-i", f"{int(line)}:0:{path}", "-o", pdf], text_dir)
    if not raw:
        return None
    try:
        return {
            "ok": True,
            "page": int(float(raw.get("page", "1"))),
            "x": float(raw.get("x", 0)), "y": float(raw.get("y", 0)),
            "path": path, "line": line, "engine": "synctex",
        }
    except ValueError:
        return None


def edit_cli(text_dir: Path, page: int, x: float, y: float,
             main: str = "paper.tex") -> dict | None:
    pdf = Path(main).stem + ".pdf"
    raw = _run_cli(["edit", "-o", f"{int(page)}:{x:.2f}:{y:.2f}:{pdf}"], text_dir)
    if not raw:
        return None
    inp = raw.get("input") or raw.get("file") or ""
    ln = raw.get("line") or "1"
    try:
        return {
            "ok": True, "page": int(page), "x": float(x), "y": float(y),
            "path": _rel_key(inp), "line": int(float(ln)), "engine": "synctex",
        }
    except ValueError:
        return None


def rel_path(text_dir: Path, raw: str) -> str:
    """Turn a SyncTeX input name (absolute, ``./paper.tex``, …) into text/-relative."""
    if not raw:
        return ""
    text_dir = Path(text_dir).resolve()
    p = Path(str(raw).strip())
    try:
        if p.is_absolute():
            return p.resolve().relative_to(text_dir).as_posix()
    except ValueError:
        return p.name
    rel = _rel_key(raw)
    if rel.startswith("text/"):
        rel = rel[5:]
    return rel


def view(text_dir: Path, path: str, line: int, main: str = "paper.tex") -> dict | None:
    sx = load(synctex_path(text_dir, main))
    return sx.view(path, int(line)) if sx else None


def edit(text_dir: Path, page: int, x: float, y: float,
         main: str = "paper.tex") -> dict | None:
    sx = load(synctex_path(text_dir, main))
    return sx.edit(int(page), float(x), float(y)) if sx else None


def locate_snippet(text_dir: Path, query: str, *, prefer: str | None = None) -> dict | None:
    """Map a PDF text snippet back to a ``.tex`` line (whitespace-insensitive)."""
    q, _ = _alnum(query or "")
    if len(q) < 6:
        return None
    text_dir = Path(text_dir)
    ordered: list[Path] = []
    if prefer:
        cand = text_dir / prefer
        if cand.is_file():
            ordered.append(cand)
    ordered.extend(sorted(p for p in text_dir.rglob("*.tex") if p not in ordered))
    needle = q[:96]
    for p in ordered:
        raw = p.read_text(encoding="utf-8", errors="replace")
        n, idx = _alnum(raw)
        at = n.find(needle)
        if at < 0:
            continue
        raw_i = idx[at] if at < len(idx) else 0
        line = raw.count("\n", 0, raw_i) + 1
        return {
            "ok": True, "path": p.relative_to(text_dir).as_posix(),
            "line": line, "offset": raw_i, "engine": "text",
        }
    return None
