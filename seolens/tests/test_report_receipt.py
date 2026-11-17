import csv
import json
import re

from seolens.cli import main
from seolens.config import ROOT

from conftest import FIX


def run_cli(work, out, cfg_path):
    assert main(["--work", str(work), "--config", str(cfg_path), "report", "--out", str(out)]) == 0
    return json.loads((out / "receipt.json").read_text("utf-8"))


def _cfg_file(tmp_path):
    p = tmp_path / "t.toml"
    p.write_text('[site]\nallowlist = ["example.com"]\n')
    return p


def test_determinism_same_input_same_hash(work_full, tmp_path):
    cp = _cfg_file(tmp_path)
    a = run_cli(work_full, tmp_path / "r1", cp)
    b = run_cli(work_full, tmp_path / "r2", cp)
    assert a["run_hash"] == b["run_hash"]
    for o in a["outputs"]:
        assert (tmp_path / "r1" / o["name"]).read_bytes() == (tmp_path / "r2" / o["name"]).read_bytes()


def test_hash_changes_when_config_changes(work_full, tmp_path):
    cp = _cfg_file(tmp_path)
    a = run_cli(work_full, tmp_path / "r1", cp)
    cp2 = tmp_path / "t2.toml"
    cp2.write_text('[site]\nallowlist = ["example.com"]\n[weights]\nfit = 0.3\n')
    b = run_cli(work_full, tmp_path / "r2", cp2)
    assert a["config_hash"] != b["config_hash"] and a["run_hash"] != b["run_hash"]


def test_receipt_contents(work_full, tmp_path):
    rec = run_cli(work_full, tmp_path / "r", _cfg_file(tmp_path))
    assert {i["name"] for i in rec["inputs"]} == {"corpus.jsonl", "gsc.json"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", x["sha256"]) for x in rec["inputs"] + rec["outputs"])
    assert rec["signed"].startswith("SIGNED: ")
    md = (tmp_path / "r" / "receipt.md").read_text("utf-8")
    assert rec["run_hash"] in md and "SIGNED:" in md
    assert "/" not in "".join(i["name"] for i in rec["inputs"])     # no local paths leak
    assert str(tmp_path) not in json.dumps(rec)


def test_report_outputs_and_no_timestamp_in_hashed_files(work_full, tmp_path):
    rec = run_cli(work_full, tmp_path / "r", _cfg_file(tmp_path))
    out = tmp_path / "r"
    names = {o["name"] for o in rec["outputs"]}
    assert names == {"scores.csv", "clusters.csv", "quick_wins.csv", "gaps.csv", "page_suggestions.csv",
                     "cannibalization.csv", "bridges.csv", "social.csv", "trends.csv", "observations.csv",
                     "report.json", "report.md"}
    assert rec["timestamp"] not in (out / "report.md").read_text("utf-8")
    md = (out / "report.md").read_text("utf-8")
    assert "Thin data" in md and "INFERRED" in md


def test_suggestions_plain_language_first(work_full, tmp_path):
    run_cli(work_full, tmp_path / "r", _cfg_file(tmp_path))
    rows = list(csv.DictReader((tmp_path / "r" / "page_suggestions.csv").open(encoding="utf-8")))
    by = {r["page"]: r for r in rows}
    route = by["https://example.com/p/route-card.html"]
    assert not route["suggested_title"].startswith("∆")                 # plain words lead
    assert "current title starts with a glyph" in route["notes"]
    for r in rows:
        assert len(r["suggested_title"]) <= 60 and len(r["suggested_description"]) <= 155
    gaps = list(csv.DictReader((tmp_path / "r" / "gaps.csv").open(encoding="utf-8")))
    assert gaps[0]["phrase"] == "pricing plans" and gaps[0]["suggested_slug"] == "/pricing-plans.html"
    assert gaps[0]["action"] == "NEW POST"


def test_explain_prints_terms(work_full, tmp_path, capsys):
    assert main(["--work", str(work_full), "--config", str(_cfg_file(tmp_path)), "explain",
                 "Workflow Templates"]) == 0
    out = capsys.readouterr().out
    for t in ("demand", "quickwin", "fit", "distinct", "penalty", "TOTAL"):
        assert t in out


def test_expand_rule_universal_runtime(lex, cfg):
    from seolens.report import render
    assert render("urt setup", lex, cfg["expand"]) == "Universal Runtime (URT) Setup"


def test_gitignore_guards_private_data():
    gi = (ROOT / ".gitignore").read_text()
    for pat in ("work/", "runs/", "private/", "*.gsc.csv"):
        assert pat in gi


def test_no_credentials_in_source():
    words = ["api[_-]?" + "key", "client_" + "secret", "pass" + "word", "bear" + r"er\s+[a-z0-9]", "ya" + r"29\.",
             "gh" + "p_", "sk-" + "[a-z0-9]{10}", "AIza" + "Sy"]
    bad = re.compile("(" + "|".join(words) + ")", re.I)
    files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts
             and p.suffix in (".py", ".toml", ".md", ".txt", ".csv", ".html", ".json", ".gitignore", "")]
    assert len(files) > 30
    for p in files:
        assert not bad.search(p.read_text("utf-8")), p


def test_fixtures_are_example_com_only():
    for p in FIX.rglob("*"):
        if p.is_file():
            hosts = set(re.findall(r"https?://([a-z0-9.-]+)", p.read_text("utf-8")))
            assert hosts <= {"example.com"}, (p, hosts)


def test_slug_never_ends_on_hyphen():
    from seolens.report import slugify
    s = slugify("a" * 69 + " b c d")
    assert len(s) <= 70 and not s.endswith("-") and not s.startswith("-")


def test_default_work_dirs_live_inside_seolens():
    import argparse
    from seolens import cli
    seen = {}
    real = argparse.ArgumentParser.parse_args
    def spy(self, *a, **k):
        ns = real(self, *a, **k); seen.update(vars(ns)); raise SystemExit(0)
    argparse.ArgumentParser.parse_args = spy
    try:
        try:
            cli.main(["report"])
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = real
    assert seen["work"] == str(ROOT / "work") and seen["runs"] == str(ROOT / "runs")


def test_explain_says_why_not_scored(work_full, tmp_path, capsys):
    cp = _cfg_file(tmp_path)
    assert main(["--work", str(work_full), "--config", str(cp), "explain", "these workflow templates"]) == 0
    out = capsys.readouterr().out
    assert "starts with stopword 'these'" in out and "Raw occurrences" in out
    assert main(["--work", str(work_full), "--config", str(cp), "explain",
                 "reusable workflow templates cut setup time"]) == 0
    out = capsys.readouterr().out
    assert "6 words; candidates are 1–4 words" in out
    assert main(["--work", str(work_full), "--config", str(cp), "explain", "quantum lasagna"]) == 0
    assert "not found on any harvested page" in capsys.readouterr().out
