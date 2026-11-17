"""report: CSVs + report.md + report.json (+ receipt) from one in-memory score/cluster pass.

Suggestions are deterministic templates built from the page's own phrases and sentences. Draft only:
SEO LENS never edits Blogger.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .bridges import find_bridges
from .cluster import build_clusters
from .signals import trend_momentum
from .score import ScoreResult, score
from .text import Lexicon, phrase_key, segments


def f4(x):
    return "" if x is None else f"{x:.4f}"


def f1(x):
    return "" if x is None else f"{x:.1f}"


def write_csv(path: Path, header: list[str], rows: list[list]):
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


# ---------- plain-language rendering ----------

def _up(t: str) -> str:
    return "".join(ch if ch == "µ" else ch.upper() for ch in t)


def render(phrase: str, lex: Lexicon, expand: dict, cap=True, acronyms=("ai",)) -> str:
    out = []
    for i, t in enumerate(phrase.split(" ")):
        if t in expand:
            out.append(expand[t])
        elif t in acronyms:
            out.append(t.upper())
        elif lex.is_glyph(t):
            out.append(_up(t))
        elif cap and (i == 0 or not lex.is_stop(t)):
            out.append(t[:1].upper() + t[1:])
        else:
            out.append(t)
    return " ".join(out)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:70].strip("-")


def _trim(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n:
        return s
    cut = s[: n - 1].rsplit(" ", 1)[0].rstrip(",;:-–— ")
    return cut + "…"


def _sentence_with(text: str, p1: str) -> str:
    for seg in segments(text, lower=False):
        if f" {p1} " in f" {phrase_key(seg)} " and len(seg.split()) >= 5:
            return seg.strip()
    return ""


def page_suggestions(res: ScoreResult, clusters: list, cfg: dict, lex: Lexicon) -> list[dict]:
    R, expand = cfg["report"], cfg.get("expand", {})
    ac = tuple(R.get("acronyms", ()))
    by_pp = {(r["phrase"], r["page"]): r for r in res.rows}
    owner_of = {m: c["owner"] for c in clusters for m in c["members"]}
    out = []
    for rec in res.pages:
        url = rec["url"]
        # the page's own phrases, minus phrases another page owns (unless only this page has them)
        pool = {p for p in res.fit.get(url, {})
                if owner_of.get(p, url) == url or by_pp[(p, url)]["df"] == 1}
        plain = [p for p in pool if lex.glyph_frac(p.split(" ")) == 0]
        # glyph phrases are usable only if every glyph token has a plain-words expansion
        mixed = [p for p in pool if lex.glyph_frac(p.split(" ")) > 0
                 and all(t in expand for t in p.split(" ") if lex.is_glyph(t))]
        cands = plain or mixed
        notes = []
        if not cands:
            out.append({"page": url, "kind": rec.get("kind", ""), "current_title": rec.get("title", ""),
                        "current_h1": rec.get("h1", ""), "current_description": rec.get("description", ""),
                        "suggested_title": "", "suggested_h1": "", "suggested_description": "",
                        "top_phrases": "", "why": "", "notes": "only glyph phrases found; write plain-language copy"})
            continue

        def key(p):
            r = by_pp.get((p, url), {})
            return (-r.get("impressions", 0), -(len(p.split(" ")) >= 2), -round(r.get("total", 0), 9), p)

        ranked = sorted(cands, key=key)
        p1 = ranked[0]
        # prefer the fuller phrase ("free workflow" → "free workflow templates") when nearly as strong
        while True:
            f1_ = by_pp[(p1, url)]["fit"]
            longer = sorted((p for p in cands if p != p1 and f" {p1} " in f" {p} "
                             and len(p.split(" ")) <= 4 and by_pp[(p, url)]["fit"] >= 0.75 * f1_),
                            key=lambda p: (-by_pp[(p, url)]["fit"], len(p), p))
            if not longer:
                break
            p1 = longer[0]
        ranked = [p1] + [p for p in ranked if p != p1]
        p2 = next((p for p in ranked[1:] if len(p.split(" ")) >= 2
                   and not set(p.split(" ")) & set(p1.split(" "))), None)
        t1 = render(p1, lex, expand, acronyms=ac)
        title = t1
        if p2:
            cand = f"{t1} — {render(p2, lex, expand, acronyms=ac)}"
            if len(cand) <= R["title_max"]:
                title = cand
        title = _trim(title, R["title_max"])
        sent = _sentence_with(rec.get("text", ""), p1)
        if sent and sent[-1] not in ".!?…":
            sent += "."
        desc = _trim(sent if sent else R["description_fallback"].format(P1=t1), R["description_max"])
        cur_title = rec.get("title", "")
        ct = [t for seg in segments(cur_title) for t in seg.split()]
        if ct and lex.is_glyph(ct[0].strip("-_'’")):
            notes.append("current title starts with a glyph")
        if not rec.get("description"):
            notes.append("no meta description found" + (" (feed source)" if rec.get("source") == "feed" else ""))
        if not sent:
            notes.append("description from template; no page sentence contains the phrase")
        r1 = by_pp.get((p1, url), {})
        why = f"'{p1}': fit {r1.get('fit', 0):.2f}"
        if r1.get("impressions"):
            why += f", {r1['impressions']} impr"
            if r1.get("position") is not None:
                why += f", pos {r1['position']:.1f} ({r1.get('link') or 'site'})"
            if "LOW-DATA" in r1.get("flags", ""):
                notes.append("LOW-DATA")
        out.append({"page": url, "kind": rec.get("kind", ""), "current_title": cur_title,
                    "current_h1": rec.get("h1", ""), "current_description": rec.get("description", ""),
                    "suggested_title": title, "suggested_h1": _trim(t1, R["title_max"]),
                    "suggested_description": desc, "top_phrases": " | ".join(ranked[:5]), "why": why,
                    "notes": "; ".join(notes)})
    return out


# ---------- main ----------

OUTPUTS = ["scores.csv", "clusters.csv", "quick_wins.csv", "gaps.csv", "page_suggestions.csv",
           "cannibalization.csv", "bridges.csv", "social.csv", "trends.csv", "observations.csv",
           "report.json", "report.md"]

X_NOTE = "X posts, not search volume"
T_NOTE = "relative interest 0-100, not volume"


def _on_site(best):
    url, f, c = best
    return "YES" if f >= 0.10 else ("MENTIONED" if c > 0 else "NO")


def _signals(res, cfg, xt, tr, as_of):
    """social.csv, trends.csv and observations.csv rows. Nothing here touches the score."""
    social, trends, obs = [], [], []
    trend_words = set()
    if xt:
        tags = {}
        for r in xt["records"]:
            tags.setdefault(r["hashtag"].lower(), []).append(r)
        for key in sorted(tags):
            g = tags[key]
            r = sorted(g, key=lambda x: (-x["days_measured"], x["topic"]))[0]   # fullest record
            vals = {x["value"] for x in g}
            note = X_NOTE + ("; CONFLICTING values across records" if len(vals) > 1 else "")
            best = res.best_page(r["words"])
            trend_words.add(r["words"])
            social.append(["hashtag", r["hashtag"], r["words"], " | ".join(sorted({x["topic"] for x in g if x["topic"]})),
                           "" if not r["measured"] else r["value"], "TRUE" if r["measured"] else "FALSE",
                           r["window_end"], f4(r["momentum"]), best[0], f4(best[1]), _on_site(best), note])
            obs.append([r["date"] or as_of, "x_trends", r["hashtag"], "x_posts_7d",
                        "" if not r["measured"] else r["value"], r["units"], r["window_start"], r["window_end"],
                        "TRUE" if r["measured"] else "FALSE", X_NOTE])
        for p in xt["phrases"]:
            best = res.best_page(p["words"])
            trend_words.add(p["words"])
            social.append(["phrase", p["phrase"], p["words"], "", "" if not p["measured"] else p["value"],
                           "TRUE" if p["measured"] else "FALSE", p["window_end"], f4(p["momentum"]), best[0],
                           f4(best[1]), _on_site(best), X_NOTE])
            obs.append([as_of, "x_trends", p["phrase"], "x_posts_7d", "" if not p["measured"] else p["value"],
                        p["units"], p["window_start"], p["window_end"], "TRUE" if p["measured"] else "FALSE", X_NOTE])
    if tr:
        T = cfg["trends"]
        for term in sorted(tr["series"]):
            pts = tr["series"][term]
            mom = trend_momentum(pts, T["recent_points"], T["base_points"])
            words = phrase_key(term)
            trend_words.add(words)
            best = res.best_page(words)
            last = pts[-1] if pts else {"date": "", "raw": ""}
            trends.append(["timeline", term, "", len(pts), last["raw"], f4(mom), best[0], f4(best[1]), _on_site(best), T_NOTE])
            obs.append([last["date"], "google_trends", term, "trends_interest_latest", last["raw"], "relative 0-100",
                        pts[0]["date"] if pts else "", last["date"], "TRUE" if pts else "FALSE", T_NOTE])
            if mom is not None:
                obs.append([last["date"], "google_trends", term, "trends_momentum", f4(mom), "ratio",
                            pts[0]["date"], last["date"], "TRUE", T_NOTE])
        for r in tr["related"]:
            words = phrase_key(r["query"])
            trend_words.add(words)
            best = res.best_page(words)
            trends.append([f"related_{r['section'].lower()}", r["query"], r["term"], "", r["raw"], "", best[0],
                           f4(best[1]), _on_site(best), T_NOTE])
    for q in sorted(res.qagg):
        a = res.qagg[q]
        for metric, v in (("gsc_impressions", a["impressions"]), ("gsc_clicks", a["clicks"]),
                          ("gsc_avg_position", a["position"])):
            obs.append([as_of, "search_console", q, metric, v, "count" if metric != "gsc_avg_position" else "rank",
                        "", "", "TRUE", "Search Console export"])
    obs.sort(key=lambda o: (o[1], o[2].lower(), o[3], str(o[0])))
    return social, trends, obs, trend_words


def build_report(corpus, gsc, cfg, lex: Lexicon, out_dir, xt=None, tr=None, as_of: str = "") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    R, expand = cfg["report"], cfg.get("expand", {})
    ac = tuple(R.get("acronyms", ()))
    res = score(corpus, gsc, cfg, lex)
    clusters = build_clusters(res, cfg, lex)
    cid = {m: c["cluster_id"] for c in clusters for m in c["members"]}
    owner = {c["cluster_id"]: c["owner"] for c in clusters}

    # scores.csv (top rows per page; scoring used all rows)
    per_page, srows = {}, []
    for r in res.rows:
        k = per_page.get(r["page"], 0)
        if R["scores_per_page"] and k >= R["scores_per_page"] and r["count"] > 0:
            continue
        per_page[r["page"]] = k + 1
        c = cid.get(r["phrase"], "")
        srows.append([r["phrase"], r["page"], r["n"], r["count"], r["df"], r["impressions"], r["link"],
                      r["link_impressions"], r["link_clicks"], f1(r["position"]), f4(r["demand"]),
                      f4(r["quickwin"]), f4(r["fit"]), f4(r["distinct"]), f4(r["penalty"]), f4(r["total"]),
                      r["flags"], c, owner.get(c, "")])
    write_csv(out / "scores.csv",
              ["phrase", "page", "n", "count", "df", "impressions", "link", "link_impressions", "link_clicks",
               "position", "demand", "quickwin", "fit", "distinct", "penalty", "total", "flags",
               "cluster", "cluster_owner"], srows)

    write_csv(out / "clusters.csv",
              ["cluster", "seed", "size", "impressions_sum", "owner", "owner_basis", "owner_coverage", "severity",
               "competitors", "members"],
              [[c["cluster_id"], c["seed"], c["size"], c["demand"], c["owner"], c["owner_basis"],
                f4(c["owner_coverage"]), c["severity"],
                " | ".join(f"{x['page']} (fit {x['max_fit']:.2f}, impr {x['impressions']})" for x in c["competitors"]),
                " | ".join(c["members"][:25])] for c in clusters])

    qw = [r for r in res.rows if r["quickwin"] > 0]
    write_csv(out / "quick_wins.csv",
              ["phrase", "page", "impressions", "link", "link_impressions", "link_clicks", "position", "fit",
               "total", "flags", "action"],
              [[r["phrase"], r["page"], r["impressions"], r["link"], r["link_impressions"], r["link_clicks"],
                f1(r["position"]), f4(r["fit"]), f4(r["total"]), r["flags"],
                "add phrase to title/H1/intro" if r["count"] == 0 or r["fit"] < 0.5 else "tighten title/description"]
               for r in qw])

    gap_rows = []
    for g in res.gaps:
        plain = render(g["phrase"], lex, expand, acronyms=ac)
        action = "NEW POST" if not g["best_page"] else "EXTEND best page or NEW POST"
        gap_rows.append([g["phrase"], g["impressions"], g["clicks"], f1(g["position"]), g["best_page"],
                         f4(g["best_fit"]), g["gsc_pages"], action, _trim(plain, R["title_max"]),
                         "/" + slugify(plain) + ".html"])
    write_csv(out / "gaps.csv",
              ["phrase", "impressions", "clicks", "position", "best_page", "best_fit", "gsc_pages", "action",
               "suggested_title", "suggested_slug"], gap_rows)

    sugg = page_suggestions(res, clusters, cfg, lex)
    keys = ["page", "kind", "current_title", "current_h1", "current_description", "suggested_title",
            "suggested_h1", "suggested_description", "top_phrases", "why", "notes"]
    write_csv(out / "page_suggestions.csv", keys, [[s[k] for k in keys] for s in sugg])

    sev_rank = {"HIGH": 0, "MED": 1, "LOW": 2}
    cann = sorted([c for c in clusters if c["severity"]],
                  key=lambda c: (sev_rank[c["severity"]], -c["demand"], c["cluster_id"]))
    write_csv(out / "cannibalization.csv",
              ["cluster", "severity", "seed", "impressions_sum", "owner", "owner_basis", "competitors", "members"],
              [[c["cluster_id"], c["severity"], c["seed"], c["demand"], c["owner"], c["owner_basis"],
                " | ".join(f"{x['page']} (fit {x['max_fit']:.2f}, impr {x['impressions']})" for x in c["competitors"]),
                " | ".join(c["members"][:25])] for c in cann])

    social, trend_rows, obs, trend_words = _signals(res, cfg, xt, tr, as_of)
    write_csv(out / "social.csv", ["kind", "term", "words", "topics", "x_posts", "measured", "window_end", "momentum",
                                   "best_page", "best_fit", "on_site", "note"], social)
    write_csv(out / "trends.csv", ["kind", "query", "for_term", "points", "latest_or_value", "momentum", "best_page",
                                   "best_fit", "on_site", "note"], trend_rows)
    write_csv(out / "observations.csv", ["as_of", "source", "keyword", "metric", "value", "units", "window_start",
                                         "window_end", "measured", "note"], obs)
    bridges, gate = find_bridges(res, cfg, lex, trend_words, clusters)
    write_csv(out / "bridges.csv", ["page_a", "page_b", "similarity", "shared", "anchor_a_to_b", "anchor_b_to_a",
                                    "rationale", "bridge_angle"],
              [[b["page_a"], b["page_b"], f4(b["similarity"]), " | ".join(b["shared"]), b["anchor_a_to_b"],
                b["anchor_b_to_a"], b["rationale"], b["bridge_angle"]] for b in bridges])

    meta = dict(res.meta, clusters=len(clusters), quick_wins=len(qw), gaps=len(res.gaps),
                bridges=len(bridges), bridge_gate=gate, x_terms=len(social), trends_rows=len(trend_rows),
                observations=len(obs),
                cannibal_high=sum(c["severity"] == "HIGH" for c in clusters),
                cannibal_med=sum(c["severity"] == "MED" for c in clusters),
                cannibal_low=sum(c["severity"] == "LOW" for c in clusters))
    top = R["top_n"]
    bot = {
        "meta": meta,
        "weights": cfg["weights"],
        "quick_wins": [{k: r[k] for k in ("phrase", "page", "link", "link_impressions", "position", "total")} for r in qw[:top]],
        "gaps": [{"phrase": g[0], "impressions": g[1], "action": g[7], "suggested_title": g[8], "suggested_slug": g[9]} for g in gap_rows[:top]],
        "cannibalization": [{"cluster": c["cluster_id"], "severity": c["severity"], "seed": c["seed"], "owner": c["owner"],
                             "competitors": [x["page"] for x in c["competitors"]]} for c in cann if c["severity"] != "LOW"][:top],
        "page_suggestions": [{k: s[k] for k in ("page", "suggested_title", "suggested_h1", "suggested_description")} for s in sugg],
        "bridges": [{k: b[k] for k in ("page_a", "page_b", "anchor_a_to_b", "anchor_b_to_a", "rationale", "bridge_angle")}
                    for b in bridges],
        "social_note": X_NOTE, "trends_note": T_NOTE,
    }
    (out / "report.json").write_text(json.dumps(bot, sort_keys=True, ensure_ascii=False, indent=1,
                                                default=lambda o: round(o, 6)) + "\n", "utf-8")
    (out / "report.md").write_text(_markdown(meta, cfg, qw, gap_rows, cann, sugg, top, bridges, gate, social,
                                             trend_rows), "utf-8")
    return {"meta": meta, "outputs": OUTPUTS}


def _md_cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _markdown(meta, cfg, qw, gap_rows, cann, sugg, top, bridges=(), gate=None, social=(), trend_rows=()) -> str:
    W, T = cfg["weights"], cfg["thresholds"]
    L = ["# SEO LENS report", "",
         "Draft suggestions only. SEO LENS never edits the site.", "",
         "## Data", "",
         "| item | value |", "|---|---|",
         f"| pages (/p/) | {meta['pages']} |", f"| posts | {meta['posts']} |", f"| words | {meta['words']} |",
         f"| phrases scored | {meta['phrases']} |", f"| GSC queries | {meta['queries']} |",
         f"| GSC query×page rows | {meta['pair_rows']} |", f"| GSC impressions (sum) | {meta['impressions_total']} |",
         f"| clusters | {meta['clusters']} |", ""]
    if not meta["has_gsc"]:
        L += ["> **No Search Console data.** Demand and quick-win are zero; this is a page-fit report only. "
              "Run `ingest` with a GSC export.", ""]
    elif meta["thin"]:
        L += [f"> **Thin data.** Under {T['thin_site_impressions']} impressions or {T['thin_site_queries']} queries. "
              "Treat rankings as hints, not findings; weights are starting values, not tuned.", ""]
    if meta["has_gsc"] and not meta["pair_rows"]:
        L += ["> No query×page rows: each query is linked to its best-fit page (`INFERRED`), not to the page Google showed.", ""]

    L += ["## Quick wins (avg position 5–20)", ""]
    if qw:
        L += ["| phrase | page | impr | pos | link | total |", "|---|---|---|---|---|---|"]
        L += [f"| {_md_cell(r['phrase'])} | {_md_cell(r['page'])} | {r['link_impressions']} | {f1(r['position'])} | {r['link']} | {f4(r['total'])} |" for r in qw[:top]]
    else:
        L += ["None found."]
    L += ["", "## Gaps (searched, no page is about it)", ""]
    if gap_rows:
        L += ["| phrase | impr | pos | action | suggested slug |", "|---|---|---|---|---|"]
        L += [f"| {_md_cell(g[0])} | {g[1]} | {g[3]} | {g[7]} | {g[9]} |" for g in gap_rows[:top]]
    else:
        L += ["None found."]
    L += ["", "## Cannibalization (two pages chasing one cluster)", ""]
    shown = [c for c in cann if c["severity"] in ("HIGH", "MED")]
    if shown:
        L += ["| cluster | severity | seed | owner | competing |", "|---|---|---|---|---|"]
        L += [f"| {c['cluster_id']} | {c['severity']} | {_md_cell(c['seed'])} | {_md_cell(c['owner'])} | "
              f"{_md_cell(', '.join(x['page'] for x in c['competitors']))} |" for c in shown[:top]]
    else:
        L += ["No HIGH/MED cases."]
    n_low = sum(c["severity"] == "LOW" for c in cann)
    if n_low:
        L += ["", f"{n_low} LOW (content-overlap only, no search demand) in cannibalization.csv."]
    L += ["", "## Page suggestions (plain language first)", "",
          "| page | suggested title | suggested H1 | why | notes |", "|---|---|---|---|---|"]
    L += [f"| {_md_cell(s['page'])} | {_md_cell(s['suggested_title'])} | {_md_cell(s['suggested_h1'])} | "
          f"{_md_cell(s['why'])} | {_md_cell(s['notes'])} |" for s in sugg[:top]]
    if len(sugg) > top:
        L += ["", f"…{len(sugg) - top} more in page_suggestions.csv (with descriptions)."]
    L += ["", "## Bridges (pages that should link to each other)", ""]
    if bridges:
        L += ["| page A | page B | A→B anchor | B→A anchor | why a reader would care |", "|---|---|---|---|---|"]
        L += [f"| {_md_cell(b['page_a'])} | {_md_cell(b['page_b'])} | {_md_cell(b['anchor_a_to_b'])} | "
              f"{_md_cell(b['anchor_b_to_a'])} | {_md_cell(b['rationale'])} |" for b in bridges[:top]]
    else:
        L += ["None passed the relevance gate."]
    if gate:
        L += ["", "Gate: " + " · ".join(f"{k} {v}" for k, v in gate.items())]
    if social:
        L += ["", "## Social signals (X posts, not search volume)", "",
              "Never used as demand. Blank = not measured (never estimated); 0 = measured zero.", "",
              "| kind | term | X posts (7d) | momentum | on site | best page |", "|---|---|---|---|---|---|"]
        L += [f"| {s[0]} | {_md_cell(s[1])} | {s[4] if s[4] != '' else '—'} | {s[7] or '—'} | {s[10]} | {_md_cell(s[8])} |"
              for s in social[:top]]
    if trend_rows:
        L += ["", "## Google Trends (relative interest 0–100, not volume)", "",
              "| kind | query | latest / value | momentum | on site |", "|---|---|---|---|---|"]
        L += [f"| {t[0]} | {_md_cell(t[1])} | {t[4]} | {t[5] or '—'} | {t[8]} |" for t in trend_rows[:top]]
    L += ["", "## Method", "",
          f"total = {W['demand']}·demand + {W['quickwin']}·quickwin + {W['fit']}·fit + {W['distinct']}·distinct − {W['penalty']}·penalty",
          "",
          "- **demand**: ln(1+impressions) ÷ ln(1+site max), for the phrase as a Search Console query",
          f"- **quickwin**: demand of the linked page row when avg position is {T['quickwin_min_position']:g}–{T['quickwin_max_position']:g}",
          "- **fit**: TF-IDF on the page ÷ the page's strongest phrase (title/H1 count double)",
          "- **distinct**: rarity across the site (IDF, 1.0 = on one page only)",
          "- **penalty**: glyph/jargon share of the phrase, only when it has 0 impressions",
          "- Candidates are 1–4-word n-grams that don't start/end on a stopword: a stand-in for noun phrases, not a parser.",
          "- `seo_lens.py explain \"<phrase>\"` prints every term for one phrase.",
          "", "See receipt.md for input/config/output hashes.", ""]
    return "\n".join(L)
