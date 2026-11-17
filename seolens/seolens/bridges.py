"""Bridge finder: pairs of existing pages that can link to each other because the link is real.

Relevance gate (all must pass, or the pair is dropped and counted in the receipt):
  1. similarity   page TF-IDF cosine in [sim_min, sim_max)  (above = overlap → cannibalization, not a bridge)
  2. shared       ≥1 plain-language phrase that matters on BOTH pages (fit ≥ shared_min_fit), not glyph-only,
                  not on more than max_df_share of all pages (too generic)
     … and at least one shared phrase is 2+ words (a shared topic, not a lone common word)
  3. not trend    at least one shared phrase is not just a trending social/Trends term
  0. not rivals   pages competing in a HIGH/MED cannibalization cluster are never bridged (fix the overlap first)
  4. novelty      each side has an anchor phrase the other page barely covers (fit ≤ novelty_max_fit)
  5. rationale    built from 2–4; if any part is missing there is no sentence, so no pair
"""
from __future__ import annotations

from .cluster import cosine
from .score import ScoreResult
from .text import Lexicon


def _plain(p: str, lex: Lexicon) -> bool:
    return lex.glyph_frac(p.split(" ")) == 0


def _label(rec: dict, lex: Lexicon) -> str:
    t = (rec.get("title") or "").strip()
    toks = t.lower().split()
    if not t or (toks and sum(1 for x in toks if lex.is_glyph(x)) / len(toks) > 0.5):
        slug = rec["url"].rstrip("/").rsplit("/", 1)[-1].replace(".html", "").replace("-", " ")
        return slug or rec["url"]
    return t


def _fuller(p: str, fits: dict) -> str:
    """'ai chat' → 'ai chat memory' when the longer phrase is nearly as strong on the same page."""
    while True:
        longer = sorted((q for q in fits if q != p and f" {p} " in f" {q} " and fits[q] >= 0.75 * fits[p]),
                        key=lambda q: (-fits[q], len(q), q))
        if not longer:
            return p
        p = longer[0]


def find_bridges(res: ScoreResult, cfg: dict, lex: Lexicon, trend_words: set | None = None, clusters=()):
    B = cfg["bridges"]
    rivals = set()
    for c in clusters:
        if c.get("severity") in ("HIGH", "MED"):
            group = [c["owner"]] + [x["page"] for x in c["competitors"]]
            rivals.update((min(u, v), max(u, v)) for u in group for v in group if u != v)
    trend_words = trend_words or set()
    N = len(res.pages)
    by_url = {r["url"]: r for r in res.pages}
    df = {}
    for r in res.rows:
        if r["count"] > 0:
            df[r["phrase"]] = r["df"]
    max_df = max(1, int(B["max_df_share"] * N))
    gate = {"pairs_checked": 0, "rivals": 0, "similarity": 0, "no_shared": 0, "trend_only": 0, "no_novel_anchor": 0, "kept": 0}
    out = []
    urls = sorted(res.fit)
    for i, a in enumerate(urls):
        for b in urls[i + 1:]:
            gate["pairs_checked"] += 1
            if (a, b) in rivals:
                gate["rivals"] += 1
                continue
            fa, fb = res.fit[a], res.fit[b]
            sim = cosine(fa, fb)
            if not (B["sim_min"] <= sim < B["sim_max"]):
                gate["similarity"] += 1
                continue
            shared = sorted((p for p in fa if p in fb and _plain(p, lex) and df.get(p, N) <= max_df
                             and min(fa[p], fb[p]) >= B["shared_min_fit"]),
                            key=lambda p: (-(len(p.split()) >= 2), -min(fa[p], fb[p]), p))
            if not shared or not any(len(p.split()) >= 2 for p in shared):
                gate["no_shared"] += 1
                continue
            real = [p for p in shared if p not in trend_words]
            if not any(len(p.split()) >= 2 for p in real):
                gate["trend_only"] += 1
                continue

            def anchor(src, dst):  # phrase strong on dst, new to src
                c = [p for p in res.fit[dst] if _plain(p, lex) and res.fit[src].get(p, 0) <= B["novelty_max_fit"]
                     and df.get(p, N) <= max_df]
                c.sort(key=lambda p: (-(len(p.split()) >= 2), -res.fit[dst][p], p))
                if not c:
                    return None
                full = _fuller(c[0], res.fit[dst])
                return full if res.fit[src].get(full, 0) <= B["novelty_max_fit"] else c[0]

            ab, ba = anchor(a, b), anchor(b, a)
            if not ab or not ba:
                gate["no_novel_anchor"] += 1
                continue
            la, lb = _label(by_url[a], lex), _label(by_url[b], lex)
            s0 = next(p for p in real if len(p.split()) >= 2)
            rationale = (f"Readers of \"{la}\" already care about {s0}; \"{lb}\" takes them further into {ab}, "
                         f"and it sends readers back for {ba}.")
            out.append({"page_a": a, "page_b": b, "similarity": sim, "shared": real[:5],
                        "anchor_a_to_b": ab, "anchor_b_to_a": ba, "rationale": rationale,
                        "bridge_angle": f"How {ba} and {ab} connect through {s0}",
                        "label_a": la, "label_b": lb})
    out.sort(key=lambda x: (-len(x["shared"]), -round(x["similarity"], 9), x["page_a"], x["page_b"]))
    gate["over_cap"] = max(0, len(out) - B["max_pairs"])
    out = out[: B["max_pairs"]]
    gate["kept"] = len(out)
    return out, gate
