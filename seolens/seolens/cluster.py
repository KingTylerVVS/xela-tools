"""cluster: group phrases, pick one owner page per cluster, flag cannibalization.

Leader clustering, deterministic: phrases in (best total desc, phrase asc) order; a phrase joins the first
cluster whose seed shares tokens with it AND (token Jaccard >= cluster_jaccard OR cosine of their
per-page fit vectors >= cluster_cosine); otherwise it seeds a new cluster.
Owner = most GSC clicks (pair data) → else highest coverage (sum of member fits on the page).
Competitor = another page with a member fit >= cannibal_min_fit, or with GSC impressions for a member.
Cluster 'demand' = raw sum of member GSC impressions (written as impressions_sum; not the 0–1 row demand).
Severity: HIGH both owner and competitor get impressions · MED cluster has demand · LOW content overlap only.
"""
from __future__ import annotations

import math
from collections import defaultdict

from .score import ScoreResult
from .text import Lexicon


def cosine(a: dict, b: dict) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def build_clusters(res: ScoreResult, cfg: dict, lex: Lexicon) -> list[dict]:
    T = cfg["thresholds"]
    vec, best = defaultdict(dict), {}
    for r in res.rows:
        if r["fit"] > 0:
            vec[r["phrase"]][r["page"]] = r["fit"]
        best[r["phrase"]] = max(best.get(r["phrase"], -1e9), r["total"])
    order = sorted(best, key=lambda p: (-round(best[p], 9), p))
    k = T["cluster_top_k"]
    cand = order[:k] + [p for p in order[k:] if p in res.qagg]

    raw = []
    for p in cand:
        toks = {t for t in p.split(" ") if not lex.is_stop(t)}
        for c in raw:
            shared = toks & c["toks"]
            if not shared:
                continue
            jac = len(shared) / len(toks | c["toks"])
            if jac >= T["cluster_jaccard"] or cosine(vec[p], vec[c["seed"]]) >= T["cluster_cosine"]:
                c["members"].append(p)
                break
        else:
            raw.append({"seed": p, "toks": toks, "members": [p]})

    out = []
    for i, c in enumerate(raw, 1):
        cov, mx = defaultdict(float), defaultdict(float)
        clicks, pimp = defaultdict(int), defaultdict(int)
        for p in c["members"]:
            for u, f in vec[p].items():
                cov[u] += f
                mx[u] = max(mx[u], f)
            for u, a in res.pair_pages.get(p, {}).items():
                clicks[u] += a["clicks"]
                pimp[u] += a["impressions"]
        pages = sorted(set(cov) | set(pimp))
        if not pages:
            continue
        if any(clicks.values()):
            owner = sorted(pages, key=lambda u: (-clicks[u], -cov[u], u))[0]
            basis = "clicks"
        else:
            owner = sorted(pages, key=lambda u: (-round(cov[u], 9), u))[0]
            basis = "coverage"
        comps = [u for u in pages if u != owner and (mx[u] >= T["cannibal_min_fit"] or pimp[u] > 0)]
        demand = sum(res.qagg[p]["impressions"] for p in c["members"] if p in res.qagg)
        if not comps:
            sev = ""
        elif pimp[owner] > 0 and any(pimp[u] > 0 for u in comps):
            sev = "HIGH"
        elif demand > 0:
            sev = "MED"
        else:
            sev = "LOW"
        out.append({
            "cluster_id": f"C{i:03d}", "seed": c["seed"], "size": len(c["members"]), "members": c["members"],
            "demand": demand, "owner": owner, "owner_basis": basis, "owner_coverage": cov[owner],
            "owner_clicks": clicks[owner],
            "competitors": [{"page": u, "max_fit": mx[u], "impressions": pimp[u], "clicks": clicks[u]} for u in comps],
            "severity": sev,
        })
    return out
