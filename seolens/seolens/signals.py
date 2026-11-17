"""File-drop signals: XXENG x_trends.json and Google Trends CSV exports.

Both are *relative / social* signals. Neither is search volume, and neither feeds the SEO LENS
`demand` term (scores stay separate: Tyler 11-17). Rules:
  - trend_signal null  → unmeasured; never estimated, never shown as 0
  - trend_signal value 0 → measured zero; kept as 0
  - Google Trends values are 0–100 relative interest ("<1" kept as the string, numeric 0.5)
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from .config import sha256_bytes
from .text import phrase_key

# ---------------- XXENG x_trends.json (schema x_trends_sample.v1) ----------------

_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def hashtag_words(tag: str) -> str:
    """#AIAgents → 'ai agents' · #UniversalRuntime → 'universal runtime'."""
    return phrase_key(" ".join(_CAMEL.findall((tag or "").lstrip("#"))))


def _signal(ts) -> dict:
    """Normalise trend_signal (object | number | null). Unmeasured stays None, never 0."""
    if ts is None:
        return {"measured": False, "value": None, "units": "", "window_start": "", "window_end": "", "daily": []}
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return {"measured": True, "value": ts, "units": "", "window_start": "", "window_end": "", "daily": []}
    if isinstance(ts, dict):
        v = ts.get("value")
        daily = []
        for d in ts.get("daily") or []:
            if isinstance(d, dict):  # trimmed samples contain "…" strings: skipped, not guessed
                c = d.get("tweet_count", d.get("count"))
                daily.append(c if isinstance(c, (int, float)) and not isinstance(c, bool) else None)
        return {"measured": isinstance(v, (int, float)) and not isinstance(v, bool),
                "value": v if isinstance(v, (int, float)) and not isinstance(v, bool) else None,
                "units": str(ts.get("units") or ""), "window_start": str(ts.get("window_start") or ""),
                "window_end": str(ts.get("window_end") or ""), "daily": daily}
    raise ValueError(f"trend_signal has unsupported type {type(ts).__name__}")


def momentum(daily: list, n: int):
    """(mean last n ÷ mean first n) − 1, only when ≥2n days were all measured; else None."""
    if len(daily) < 2 * n or any(d is None for d in daily):
        return None
    first, last = sum(daily[:n]) / n, sum(daily[-n:]) / n
    if first == 0:
        return None
    return round(last / first - 1, 4)


def ingest_x(path, cfg: dict) -> dict:
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    if isinstance(data, list):  # bare list of records (older drops)
        data = {"schema_version": "", "records": data}
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError("x_trends file must be an object with records[] (schema x_trends_sample.v1)")
    n = cfg["social"]["momentum_days"]
    recs = []
    for r in data["records"]:
        if not isinstance(r, dict) or not r.get("hashtag"):
            continue
        s = _signal(r.get("trend_signal"))
        recs.append({
            "hashtag": str(r["hashtag"]), "words": hashtag_words(r["hashtag"]), "topic": str(r.get("topic") or ""),
            "source": str(r.get("source") or ""), "measured": s["measured"], "value": s["value"],
            "units": s["units"], "window_start": s["window_start"], "window_end": s["window_end"],
            "days_measured": sum(1 for d in s["daily"] if d is not None), "momentum": momentum(s["daily"], n),
            "related_topics": sorted({str(x) for x in r.get("related_topics") or []}),
            "related_hashtags": sorted({str(x) for x in r.get("related_hashtags") or []}),
            "date": str(r.get("date") or ""),
        })
    phrases = []
    for k, v in sorted((data.get("phrase_counts") or {}).items()):
        if isinstance(v, dict):
            s = _signal(v)
        else:
            s = _signal(v if v is not None else None)
        phrases.append({"phrase": str(k), "words": phrase_key(k), "measured": s["measured"], "value": s["value"],
                        "units": s["units"], "window_start": s["window_start"], "window_end": s["window_end"],
                        "momentum": momentum(s["daily"], n)})
    recs.sort(key=lambda r: (r["hashtag"].lower(), r["topic"]))
    return {"kind": "x_trends", "schema_version": str(data.get("schema_version") or ""),
            "source": {"file": Path(path).name, "sha256": sha256_bytes(raw)}, "records": recs, "phrases": phrases}


# ---------------- Google Trends CSV exports ----------------

TIME_HEADS = {"week", "day", "month", "time", "date"}


def is_trends_csv(text: str) -> bool:
    first = text.lstrip("﻿").splitlines()[0] if text.strip() else ""
    return first.strip().lower().startswith("category:")


def _tval(s: str):
    s = (s or "").strip()
    if s == "<1":
        return 0.5
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def parse_trends(text: str, term: str = "") -> dict:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    out = {"series": {}, "related": []}
    # timeline: header like  Week,ai workflow: (United States)
    for i, r in enumerate(rows):
        if r and r[0].strip().lower() in TIME_HEADS and len(r) > 1 and ":" in r[1]:
            terms = [c.split(":")[0].strip().lower() for c in r[1:]]
            for t in terms:
                out["series"].setdefault(t, [])
            for row in rows[i + 1:]:
                if not row or not row[0].strip():
                    continue
                for t, cell in zip(terms, row[1:]):
                    v = _tval(cell)
                    if v is not None:
                        out["series"][t].append({"date": row[0].strip(), "value": v, "raw": cell.strip()})
            return out
    # related queries / topics: TOP and RISING blocks of  query,value
    section = None
    for r in rows:
        if not r or not any(c.strip() for c in r):
            continue
        head = r[0].strip().upper()
        if head in ("TOP", "RISING") and len(r) == 1:
            section = head
            continue
        if section and len(r) >= 2:
            raw = r[1].strip()
            num = None
            if raw.lower() == "breakout":
                num = None
            elif raw.startswith("+") and raw.endswith("%"):
                num = _tval(raw[1:-1])
            else:
                num = _tval(raw)
            out["related"].append({"term": term.lower(), "section": section, "query": r[0].strip().lower(),
                                   "raw": raw, "value": num})
    return out


def ingest_trends(paths, term: str = "") -> dict:
    data = {"kind": "google_trends", "series": {}, "related": [], "sources": [], "skipped": []}
    for p in sorted(Path(x) for x in paths):
        b = p.read_bytes()
        text = b.decode("utf-8-sig", errors="replace")
        if not is_trends_csv(text):
            data["skipped"].append(f"{p.name} (no 'Category:' line, so not a Google Trends export)")
            continue
        t = parse_trends(text, term or "")
        if not t["series"] and not t["related"]:
            data["skipped"].append(f"{p.name} (no timeline or related-query block found)")
            continue
        for k, v in t["series"].items():
            data["series"][k] = v
        data["related"].extend(t["related"])
        data["sources"].append({"file": p.name, "sha256": sha256_bytes(b),
                                "shape": "timeline" if t["series"] else "related", "term": term})
    data["related"].sort(key=lambda r: (r["term"], r["section"], -(r["value"] or 0), r["query"]))
    return data


def trend_momentum(points: list, recent: int, base: int):
    vals = [p["value"] for p in points]
    if len(vals) < recent + base:
        return None
    b = sum(vals[-(recent + base):-recent]) / base
    if b == 0:
        return None
    return round((sum(vals[-recent:]) / recent) / b - 1, 4)


# ---------------- store ----------------

def write_json(data: dict, work, name: str) -> Path:
    Path(work).mkdir(parents=True, exist_ok=True)
    p = Path(work) / name
    p.write_text(json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return p


def load_json(work, name: str):
    p = Path(work) / name
    return json.loads(p.read_text("utf-8")) if p.exists() else None
