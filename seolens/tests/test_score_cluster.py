from seolens.cluster import build_clusters
from seolens.ingest import load_gsc
from seolens.score import load_corpus, score

WT = "https://example.com/p/workflow-templates.html"
FWT = "https://example.com/2026/01/free-workflow-templates.html"
MEM = "https://example.com/p/memory-notes.html"


def run(work, cfg, lex):
    res = score(load_corpus(work), load_gsc(work), cfg, lex)
    return res, build_clusters(res, cfg, lex)


def row(res, phrase, page):
    return next(r for r in res.rows if r["phrase"] == phrase and r["page"] == page)


def test_total_is_weighted_sum(work_full, cfg, lex):
    res, _ = run(work_full, cfg, lex)
    W = cfg["weights"]
    for r in res.rows:
        exp = (W["demand"] * r["demand"] + W["quickwin"] * r["quickwin"] + W["fit"] * r["fit"]
               + W["distinct"] * r["distinct"] - W["penalty"] * r["penalty"])
        assert abs(exp - r["total"]) < 1e-12


def test_terms_in_range(work_full, cfg, lex):
    res, _ = run(work_full, cfg, lex)
    for r in res.rows:
        for t in ("demand", "quickwin", "fit", "distinct", "penalty"):
            assert 0.0 <= r[t] <= 1.0 + 1e-12, (t, r)


def test_quick_win_inferred_without_pairs(work_full, cfg, lex):
    res, _ = run(work_full, cfg, lex)
    r = row(res, "ai chat memory", MEM)
    assert r["link"] == "INFERRED" and r["position"] == 14.5 and r["quickwin"] > 0
    assert row(res, "workflow templates", WT)["quickwin"] > 0        # pos 8.2 → in band
    assert all(x["quickwin"] == 0 for x in res.rows if x["phrase"] == "task routing")  # pos 32 → out


def test_pairs_give_page_level_links(work_pairs, cfg, lex):
    res, _ = run(work_pairs, cfg, lex)
    a, b = row(res, "workflow templates", WT), row(res, "workflow templates", FWT)
    assert a["link"] == b["link"] == "PAIR"
    assert a["link_impressions"] == 80 and b["position"] == 15.0
    assert a["quickwin"] > b["quickwin"] > 0                        # both in band, more impressions wins


def test_not_on_page_pair_row(work_pairs, cfg, lex):
    res, _ = run(work_pairs, cfg, lex)
    r = row(res, "pricing plans", "https://example.com/2026/02/getting-started.html")
    assert r["count"] == 0 and "NOT-ON-PAGE" in r["flags"] and r["quickwin"] == 0  # pos 25 → out of band


def test_gap_found(work_full, cfg, lex):
    res, _ = run(work_full, cfg, lex)
    # sorted by impressions; "getting started workflow" never appears contiguously on a page
    assert [g["phrase"] for g in res.gaps] == ["pricing plans", "getting started workflow"]


def test_glyph_penalty_only_without_impressions(work_full, cfg, lex):
    res, _ = run(work_full, cfg, lex)
    r = row(res, "∆z route card", "https://example.com/p/route-card.html")
    assert r["penalty"] > 0 and "GLYPH" in r["flags"]
    assert all(x["penalty"] == 0 for x in res.rows if x["impressions"] > 0)


def test_low_data_flag(work_full, cfg, lex):
    res, _ = run(work_full, cfg, lex)
    assert res.meta["thin"] is True
    assert any("LOW-DATA" in r["flags"] for r in res.rows if r["phrase"] == "getting started workflow") or \
        any(g["phrase"] == "getting started workflow" for g in res.gaps)


def test_no_gsc_still_runs(work_dir_harvested, cfg, lex):
    res, cl = run(work_dir_harvested, cfg, lex)
    assert res.meta["has_gsc"] is False and res.rows and cl
    assert all(r["demand"] == 0 and r["quickwin"] == 0 for r in res.rows)


def test_cannibalization_workflow_templates(work_pairs, cfg, lex):
    res, cl = run(work_pairs, cfg, lex)
    c = next(c for c in cl if "workflow templates" in c["members"])
    assert c["owner"] == WT and c["owner_basis"] == "clicks"
    assert FWT in [x["page"] for x in c["competitors"]]
    assert c["severity"] == "HIGH"


def test_cannibalization_without_pairs_is_med(work_full, cfg, lex):
    _, cl = run(work_full, cfg, lex)
    c = next(c for c in cl if "workflow templates" in c["members"])
    assert c["severity"] == "MED" and {c["owner"]} | {x["page"] for x in c["competitors"]} >= {WT, FWT}


def test_cluster_ids_and_members_unique(work_full, cfg, lex):
    _, cl = run(work_full, cfg, lex)
    members = [m for c in cl for m in c["members"]]
    assert len(members) == len(set(members))
    assert [c["cluster_id"] for c in cl] == sorted(c["cluster_id"] for c in cl)
