"""ingest: Google Search Console CSV exports → gsc.json (never logs in anywhere).

Accepts the UI export zip or loose CSVs. Recognised tables:
  queries  (Top queries / Query + metrics)
  pages    (Top pages / Page + metrics)
  pairs    (query AND page columns: API, Looker Studio, Search Analytics for Sheets)
Other tables in the zip (Countries, Devices, Dates, Filters, …) are listed as skipped.
Duplicate keys across files: the row with more impressions wins (no double counting).
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path

from .config import sha256_bytes
from .harvest import normalize_url

FIELDS = {
    "query": {"query", "queries", "top queries", "search query"},
    "page": {"page", "pages", "top pages", "landing page", "url", "address"},
    "clicks": {"clicks", "url clicks"},
    "impressions": {"impressions"},
    "ctr": {"ctr", "url ctr"},
    "position": {"position", "average position", "avg. position", "avg position"},
}


def _canon(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def _num(v) -> float:
    s = str(v or "").strip().replace(",", "").replace("%", "")
    if s in ("", "-", "—"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_table(text: str):
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return "empty", []
    idx = {}
    for i, h in enumerate(header):
        ch = _canon(h)
        for f, aliases in FIELDS.items():
            if ch in aliases and f not in idx:
                idx[f] = i
    has_q, has_p = "query" in idx, "page" in idx
    shape = "pairs" if has_q and has_p else "queries" if has_q else "pages" if has_p else "other"
    if shape == "other":
        return shape, []
    rows = []
    for r in reader:
        if not any(c.strip() for c in r):
            continue

        def cell(f):
            i = idx.get(f)
            return r[i] if i is not None and i < len(r) else ""

        clicks, impr = int(_num(cell("clicks"))), int(_num(cell("impressions")))
        raw_ctr = cell("ctr")
        if raw_ctr.strip():
            ctr = _num(raw_ctr) / (100.0 if "%" in raw_ctr else 1.0)
        else:
            ctr = clicks / impr if impr else 0.0
        rec = {"clicks": clicks, "impressions": impr, "ctr": round(ctr, 6),
               "position": round(_num(cell("position")), 4)}
        if has_q:
            rec["query"] = re.sub(r"\s+", " ", cell("query").strip().lower())
            if not rec["query"]:
                continue
        if has_p:
            rec["page"] = normalize_url(cell("page"))
            if not rec["page"]:
                continue
        rows.append(rec)
    return shape, rows


def _tables(path: Path):
    data = path.read_bytes()
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in sorted(z.namelist()):
                if name.lower().endswith(".csv"):
                    b = z.read(name)
                    yield path.name, name, b
    else:
        yield path.name, None, data


def ingest(paths) -> dict:
    keyed = {"queries": {}, "pages": {}, "pairs": {}}
    sources, skipped = [], []
    for p in sorted(Path(x) for x in paths):
        for fname, member, b in _tables(p):
            shape, rows = parse_table(b.decode("utf-8-sig", errors="replace"))
            label = f"{fname}:{member}" if member else fname
            if shape in ("other", "empty"):
                skipped.append(label)
                continue
            sources.append({"file": label, "sha256": sha256_bytes(b), "shape": shape, "rows": len(rows)})
            for r in rows:
                key = r.get("query", "") + "\t" + r.get("page", "")
                cur = keyed[shape].get(key)
                if cur is None or r["impressions"] > cur["impressions"]:
                    keyed[shape][key] = r
    out = {k: [v[key] for key in sorted(v)] for k, v in keyed.items()}
    out["sources"] = sources
    out["skipped"] = skipped
    return out


def write_gsc(data: dict, work) -> Path:
    out = Path(work) / "gsc.json"
    Path(work).mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return out


def load_gsc(work) -> dict:
    p = Path(work) / "gsc.json"
    if not p.exists():
        return {"queries": [], "pages": [], "pairs": [], "sources": [], "skipped": [], "missing": True}
    return json.loads(p.read_text("utf-8"))
