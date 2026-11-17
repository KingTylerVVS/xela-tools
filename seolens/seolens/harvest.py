"""harvest: own-site pages → local cache → corpus.jsonl.

Only network step in SEO LENS. Guards: host allowlist, robots.txt, rate limit, named User-Agent.
Modes: Blogger feeds (preferred) · sitemap · local dir of saved HTML · rebuild from cache (offline).
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .extract import extract_html

ATOM = "{http://www.w3.org/2005/Atom}"
SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


class HarvestError(RuntimeError):
    pass


def normalize_url(u: str) -> str:
    p = urlsplit((u or "").strip())
    if not p.netloc:
        return (u or "").strip()
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if k != "m"])
    return urlunsplit(("https", p.netloc.lower(), p.path or "/", q, ""))


def kind_of(url: str) -> str:
    return "page" if "/p/" in urlsplit(url).path else "post"


def default_transport(url: str, user_agent: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, r.read().decode(charset, "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except urllib.error.URLError as e:
        raise HarvestError(f"network error for {url}: {e.reason}") from e


class Fetcher:
    def __init__(self, allowlist, user_agent, delay=1.0, timeout=20, transport=None,
                 sleep=time.sleep, clock=time.monotonic):
        self.allow = {h.lower() for h in allowlist}
        self.ua = user_agent
        self.delay = float(delay)
        self.timeout = timeout
        self.transport = transport or (lambda url: default_transport(url, user_agent, timeout))
        self.sleep, self.clock = sleep, clock
        self._last = None
        self._robots: dict[str, RobotFileParser] = {}
        self.requests = 0

    def check_host(self, url: str):
        host = (urlsplit(url).hostname or "").lower()
        if host not in self.allow:
            raise HarvestError(f"refused: host '{host}' is not in the allowlist {sorted(self.allow)}")

    def _wait(self):
        if self._last is not None:
            gap = self.clock() - self._last
            if gap < self.delay:
                self.sleep(self.delay - gap)
        self._last = self.clock()

    def _raw(self, url):
        self._wait()
        self.requests += 1
        return self.transport(url)

    def robots(self, url) -> RobotFileParser:
        p = urlsplit(url)
        key = f"https://{p.netloc.lower()}"
        if key not in self._robots:
            status, text = self._raw(key + "/robots.txt")
            rp = RobotFileParser()
            if status == 200:
                rp.parse(text.splitlines())
            elif status in (401, 403):
                rp.disallow_all = True
            elif 400 <= status < 500:
                rp.allow_all = True
            else:
                raise HarvestError(f"robots.txt unreachable (HTTP {status}); refusing to crawl {key}")
            self._robots[key] = rp
        return self._robots[key]

    def get(self, url: str) -> str:
        self.check_host(url)
        if not self.robots(url).can_fetch(self.ua, url):
            raise HarvestError(f"robots.txt disallows {url}")
        status, text = self._raw(url)
        if status != 200:
            raise HarvestError(f"HTTP {status} for {url}")
        return text


# ---------- parsing ----------

def parse_atom(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        href = ""
        for link in e.findall(f"{ATOM}link"):
            if link.get("rel") == "alternate":
                href = link.get("href", "")
                break
        c = e.find(f"{ATOM}content")
        summary_only = c is None
        if c is None:
            c = e.find(f"{ATOM}summary")
        out.append({
            "url": href,
            "title": (e.findtext(f"{ATOM}title") or "").strip(),
            "html": (c.text or "") if c is not None else "",
            "summary_only": summary_only,
        })
    return out


def parse_sitemap(xml_text: str):
    root = ET.fromstring(xml_text)
    kind = "index" if root.tag.endswith("sitemapindex") else "urlset"
    return kind, [(el.text or "").strip() for el in root.iter(f"{SM}loc") if (el.text or "").strip()]


# ---------- cache ----------

class Cache:
    def __init__(self, work: Path):
        self.dir = Path(work) / "cache"
        self.raw = self.dir / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.dir / "manifest.json"
        self.entries = json.loads(self.manifest_path.read_text("utf-8")) if self.manifest_path.exists() else []

    def reset(self):
        for f in self.raw.iterdir():
            f.unlink()
        self.entries = []

    def put(self, kind: str, url: str, text: str, name: str | None = None):
        name = name or f"{kind}-{hashlib.sha1(url.encode()).hexdigest()[:16]}.{'xml' if kind != 'page' else 'html'}"
        (self.raw / name).write_text(text, "utf-8")
        self.entries.append({"file": name, "kind": kind, "url": url})

    def save(self):
        self.manifest_path.write_text(json.dumps(self.entries, indent=1, ensure_ascii=False), "utf-8")


def records_from_cache(cache: Cache, warnings: list) -> list[dict]:
    recs = []
    for ent in cache.entries:
        text = (cache.raw / ent["file"]).read_text("utf-8")
        if ent["kind"] == "feed":
            for item in parse_atom(text):
                if not item["url"]:
                    continue
                if item["summary_only"]:
                    warnings.append(f"feed gives summary only for {item['url']} (set Blogger feed to Full)")
                ex = extract_html(item["html"])
                url = normalize_url(item["url"])
                recs.append({"url": url, "kind": kind_of(url), "title": item["title"], "h1": ex["h1"],
                             "description": "", "text": ex["text"], "source": "feed"})
        elif ent["kind"] == "page":
            ex = extract_html(text)
            url = normalize_url(ent["url"])
            recs.append({"url": url, "kind": kind_of(url), "title": ex["title"], "h1": ex["h1"],
                         "description": ex["description"], "text": ex["text"], "source": "page"})
    return recs


# ---------- modes ----------

def _root(url: str) -> str:
    p = urlsplit(url if "://" in url else "https://" + url)
    return f"https://{p.netloc.lower()}"


def harvest_feed(base: str, fetcher: Fetcher, cache: Cache, page_size: int = 150, warnings=None):
    root = _root(base)
    for feed in ("posts", "pages"):
        start = 1
        while True:
            url = f"{root}/feeds/{feed}/default?alt=atom&max-results={page_size}&start-index={start}"
            try:
                xml = fetcher.get(url)
            except HarvestError as e:
                if start == 1 and feed == "pages":
                    warnings.append(f"pages feed unavailable ({e}); /p/ pages missing, try --sitemap")
                    break
                raise
            cache.put("feed", url, xml, name=f"feed-{feed}-{start:05d}.xml")
            n = len(parse_atom(xml))
            if n < page_size:
                break
            start += page_size


def harvest_sitemap(url: str, fetcher: Fetcher, cache: Cache, max_pages: int, warnings: list):
    queue, seen, page_urls = [url], set(), set()
    while queue:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            xml = fetcher.get(u)
        except HarvestError as e:
            warnings.append(str(e))
            continue
        kind, locs = parse_sitemap(xml)
        if kind == "index":
            queue.extend(sorted(locs))
        else:
            page_urls.update(normalize_url(loc) for loc in locs)
    pages = sorted(page_urls)
    if len(pages) > max_pages:
        warnings.append(f"sitemap lists {len(pages)} URLs; capped at max_pages={max_pages}")
    for pu in pages[:max_pages]:
        try:
            cache.put("page", pu, fetcher.get(pu))
        except HarvestError as e:
            warnings.append(str(e))


def records_from_dir(path: str, base: str | None) -> list[dict]:
    d = Path(path)
    recs = []
    for f in sorted(list(d.rglob("*.html")) + list(d.rglob("*.htm"))):
        ex = extract_html(f.read_text("utf-8", errors="replace"))
        rel = f.relative_to(d).as_posix()
        if ex["canonical"]:
            url = normalize_url(ex["canonical"])
        elif base:
            url = normalize_url(base.rstrip("/") + "/" + rel)
        else:
            url = "local:" + rel
        recs.append({"url": url, "kind": kind_of(url), "title": ex["title"], "h1": ex["h1"],
                     "description": ex["description"], "text": ex["text"], "source": "dir"})
    return recs


def write_corpus(recs: list[dict], work: Path, warnings: list) -> Path:
    by_url = {}
    for r in sorted(recs, key=lambda r: (r["url"], r["source"])):
        if not r["text"].strip():
            warnings.append(f"empty text, skipped: {r['url']}")
            continue
        by_url.setdefault(r["url"], r)
    out = Path(work) / "corpus.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for url in sorted(by_url):
            fh.write(json.dumps(by_url[url], sort_keys=True, ensure_ascii=False) + "\n")
    return out


def run_harvest(cfg: dict, work, mode: str, target: str | None = None, base: str | None = None,
                transport=None, sleep=time.sleep) -> dict:
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    s = cfg["site"]
    warnings: list[str] = []
    fetcher = None
    if mode == "dir":
        recs = records_from_dir(target, base)
    else:
        cache = Cache(work)
        if mode in ("feed", "sitemap"):
            fetcher = Fetcher(s["allowlist"], s["user_agent"], s["delay_seconds"], s["timeout_seconds"],
                              transport=transport, sleep=sleep)
            cache.reset()
            if mode == "feed":
                harvest_feed(target, fetcher, cache, s["feed_page_size"], warnings)
            else:
                harvest_sitemap(target, fetcher, cache, s["max_pages"], warnings)
            cache.save()
        elif mode != "cache":
            raise HarvestError(f"unknown mode {mode}")
        recs = records_from_cache(cache, warnings)
    out = write_corpus(recs, work, warnings)
    n = sum(1 for _ in out.open(encoding="utf-8"))
    summary = {"mode": mode, "target": target, "records": n,
               "requests": fetcher.requests if fetcher else 0, "warnings": warnings,
               "harvested_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (work / "harvest.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), "utf-8")
    return summary
