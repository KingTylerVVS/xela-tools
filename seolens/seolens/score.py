"""score: phrase × page rows with every term kept separately (explainable).

total = w.demand·demand + w.quickwin·quickwin + w.fit·fit + w.distinct·distinct − w.penalty·penalty

demand    ln(1+impressions of the phrase as a GSC query) ÷ ln(1+max impressions on the site)   [0–1]
quickwin  demand of the *linked* row (PAIR or INFERRED page) when its avg position is in [min, max], else 0
fit       TF-IDF of the phrase on this page ÷ the page's strongest TF-IDF  (1.0 = what the page is most about)
distinct  IDF ÷ IDF of a phrase found on one page only  (rarity across the site)               [0–1]
penalty   share of glyph/jargon tokens in the phrase, only when the phrase has 0 impressions   [0–1]

TF = 1 + ln(count) (title + H1 counted head_boost times) · IDF = ln((1+N)/(1+df)) + 1
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .text import Lexicon, count_phrase, phrase_key, tokenize_segments


@dataclass
class ScoreResult:
    rows: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    pages: list = field(default_factory=list)          # corpus records, sorted by url
    qagg: dict = field(default_factory=dict)            # phrase -> {impressions, clicks, position}
    pair_pages: dict = field(default_factory=dict)      # phrase -> {url -> metrics}
    links: dict = field(default_factory=dict)           # phrase -> (url, "PAIR"|"INFERRED")
    fit: dict = field(default_factory=dict)             # url -> {phrase -> fit}
    meta: dict = field(default_factory=dict)
    streams: dict = field(default_factory=dict)         # url -> (head segs, other segs)

    def best_page(self, words: str):
        """(url, fit, count) of the page that covers a phrase best; ("", 0.0, 0) if none."""
        if not words:
            return "", 0.0, 0
        ptoks = words.split(" ")
        best = ("", 0.0, 0)
        for url in sorted(self.streams):
            f = self.fit.get(url, {}).get(words, 0.0)
            head, other = self.streams[url]
            c = count_phrase(head, ptoks) + count_phrase(other, ptoks)
            if (f, c) > (best[1], best[2]):
                best = (url, f, c)
        return best


def load_corpus(work) -> list[dict]:
    p = Path(work) / "corpus.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"{p} not found: run `harvest` first")
    return [json.loads(line) for line in p.read_text("utf-8").splitlines() if line.strip()]


def _agg(rows, keyf):
    out = {}
    for r in rows:
        k = keyf(r)
        if not k:
            continue
        a = out.setdefault(k, {"impressions": 0, "clicks": 0, "_pw": 0.0, "_pn": 0.0, "_n": 0})
        a["impressions"] += r["impressions"]
        a["clicks"] += r["clicks"]
        a["_pw"] += r["position"] * r["impressions"]
        a["_pn"] += r["position"]
        a["_n"] += 1
    for a in out.values():
        a["position"] = round(a["_pw"] / a["impressions"] if a["impressions"] else a["_pn"] / a["_n"], 4)
        for k in ("_pw", "_pn", "_n"):
            del a[k]
    return out


def score(corpus: list[dict], gsc: dict, cfg: dict, lex: Lexicon) -> ScoreResult:
    C, W, T = cfg["candidates"], cfg["weights"], cfg["thresholds"]
    boost = C["head_boost"]
    res = ScoreResult(pages=sorted(corpus, key=lambda r: r["url"]))

    # --- page token streams ---
    streams = {}
    for rec in res.pages:
        head = tokenize_segments(rec.get("title", "")) + tokenize_segments(rec.get("h1", ""))
        other = tokenize_segments(rec.get("description", "")) + tokenize_segments(rec.get("text", ""))
        streams[rec["url"]] = (head, other)
    res.streams = streams

    # --- candidate phrases ---
    counts: dict[str, Counter] = {}
    head_phr, site = set(), Counter()
    for url, (head, other) in streams.items():
        c = Counter()
        for seg in head:
            for g in lex.ngrams(seg, C["min_n"], C["max_n"], C["min_unigram_len"]):
                c[g] += boost
                head_phr.add(g)
        for seg in other:
            for g in lex.ngrams(seg, C["min_n"], C["max_n"], C["min_unigram_len"]):
                c[g] += 1
        counts[url] = c
        site.update(c)

    # --- Search Console ---
    res.qagg = _agg(gsc.get("queries", []), lambda r: phrase_key(r["query"]))
    pair_agg = _agg(gsc.get("pairs", []), lambda r: (phrase_key(r["query"]), r["page"]) if phrase_key(r["query"]) else None)
    if not res.qagg and pair_agg:  # pairs only: derive query level
        res.qagg = _agg([{"impressions": a["impressions"], "clicks": a["clicks"], "position": a["position"], "q": k[0]}
                         for k, a in sorted(pair_agg.items())], lambda r: r["q"])
    for (ph, url), a in pair_agg.items():
        res.pair_pages.setdefault(ph, {})[url] = a

    for q in res.qagg:  # queries: exact contiguous scan (may contain stopwords)
        ptoks = q.split(" ")
        for url, (head, other) in streams.items():
            n = boost * count_phrase(head, ptoks) + count_phrase(other, ptoks)
            if n:
                counts[url][q] = n
            else:
                counts[url].pop(q, None)

    keep = {p for p, n in site.items() if n >= C["min_site_count"]} | head_phr | set(res.qagg)

    # --- TF-IDF / fit ---
    N = len(res.pages)
    df = Counter()
    for c in counts.values():
        for p, n in c.items():
            if p in keep and n > 0:
                df[p] += 1

    def idf(d):
        return math.log((1 + N) / (1 + d)) + 1

    idf_one = idf(1) if N else 1.0
    for url, c in counts.items():
        w = {p: (1 + math.log(n)) * idf(df[p]) for p, n in c.items() if p in keep and n > 0}
        mx = max(w.values(), default=0.0)
        res.fit[url] = {p: (v / mx if mx else 0.0) for p, v in w.items()}

    # --- links (which page a query belongs to) ---
    for q in sorted(res.qagg):
        if q in res.pair_pages:
            continue
        best = sorted(((res.fit[u].get(q, 0.0), u) for u in res.fit), key=lambda x: (-x[0], x[1]))
        if best and best[0][0] > 0:
            res.links[q] = (best[0][1], "INFERRED")

    max_impr = max([a["impressions"] for a in res.qagg.values()] + [0])

    def dem(imp):
        return math.log1p(imp) / math.log1p(max_impr) if max_impr > 0 else 0.0

    qmin, qmax = T["quickwin_min_position"], T["quickwin_max_position"]
    gf_cache = {}

    def row(p, url, fit, count):
        q = res.qagg.get(p)
        q_imp = q["impressions"] if q else 0
        pa = res.pair_pages.get(p, {}).get(url)
        if pa:
            link, l_imp, l_clicks, l_pos = "PAIR", pa["impressions"], pa["clicks"], pa["position"]
        elif q and res.links.get(p, (None,))[0] == url:
            link, l_imp, l_clicks, l_pos = "INFERRED", q_imp, q["clicks"], q["position"]
        else:
            link, l_imp, l_clicks, l_pos = "", 0, 0, None
        demand = dem(q_imp)
        quickwin = dem(l_imp) if (link and l_pos is not None and qmin <= l_pos <= qmax) else 0.0
        if p not in gf_cache:
            gf_cache[p] = lex.glyph_frac(p.split(" "))
        gf = gf_cache[p]
        penalty = gf if q_imp == 0 else 0.0
        distinct = idf(df[p]) / idf_one if df[p] else 1.0
        total = (W["demand"] * demand + W["quickwin"] * quickwin + W["fit"] * fit
                 + W["distinct"] * distinct - W["penalty"] * penalty)
        flags = []
        if q:
            flags.append("QUERY")
            if q_imp < T["low_data_impressions"]:
                flags.append("LOW-DATA")
        if gf > 0:
            flags.append("GLYPH")
        if p in head_phr:
            flags.append("HEAD")
        if count == 0:
            flags.append("NOT-ON-PAGE")
        return {"phrase": p, "page": url, "n": len(p.split(" ")), "count": count, "df": df[p],
                "impressions": q_imp, "link": link, "link_impressions": l_imp, "link_clicks": l_clicks,
                "position": l_pos, "demand": demand, "quickwin": quickwin, "fit": fit,
                "distinct": distinct, "penalty": penalty, "total": total, "flags": " ".join(flags)}

    for url in sorted(res.fit):
        for p in sorted(res.fit[url]):
            res.rows.append(row(p, url, res.fit[url][p], counts[url][p]))
    for p in sorted(res.pair_pages):  # GSC says the page shows for it, but the phrase isn't on the page
        for url in sorted(res.pair_pages[p]):
            if p not in res.fit.get(url, {}):
                res.rows.append(row(p, url, 0.0, 0))
    res.rows.sort(key=lambda r: (-round(r["total"], 9), r["phrase"], r["page"]))

    # --- gaps: searched, but no page is about it ---
    for q in sorted(res.qagg):
        a = res.qagg[q]
        if a["impressions"] <= 0:
            continue
        best = sorted(((res.fit[u].get(q, 0.0), u) for u in res.fit), key=lambda x: (-x[0], x[1]))
        bf, bu = best[0] if best else (0.0, "")
        if bf < T["gap_max_fit"]:
            res.gaps.append({"phrase": q, "impressions": a["impressions"], "clicks": a["clicks"],
                             "position": a["position"], "best_page": bu if bf > 0 else "", "best_fit": bf,
                             "gsc_pages": " | ".join(sorted(res.pair_pages.get(q, {})))})
    res.gaps.sort(key=lambda g: (-g["impressions"], g["phrase"]))

    tot_imp = sum(a["impressions"] for a in res.qagg.values())
    res.meta = {
        "pages": sum(1 for r in res.pages if r.get("kind") == "page"),
        "posts": sum(1 for r in res.pages if r.get("kind") != "page"),
        "words": sum(len(t) for h, o in streams.values() for t in h + o),
        "phrases": len({r["phrase"] for r in res.rows}),
        "rows": len(res.rows),
        "queries": len(res.qagg),
        "pair_rows": len(pair_agg),
        "impressions_total": tot_imp,
        "has_gsc": bool(res.qagg),
        "thin": tot_imp < T["thin_site_impressions"] or len(res.qagg) < T["thin_site_queries"],
    }
    return res
