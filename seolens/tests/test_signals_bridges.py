import csv
import json

import pytest

from seolens.bridges import find_bridges
from seolens.cli import main
from seolens.cluster import build_clusters
from seolens.ingest import ingest, load_gsc
from seolens.score import load_corpus, score
from seolens.signals import (hashtag_words, ingest_trends, ingest_x, momentum, parse_trends, trend_momentum,
                             write_json)

from conftest import FIX


def rows(path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


@pytest.fixture
def work_signals(work_pairs, cfg):
    write_json(ingest_x(FIX / "x_trends.json", cfg), work_pairs, "x_trends.json")
    write_json(ingest_trends([FIX / "trends_timeline.csv", FIX / "trends_related_workflow.csv"],
                             term="workflow templates"), work_pairs, "trends.json")
    return work_pairs


def _cfgfile(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[site]\nallowlist = ["example.com"]\n')
    return p


def report(work, out, tmp_path):
    assert main(["--work", str(work), "--config", str(_cfgfile(tmp_path)), "report", "--out", str(out)]) == 0
    return json.loads((out / "receipt.json").read_text("utf-8"))


# ---------- x_trends ----------

def test_hashtag_words():
    assert hashtag_words("#AIAgents") == "ai agents"
    assert hashtag_words("#UniversalRuntime") == "universal runtime"
    assert hashtag_words("#WorkflowTemplates") == "workflow templates"


def test_x_null_is_never_zero_and_zero_is_measured(cfg):
    d = ingest_x(FIX / "x_trends.json", cfg)
    by = {(r["hashtag"], r["topic"]): r for r in d["records"]}
    null = by[("#AIChatMemory", "memory")]
    zero = by[("#TaskRouting", "task routing")]
    assert null["measured"] is False and null["value"] is None
    assert zero["measured"] is True and zero["value"] == 0
    ph = {p["phrase"]: p for p in d["phrases"]}
    assert ph["pricing plans"]["value"] is None and ph["pricing plans"]["measured"] is False
    assert ph["memory notes"]["value"] == 6
    assert d["schema_version"] == "x_trends_sample.v1" and len(d["source"]["sha256"]) == 64


def test_x_trimmed_daily_is_skipped_not_guessed(cfg):
    d = ingest_x(FIX / "x_trends.json", cfg)
    full = next(r for r in d["records"] if r["topic"] == "workflow templates")
    trimmed = next(r for r in d["records"] if r["topic"] == "planning")
    assert full["days_measured"] == 7 and full["momentum"] == round(28 / 12 - 1, 4)
    assert trimmed["days_measured"] == 0 and trimmed["momentum"] is None


def test_momentum_needs_every_day_measured():
    assert momentum([1, 2, 3, 4, 5, 6], 3) == round(5 / 2 - 1, 4)
    assert momentum([1, None, 3, 4, 5, 6], 3) is None
    assert momentum([1, 2, 3], 3) is None


def test_x_bad_schema_rejected(tmp_path, cfg):
    p = tmp_path / "bad.json"
    p.write_text('{"rows": []}')
    with pytest.raises(ValueError, match="records"):
        ingest_x(p, cfg)


def test_x_never_changes_scores(work_pairs, work_signals, tmp_path):
    # same work dir: run once with signals present, once with them removed
    a = report(work_signals, tmp_path / "with", tmp_path)
    (work_signals / "x_trends.json").unlink()
    (work_signals / "trends.json").unlink()
    b = report(work_signals, tmp_path / "without", tmp_path)
    for name in ("scores.csv", "quick_wins.csv", "gaps.csv", "clusters.csv", "cannibalization.csv"):
        assert (tmp_path / "with" / name).read_bytes() == (tmp_path / "without" / name).read_bytes(), name
    assert {i["name"] for i in a["inputs"]} >= {"x_trends.json", "trends.json"}
    assert "x_trends.json" not in {i["name"] for i in b["inputs"]}


def test_social_and_observations_keep_null_blank(work_signals, tmp_path):
    report(work_signals, tmp_path / "r", tmp_path)
    soc = {r["term"]: r for r in rows(tmp_path / "r" / "social.csv")}
    assert soc["#AIChatMemory"]["x_posts"] == "" and soc["#AIChatMemory"]["measured"] == "FALSE"
    assert soc["#TaskRouting"]["x_posts"] == "0" and soc["#TaskRouting"]["measured"] == "TRUE"
    assert soc["#WorkflowTemplates"]["momentum"] == "1.3333"            # fullest record used
    assert all(r["note"].startswith("X posts, not search volume") for r in soc.values())
    obs = rows(tmp_path / "r" / "observations.csv")
    x = {r["keyword"]: r for r in obs if r["source"] == "x_trends"}
    assert x["#AIChatMemory"]["value"] == "" and x["#AIChatMemory"]["measured"] == "FALSE"
    assert {r["source"] for r in obs} == {"x_trends", "google_trends", "search_console"}
    assert not any(r["metric"] == "demand" for r in obs)


# ---------- Google Trends ----------

def test_trends_timeline_parse():
    t = parse_trends((FIX / "trends_timeline.csv").read_text())
    assert set(t["series"]) == {"workflow templates", "memory notes"}
    first = t["series"]["memory notes"][0]
    assert first["raw"] == "<1" and first["value"] == 0.5


def test_trends_related_parse():
    t = parse_trends((FIX / "trends_related_workflow.csv").read_text(), "workflow templates")
    by = {r["query"]: r for r in t["related"]}
    assert by["ai workflow templates"]["raw"] == "Breakout" and by["ai workflow templates"]["value"] is None
    assert by["workflow templates for teams"]["value"] == 250.0 and by["workflow templates for teams"]["section"] == "RISING"
    assert by["free workflow templates"]["section"] == "TOP"


def test_trend_momentum():
    pts = [{"value": v} for v in [10] * 8 + [20] * 4]
    assert trend_momentum(pts, 4, 8) == 1.0
    assert trend_momentum(pts[:5], 4, 8) is None


def test_gsc_ingest_refuses_trends_files():
    d = ingest([FIX / "gsc_queries.csv", FIX / "trends_timeline.csv"])
    assert d["skipped"] == ["trends_timeline.csv (Google Trends file: use ingest-trends)"]
    assert len(d["queries"]) == 5


def test_trends_ingest_skips_non_trends(tmp_path):
    d = ingest_trends([FIX / "gsc_queries.csv"])
    assert d["skipped"] and not d["series"]


# ---------- bridges ----------

def _bridges(work, cfg, lex, trend_words=None):
    res = score(load_corpus(work), load_gsc(work), cfg, lex)
    cl = build_clusters(res, cfg, lex)
    return find_bridges(res, cfg, lex, trend_words or set(), cl), cl


def test_bridges_pass_gate_with_reason(work_pairs, cfg, lex):
    (bridges, gate), cl = _bridges(work_pairs, cfg, lex)
    assert bridges and gate["kept"] == len(bridges)
    rivals = set()
    for c in cl:
        if c["severity"] in ("HIGH", "MED"):
            g = [c["owner"]] + [x["page"] for x in c["competitors"]]
            rivals |= {frozenset((u, v)) for u in g for v in g if u != v}
    for b in bridges:
        assert frozenset((b["page_a"], b["page_b"])) not in rivals
        assert b["rationale"].endswith(".") and len(b["rationale"].split()) >= 8
        assert any(len(p.split()) >= 2 for p in b["shared"])
        assert b["anchor_a_to_b"] and b["anchor_b_to_a"]
    assert gate["rivals"] >= 1


def test_bridges_trend_only_pairs_dropped(work_pairs, cfg, lex):
    (bridges, _), _ = _bridges(work_pairs, cfg, lex)
    trend = {p for b in bridges for p in b["shared"]}
    (after, gate), _ = _bridges(work_pairs, cfg, lex, trend_words=trend)
    assert len(after) < len(bridges) and gate["trend_only"] >= 1


def test_signals_run_is_deterministic(work_signals, tmp_path):
    a = report(work_signals, tmp_path / "a", tmp_path)
    b = report(work_signals, tmp_path / "b", tmp_path)
    assert a["run_hash"] == b["run_hash"]


# ---------- KEYWORDS sheet export ----------

def test_export_sheet_matches_live_headers_and_rules(work_signals, tmp_path):
    out = tmp_path / "sheet"
    assert main(["--work", str(work_signals), "--config", str(_cfgfile(tmp_path)), "export-sheet",
                 "--keywords", str(FIX / "sheet_keywords.csv"), "--observations", str(FIX / "sheet_observations.csv"),
                 "--as-of", "2026-01-09", "--out", str(out)]) == 0
    kw = rows(out / "keywords_append.csv")
    ob = rows(out / "observations_append.csv")
    assert list(ob[0].keys()) == ["date", "kw_id", "source", "volume", "impressions", "clicks", "position", "kd", "serp_features"]
    assert list(kw[0].keys()) == ["kw_id", "keyword", "cluster", "intent", "tier", "target_url", "added_date", "source"]
    x = {r["kw_id"]: r for r in ob if r["source"] == "x_counts"}
    assert x["KW001"]["volume"] == "140" and x["KW001"]["date"] == "2026-01-08"      # existing kw_id reused
    assert "KW002" not in x                                                          # already in Observations
    new = {r["keyword"]: r["kw_id"] for r in kw}
    assert new["#AIChatMemory"] == "KW003"                                           # next id after KW002
    assert x["KW003"]["volume"] == ""                                                # null stays blank
    g = [r for r in ob if r["source"] == "gsc"]
    assert g and all(r["volume"] == "" and r["impressions"] != "" for r in g)        # never invent volume
    assert all(r["kd"] == "" and r["serp_features"] == "" for r in ob)


def test_export_sheet_gsc_needs_date(work_signals, tmp_path):
    out = tmp_path / "s2"
    assert main(["--work", str(work_signals), "--config", str(_cfgfile(tmp_path)), "export-sheet", "--out", str(out)]) == 0
    assert not [r for r in rows(out / "observations_append.csv") if r["source"] == "gsc"]
    assert "need --as-of" in (out / "sheet_notes.txt").read_text()
