"""seo_lens CLI: harvest · ingest · score · cluster · report · explain."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .cluster import build_clusters
from .config import ROOT
from .config import lexicon, load_config
from .harvest import HarvestError, run_harvest
from .ingest import ingest, load_gsc, write_gsc
from .receipt import write_receipt
from .report import OUTPUTS, build_report, f1, f4, write_csv
from .score import load_corpus, score
from .sheet import build_sheet_rows, write_sheet_rows
from .signals import ingest_trends, ingest_x, load_json, write_json
from .text import count_phrase, phrase_key


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


def cmd_ingest_x(a):
    cfg = load_config(a.config)
    data = ingest_x(a.file, cfg)
    p = write_json(data, a.work, "x_trends.json")
    m = sum(r["measured"] for r in data["records"])
    print(f"ingest-x → {p}  records={len(data['records'])} (measured {m}, null {len(data['records']) - m}) "
          f"phrases={len(data['phrases'])}  schema={data['schema_version'] or '?'}")
    print("  NOTE: X post counts are social signals, never search demand.")


def cmd_ingest_trends(a):
    data = ingest_trends(a.files, a.term or "")
    p = write_json(data, a.work, "trends.json")
    print(f"ingest-trends → {p}  terms={len(data['series'])} related={len(data['related'])}")
    for s in data["sources"]:
        print(f"  {s['shape']:8} {s['file']}")
    for s in data["skipped"]:
        print("  skipped:", s)
    print("  NOTE: Google Trends values are relative interest (0-100), not volume.")


def cmd_export_sheet(a):
    cfg, lex, work = _ctx(a)
    res = score(load_corpus(work), load_gsc(work), cfg, lex) if (work / "corpus.jsonl").exists() else None
    new_kw, obs, notes = build_sheet_rows(a.keywords, a.observations, load_json(work, "x_trends.json"),
                                          load_gsc(work), a.as_of, res, add_queries=not a.known_only)
    out = Path(a.out) if a.out else Path(a.runs) / ("sheet-" + time.strftime("%Y%m%d-%H%M%S"))
    c = write_sheet_rows(out, new_kw, obs, notes)
    print(f"export-sheet → {out}  new keywords={c['keywords_new']} observations={c['observations']}")
    for n in notes:
        print("  NOTE", n)
    print("  Append-only paste into KEYWORDS (Keywords, then Observations). B1 kill switch: practice mode.")


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
    write_csv(work / "clusters.csv", ["cluster", "seed", "size", "impressions_sum", "owner", "severity", "competitors"],
              [[c["cluster_id"], c["seed"], c["size"], c["demand"], c["owner"], c["severity"],
                " | ".join(x["page"] for x in c["competitors"])] for c in cl])
    print(f"cluster → {work / 'clusters.csv'}  clusters={len(cl)}")
    for c in [c for c in cl if c["severity"] in ("HIGH", "MED")][: a.top]:
        print(f"  {c['severity']:4} {c['cluster_id']} '{c['seed']}' owner={c['owner']} vs {len(c['competitors'])}")


def cmd_report(a):
    cfg, lex, work = _ctx(a)
    out = Path(a.out) if a.out else Path(a.runs) / time.strftime("%Y%m%d-%H%M%S")
    gsc = load_gsc(work)
    info = build_report(load_corpus(work), gsc, cfg, lex, out, xt=load_json(work, "x_trends.json"),
                        tr=load_json(work, "trends.json"), as_of=a.as_of)
    rec = write_receipt(out, work, cfg, info["meta"], OUTPUTS, gsc, signer=a.signer)
    print(f"report → {out}")
    print(f"  RUN_HASH {rec['run_hash']}")
    m = info["meta"]
    print(f"  bridges={m['bridges']} social_terms={m['x_terms']} trends_rows={m['trends_rows']} observations={m['observations']}")
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
        print(f"'{key}' is not scored on any page. Why:")
        for reason in why_not_scored(key, res, cfg, lex):
            print(f"  - {reason}")
        g = next((g for g in res.gaps if g["phrase"] == key), None)
        if g:
            print(f"  GAP: {g['impressions']} impressions, avg pos {g['position']}")
        hits = [(u, c) for u in sorted(res.streams)
                for c in [count_phrase(res.streams[u][0] + res.streams[u][1], key.split(" "))] if c]
        if hits:
            print("  Raw occurrences (counted, not scored):")
            for u, c in hits:
                print(f"    {c:3}  {u}")
        print("  Note: page text = title + H1 + meta description + body. Feed harvests have no meta description;"
              " use --sitemap for it. A phrase that is a Search Console query is always scored.")
        return
    print(f"phrase '{key}'  glyph_share={lex.glyph_frac(key.split(' ')):.2f}")
    for r in rows:
        print(f"\n  page {r['page']}  count={r['count']} df={r['df']} link={r['link'] or '-'} flags=[{r['flags']}]")
        for t in ("demand", "quickwin", "fit", "distinct"):
            print(f"    {t:9} {r[t]:.4f} × {W[t]:.2f} = {+W[t] * r[t]:+.4f}")
        print(f"    {'penalty':9} {r['penalty']:.4f} × {W['penalty']:.2f} = {-W['penalty'] * r['penalty']:+.4f}")
        print(f"    {'TOTAL':9} {r['total']:.4f}")


def why_not_scored(key: str, res, cfg: dict, lex) -> list[str]:
    C = cfg["candidates"]
    toks = key.split(" ") if key else []
    out = []
    if not toks:
        return ["empty phrase after tokenising"]
    if len(toks) > C["max_n"]:
        out.append(f"{len(toks)} words; candidates are {C['min_n']}–{C['max_n']} words (max_n in config)")
    if lex.is_stop(toks[0]):
        out.append(f"starts with stopword '{toks[0]}' (candidates can't start or end on a stopword)")
    if len(toks) > 1 and lex.is_stop(toks[-1]):
        out.append(f"ends with stopword '{toks[-1]}'")
    if len(toks) == 1 and len(toks[0]) < C["min_unigram_len"] and not lex.is_glyph(toks[0]):
        out.append(f"single word shorter than min_unigram_len={C['min_unigram_len']}")
    total = sum(count_phrase(h, toks) + count_phrase(o, toks) for h, o in res.streams.values())
    if total == 0:
        out.append("not found on any harvested page")
    elif not out:
        out.append(f"appears {total} time(s) site-wide; needs min_site_count={C['min_site_count']}"
                   " or a title/H1 occurrence")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="seo_lens", description="SEO LENS · offline-first keyword + page-fit tool")
    ap.add_argument("--work", default=str(ROOT / "work"), help="work dir (cache, corpus, gsc) [seolens/work]")
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

    x = sub.add_parser("ingest-x", help="XXENG x_trends.json → work/x_trends.json (social signal, never demand)")
    x.add_argument("file")
    x.set_defaults(fn=cmd_ingest_x)

    t = sub.add_parser("ingest-trends", help="Google Trends CSV exports → work/trends.json (relative, not volume)")
    t.add_argument("files", nargs="+")
    t.add_argument("--term", help="the search term a relatedQueries/relatedTopics file belongs to")
    t.set_defaults(fn=cmd_ingest_trends)

    s = sub.add_parser("export-sheet", help="append-ready CSVs for the KEYWORDS sheet (Keywords + Observations tabs)")
    s.add_argument("--keywords", help="CSV export of the sheet's Keywords tab (to reuse kw_ids)")
    s.add_argument("--observations", help="CSV export of the Observations tab (to skip rows already there)")
    s.add_argument("--as-of", default="", help="date for Search Console rows, e.g. 2026-11-17")
    s.add_argument("--known-only", action="store_true", help="Search Console: only keywords already in the sheet")
    s.add_argument("--out")
    s.add_argument("--runs", default=str(ROOT / "runs"))
    s.set_defaults(fn=cmd_export_sheet)

    for name, fn, hp in (("score", cmd_score, "phrase × page scores → work/scores.csv"),
                         ("cluster", cmd_cluster, "clusters + cannibalization → work/clusters.csv")):
        p = sub.add_parser(name, help=hp)
        p.add_argument("--top", type=int, default=15)
        p.set_defaults(fn=fn)

    r = sub.add_parser("report", help="full run → runs/<stamp>/ (CSVs, report.md/json, receipt)")
    r.add_argument("--out", help="output dir (default runs/<YYYYmmdd-HHMMSS>)")
    r.add_argument("--runs", default=str(ROOT / "runs"), help="[seolens/runs]")
    r.add_argument("--signer", default="SEO LENS engine", help="name on the SIGNED line")
    r.add_argument("--as-of", default="", help="date for Search Console rows in observations.csv (e.g. 2026-11-17)")
    r.set_defaults(fn=cmd_report)

    e = sub.add_parser("explain", help="show every score term for one phrase")
    e.add_argument("phrase")
    e.add_argument("--page")
    e.set_defaults(fn=cmd_explain)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (HarvestError, FileNotFoundError, ValueError) as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 2
    return 0
