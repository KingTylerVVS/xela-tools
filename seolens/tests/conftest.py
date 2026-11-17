"""Shared fixtures. example.com data only; fake numbers; no network anywhere."""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from seolens.config import lexicon, load_config  # noqa: E402
from seolens.extract import extract_html  # noqa: E402
from seolens.harvest import run_harvest  # noqa: E402
from seolens.ingest import ingest, write_gsc  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "example.com"
PAGES = FIX / "pages"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real socket use in a test is a failure: proves the tool runs offline."""
    def guard(*a, **k):
        raise AssertionError("network access attempted during tests")
    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


@pytest.fixture
def cfg():
    return load_config(overrides={"site": {"allowlist": ["example.com"], "delay_seconds": 0}})


@pytest.fixture
def lex(cfg):
    return lexicon(cfg)


def _page_html():
    out = {}
    for f in sorted(PAGES.glob("*.html")):
        html = f.read_text("utf-8")
        out[extract_html(html)["canonical"]] = html
    return out


def atom_feed(items):
    entries = "".join(
        f"<entry><title>{escape(t)}</title><link rel='alternate' href='{escape(u)}'/>"
        f"<content type='html'>{escape(body)}</content></entry>" for u, t, body in items)
    return f"<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'>{entries}</feed>"


class FakeSite:
    """In-memory transport: url -> (status, text). Records every request."""

    def __init__(self, page_size=2, robots="User-agent: *\nDisallow: /search\n"):
        self.calls = []
        self.routes = {"https://example.com/robots.txt": (200, robots)}
        pages = _page_html()
        posts = [(u, h) for u, h in pages.items() if "/p/" not in u]
        statics = [(u, h) for u, h in pages.items() if "/p/" in u]
        for name, group in (("posts", posts), ("pages", statics)):
            items = [(u, extract_html(h)["title"], h.split('class="post-body entry-content">')[1].split("</div>")[0])
                     for u, h in group]
            for start in range(1, max(len(items), 1) + 1 + page_size, page_size):
                chunk = items[start - 1:start - 1 + page_size]
                url = (f"https://example.com/feeds/{name}/default?alt=atom&max-results={page_size}"
                       f"&start-index={start}")
                self.routes[url] = (200, atom_feed(chunk))
                if len(chunk) < page_size:
                    break
        locs = "".join(f"<url><loc>{u}</loc></url>" for u in pages)
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        self.routes["https://example.com/sitemap.xml"] = (
            200, f"<sitemapindex xmlns='{ns}'><sitemap><loc>https://example.com/sitemap.xml?page=1</loc></sitemap>"
                 f"<sitemap><loc>https://other.example.org/sitemap.xml</loc></sitemap></sitemapindex>")
        self.routes["https://example.com/sitemap.xml?page=1"] = (200, f"<urlset xmlns='{ns}'>{locs}</urlset>")
        for u, h in pages.items():
            self.routes[u] = (200, h)

    def __call__(self, url):
        self.calls.append(url)
        return self.routes.get(url, (404, ""))


@pytest.fixture
def fake_site():
    return FakeSite()


@pytest.fixture
def work_dir_harvested(tmp_path, cfg):
    work = tmp_path / "work"
    run_harvest(cfg, work, "dir", str(PAGES))
    return work


@pytest.fixture
def work_full(work_dir_harvested):
    """Corpus + GSC queries/pages only (no pairs) → INFERRED links."""
    write_gsc(ingest([FIX / "gsc_queries.csv", FIX / "gsc_pages.csv"]), work_dir_harvested)
    return work_dir_harvested


@pytest.fixture
def work_pairs(work_dir_harvested):
    write_gsc(ingest([FIX / "gsc_queries.csv", FIX / "gsc_pairs.csv"]), work_dir_harvested)
    return work_dir_harvested
