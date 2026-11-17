"""seo_lens CLI: harvest · ingest · score · cluster · report · explain."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .cluster import build_clusters
from .config import lexicon, load_config
from .harvest import HarvestError, run_harvest
from .ingest import ingest, load_gsc, write_gsc
from .receipt import write_receipt
from .report import OUTPUTS, build_report, f1, f4, write_csv
from .score import load_corpus, score
from .text import phrase_key


def _ctx(a):
    cfg = load_config(a.config)
    return cfg, lexicon(cfg), Path(a.work)


def cmd_harvest(a):
    cfg = load_config(a.config)
    if a.feed:
        mode, target = "feed", a.feed
    elif a.sitemap:
        mode, target = "sitemap", a.sitemap
    elif a.dir:
        mode, target = "dir", a.dir
    else:
        mode, target = "cache", None
    if a.delay is not None:
        cfg["site"]["delay_seconds"] = a.delay
    if a.max_pages is not None:
        cfg["site"]["max_pages"] = a.max_pages
    s = run_harvest(cfg, a.work, mode, target, base=a.base)
    print(f"harvest [{s['mode']}] records={s['records']} requests={s['requests']} → {Path(a.work) / 'corpus.jsonl'}")
    for w in s["warnings"]:
        print("  WARN", w)


def cmd_ingest(a):
    data = ingest(a.files)
    p = write_gsc(data, a.work)
    print(f"ingest → {p}  queries={len(data['queries'])} pages={len(data['pages'])} pairs={len(data['pairs'])}")
    for s in data["sources"]:
        print(f"  {s['shape']:8} {s['rows']:6} rows  {s['file']}")
    if data["skipped"]:
        print("  skipped:", ", ".join(data["skipped"]))
    print("  NOTE: gsc.json holds real Search Console data. It stays in work/ (gitignored).")


def cmd_score(a):
    cfg, lex, work = _ctx(a)
    res = score(load_corpus(work), load_gsc(work), cfg, lex)
    write_csv(work / "scores.csv", ["phrase", "page", "impressions", "link", "position", "demand", "quickwin",
                                    "fit", "distinct", "penalty", "total", "flags"],
              [[r["phrase"], r["page"], r["impressions"], r["link"], f1(r["position"]), f4(r["demand"]),
                f4(r["quickwin"]), f4(r["fit"]), f4(r["distinct"]), f4(r["penalty"]), f4(r["total"]), r["flags"]]
               for r in res.rows])
    print(f"score → {work / 'scores.csv'}  rows={len(res.rows)} gaps={len(res.gaps)}")
    for r in res.rows[: a.top]:
        print(f"  {r['total']:.3f}  {r['phrase'][:40]:40}  {r['page']}")


def cmd_cluster(a):
    cfg, lex, work = _ctx(a)
    res = score(load_corpus(work), load_gsc(work), cfg, lex)
    cl = build_clusters(res, cfg, lex)
    write_csv(work / "clusters.csv", ["cluster", "seed", "size", "demand", "owner", "severity", "competitors"],
              [[c["cluster_id"], c["seed"], c["size"], c["demand"], c["owner"], c["severity"],
                " | ".join(x["page"] for x in c["competitors"])] for c in cl])
    print(f"cluster → {work / 'clusters.csv'}  clusters={len(cl)}")
    for c in [c for c in cl if c["severity"] in ("HIGH", "MED")][: a.top]:
        print(f"  {c['severity']:4} {c['cluster_id']} '{c['seed']}' owner={c['owner']} vs {len(c['competitors'])}")


def cmd_report(a):
    cfg, lex, work = _ctx(a)
    out = Path(a.out) if a.out else Path(a.runs) / time.strftime("%Y%m%d-%H%M%S")
    gsc = load_gsc(work)
    info = build_report(load_corpus(work), gsc, cfg, lex, out)
    rec = write_receipt(out, work, cfg, info["meta"], OUTPUTS, gsc, signer=a.signer)
    print(f"report → {out}")
    print(f"  RUN_HASH {rec['run_hash']}")
    m = info["meta"]
    print(f"  quick_wins={m['quick_wins']} gaps={m['gaps']} cannibal HIGH/MED/LOW="
          f"{m['cannibal_high']}/{m['cannibal_med']}/{m['cannibal_low']}"
          + ("  [THIN DATA]" if m["thin"] else "") + ("  [NO GSC]" if not m["has_gsc"] else ""))


def cmd_explain(a):
    cfg, lex, work = _ctx(a)
    res = score(load_corpus(work), load_gsc(work), cfg, lex)
    key = phrase_key(a.phrase)
    rows = [r for r in res.rows if r["phrase"] == key and (not a.page or r["page"] == a.page)]
    W = cfg["weights"]
    if not rows:
        print(f"'{key}' not scored on any page (not a candidate: below min_site_count, or not in the corpus).")
        g = next((g for g in res.gaps if g["phrase"] == key), None)
        if g:
            print(f"  GAP: {g['impressions']} impressions, avg pos {g['position']}")
        return
    print(f"phrase '{key}'  glyph_share={lex.glyph_frac(key.split(' ')):.2f}")
    for r in rows:
        print(f"\n  page {r['page']}  count={r['count']} df={r['df']} link={r['link'] or '-'} flags=[{r['flags']}]")
        for t in ("demand", "quickwin", "fit", "distinct"):
            print(f"    {t:9} {r[t]:.4f} × {W[t]:.2f} = {+W[t] * r[t]:+.4f}")
        print(f"    {'penalty':9} {r['penalty']:.4f} × {W['penalty']:.2f} = {-W['penalty'] * r['penalty']:+.4f}")
        print(f"    {'TOTAL':9} {r['total']:.4f}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="seo_lens", description="SEO LENS · offline-first keyword + page-fit tool")
    ap.add_argument("--work", default="work", help="work dir (cache, corpus, gsc) [work]")
    ap.add_argument("--config", default=None, help="TOML overrides on top of config/default.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="own pages → work/corpus.jsonl (only network step)")
    g = h.add_mutually_exclusive_group()
    g.add_argument("--feed", help="site root, uses Blogger feeds, e.g. https://blog.4xela.ai")
    g.add_argument("--sitemap", help="sitemap URL, e.g. https://blog.4xela.ai/sitemap.xml")
    g.add_argument("--dir", help="folder of saved .html files (offline)")
    h.add_argument("--base", help="with --dir: base URL for files without a canonical link")
    h.add_argument("--delay", type=float, help="seconds between requests (default from config)")
    h.add_argument("--max-pages", type=int)
    h.set_defaults(fn=cmd_harvest)

    i = sub.add_parser("ingest", help="Search Console CSV/zip exports → work/gsc.json")
    i.add_argument("files", nargs="+")
    i.set_defaults(fn=cmd_ingest)

    for name, fn, hp in (("score", cmd_score, "phrase × page scores → work/scores.csv"),
                         ("cluster", cmd_cluster, "clusters + cannibalization → work/clusters.csv")):
        p = sub.add_parser(name, help=hp)
        p.add_argument("--top", type=int, default=15)
        p.set_defaults(fn=fn)

    r = sub.add_parser("report", help="full run → runs/<stamp>/ (CSVs, report.md/json, receipt)")
    r.add_argument("--out", help="output dir (default runs/<YYYYmmdd-HHMMSS>)")
    r.add_argument("--runs", default="runs")
    r.add_argument("--signer", default="SEO LENS engine", help="name on the SIGNED line")
    r.set_defaults(fn=cmd_report)

    e = sub.add_parser("explain", help="show every score term for one phrase")
    e.add_argument("phrase")
    e.add_argument("--page")
    e.set_defaults(fn=cmd_explain)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (HarvestError, FileNotFoundError) as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 2
    return 0
