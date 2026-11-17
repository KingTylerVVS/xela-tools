"""export-sheet: append-ready rows for the µ SEO BRAIN KEYWORDS sheet (BOT✦TRADER side).

Matches the live tab headers (read 2026-11-17):
  Keywords:     kw_id, keyword, cluster, intent, tier, target_url, added_date, source
  Observations: date, kw_id, source, volume, impressions, clicks, position, kd, serp_features   (append-only)

Rules carried from the sheet's own Rules tab:
  - Observations.volume for source x_counts = 7-day English non-retweet X post count, NOT search volume
  - never invent Google volume: volume stays blank for every other source; null X stays blank
  - kd / serp_features stay blank (no source connected)
SEO LENS writes files only. Pasting into the sheet is a separate, approved step.
Google Trends has no column in Observations yet, so Trends rows are reported, not exported.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

KEYWORD_COLS = ["kw_id", "keyword", "cluster", "intent", "tier", "target_url", "added_date", "source"]
OBS_COLS = ["date", "kw_id", "source", "volume", "impressions", "clicks", "position", "kd", "serp_features"]


def _read(path) -> list[dict]:
    if not path:
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _day(s: str) -> str:
    m = re.match(r"\d{4}-\d{2}-\d{2}", s or "")
    return m.group(0) if m else ""


def _num(v):
    if v is None or v == "":
        return ""
    return int(v) if isinstance(v, (int, float)) and float(v).is_integer() else round(float(v), 2)


def build_sheet_rows(keywords_csv=None, observations_csv=None, xt=None, gsc=None, as_of: str = "",
                     res=None, add_queries: bool = True):
    kws = _read(keywords_csv)
    have_obs = {(r.get("date", ""), r.get("kw_id", ""), r.get("source", "")) for r in _read(observations_csv)}
    by_kw = {(r.get("keyword") or "").strip().lower(): r["kw_id"] for r in kws if r.get("kw_id")}
    nums = [int(m.group(1)) for r in kws if (m := re.match(r"KW(\d+)$", r.get("kw_id") or ""))]
    nxt = max(nums, default=0) + 1
    new_kw, obs, notes = [], [], []

    def kw_id(keyword: str, source: str, target: str = "") -> str:
        nonlocal nxt
        key = keyword.strip().lower()
        if key not in by_kw:
            kid = f"KW{nxt:03d}"
            nxt += 1
            by_kw[key] = kid
            new_kw.append({"kw_id": kid, "keyword": keyword, "cluster": "", "intent": "", "tier": "HOLD",
                           "target_url": target, "added_date": as_of, "source": source})
        return by_kw[key]

    def add(row):
        k = (row["date"], row["kw_id"], row["source"])
        if k in have_obs:
            notes.append(f"skip duplicate {k}")
            return
        have_obs.add(k)
        obs.append(row)

    if xt:
        seen = set()
        for r in sorted(xt["records"], key=lambda r: (r["hashtag"].lower(), -r["days_measured"], r["topic"])):
            if r["hashtag"].lower() in seen:
                continue
            seen.add(r["hashtag"].lower())
            d = _day(r["date"]) or as_of
            if not d:
                notes.append(f"no date for {r['hashtag']}; skipped")
                continue
            add({"date": d, "kw_id": kw_id(r["hashtag"], "x_counts"), "source": "x_counts",
                 "volume": _num(r["value"]) if r["measured"] else "", "impressions": "", "clicks": "",
                 "position": "", "kd": "", "serp_features": ""})
    if gsc and gsc.get("queries"):
        if not as_of:
            notes.append("Search Console rows need --as-of (the export has no date); skipped")
        else:
            for q in sorted(gsc["queries"], key=lambda q: q["query"]):
                key = q["query"].strip().lower()
                if key not in by_kw and not add_queries:
                    continue
                target = ""
                if res is not None:
                    target = res.best_page(" ".join(key.split()))[0]
                add({"date": as_of, "kw_id": kw_id(q["query"], "gsc", target), "source": "gsc", "volume": "",
                     "impressions": q["impressions"], "clicks": q["clicks"], "position": _num(q["position"]),
                     "kd": "", "serp_features": ""})
    return new_kw, obs, notes


def write_sheet_rows(out_dir, new_kw, obs, notes) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, cols, rows in (("keywords_append.csv", KEYWORD_COLS, new_kw), ("observations_append.csv", OBS_COLS, obs)):
        with (out / name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    (out / "sheet_notes.txt").write_text(
        "\n".join(["KEYWORDS sheet export · paste = append only · B1 kill switch applies (practice mode)",
                   "volume = X posts for x_counts only, never search volume; blank = not measured", ""] + notes) + "\n",
        "utf-8")
    return {"keywords_new": len(new_kw), "observations": len(obs), "notes": len(notes)}
