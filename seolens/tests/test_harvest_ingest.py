import io
import json
import zipfile

import pytest

from seolens.harvest import Fetcher, HarvestError, normalize_url, run_harvest
from seolens.ingest import ingest, parse_table

from conftest import FIX, PAGES, FakeSite

ALL = {"https://example.com/p/workflow-templates.html", "https://example.com/2026/01/free-workflow-templates.html",
       "https://example.com/p/route-card.html", "https://example.com/p/memory-notes.html",
       "https://example.com/2026/02/getting-started.html"}


def corpus(work):
    return [json.loads(x) for x in (work / "corpus.jsonl").read_text("utf-8").splitlines()]


def test_normalize_url_drops_mobile_param_and_fragment():
    assert normalize_url("http://Example.com/p/x.html?m=1#top") == "https://example.com/p/x.html"


def test_dir_mode(work_dir_harvested):
    recs = corpus(work_dir_harvested)
    assert {r["url"] for r in recs} == ALL
    assert {r["kind"] for r in recs if "/p/" in r["url"]} == {"page"}


def test_feed_mode_paginates_and_respects_rate_limit(tmp_path, cfg):
    site = FakeSite(page_size=2)
    cfg["site"]["feed_page_size"] = 2
    sleeps = []
    s = run_harvest(cfg, tmp_path / "w", "feed", "https://example.com", transport=site, sleep=sleeps.append)
    assert {r["url"] for r in corpus(tmp_path / "w")} == ALL
    assert site.calls[0] == "https://example.com/robots.txt"
    assert any("start-index=3" in c for c in site.calls)          # paginated
    assert s["requests"] == len(site.calls)


def test_feed_mode_rebuild_from_cache_offline(tmp_path, cfg):
    cfg["site"]["feed_page_size"] = 2
    run_harvest(cfg, tmp_path / "w", "feed", "https://example.com", transport=FakeSite(page_size=2))
    first = (tmp_path / "w" / "corpus.jsonl").read_bytes()
    (tmp_path / "w" / "corpus.jsonl").unlink()
    run_harvest(cfg, tmp_path / "w", "cache")                     # no transport at all
    assert (tmp_path / "w" / "corpus.jsonl").read_bytes() == first


def test_sitemap_mode_refuses_foreign_host(tmp_path, cfg):
    s = run_harvest(cfg, tmp_path / "w", "sitemap", "https://example.com/sitemap.xml", transport=FakeSite())
    assert {r["url"] for r in corpus(tmp_path / "w")} == ALL
    assert any("other.example.org" in w and "allowlist" in w for w in s["warnings"])


def test_allowlist_blocks_other_hosts(cfg):
    f = Fetcher(["example.com"], "t", 0, transport=FakeSite())
    with pytest.raises(HarvestError, match="allowlist"):
        f.get("https://www.google.com/search?q=x")


def test_robots_disallow(cfg):
    f = Fetcher(["example.com"], "t", 0, transport=FakeSite(robots="User-agent: *\nDisallow: /p/\n"))
    with pytest.raises(HarvestError, match="robots"):
        f.get("https://example.com/p/route-card.html")


def test_rate_limit_sleeps_between_requests():
    t = [0.0]
    slept = []
    f = Fetcher(["example.com"], "t", delay=1.0, transport=FakeSite(), sleep=lambda s: slept.append(s),
                clock=lambda: t[0])
    f.get("https://example.com/p/route-card.html")
    assert slept and abs(slept[0] - 1.0) < 1e-9


def test_parse_table_shapes():
    shape, rows = parse_table((FIX / "gsc_queries.csv").read_text())
    assert shape == "queries" and rows[0] == {"query": "workflow templates", "clicks": 6, "impressions": 120,
                                              "ctr": 0.05, "position": 8.2}
    assert parse_table((FIX / "gsc_pairs.csv").read_text())[0] == "pairs"
    assert parse_table((FIX / "gsc_countries.csv").read_text())[0] == "other"
    shape, rows = parse_table("Top pages,Clicks,Impressions\nhttps://example.com/p/a.html?m=1,\"1,200\",\"3,400\"\n")
    assert shape == "pages" and rows[0]["page"] == "https://example.com/p/a.html" and rows[0]["impressions"] == 3400


def test_ingest_zip_export_skips_other_tables(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, f in (("Queries.csv", "gsc_queries.csv"), ("Pages.csv", "gsc_pages.csv"),
                        ("Countries.csv", "gsc_countries.csv")):
            z.writestr(name, (FIX / f).read_text())
    p = tmp_path / "export.zip"
    p.write_bytes(buf.getvalue())
    d = ingest([p])
    assert len(d["queries"]) == 5 and len(d["pages"]) == 3 and not d["pairs"]
    assert d["skipped"] == ["export.zip:Countries.csv"]


def test_ingest_duplicates_not_double_counted():
    d = ingest([FIX / "gsc_queries.csv", FIX / "gsc_queries.csv"])
    assert sum(q["impressions"] for q in d["queries"]) == 120 + 60 + 15 + 40 + 8


def test_redirect_off_allowlist_refused_before_request():
    import urllib.request
    from seolens.harvest import AllowlistRedirectHandler
    h = AllowlistRedirectHandler(["example.com"])
    req = urllib.request.Request("https://example.com/p/a.html")
    with pytest.raises(HarvestError, match="refused redirect"):
        h.redirect_request(req, None, 301, "Moved", {}, "https://evil.example.net/x")
    assert h.redirect_request(req, None, 301, "Moved", {}, "https://example.com/p/b.html") is not None
