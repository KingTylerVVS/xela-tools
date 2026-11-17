"""Signed receipt: input + config + output SHA-256, counts, run_hash (timestamp excluded → reproducible)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import LANE, __version__
from .config import config_hash, portable_config, sha256_bytes, sha256_file


def now_ct() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M CT")
    except Exception:  # no tz database
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def run_hash(inputs: list, cfg_hash: str, outputs: list) -> str:
    blob = json.dumps({"inputs": inputs, "config": cfg_hash, "outputs": outputs},
                      sort_keys=True, separators=(",", ":"))
    return sha256_bytes(blob.encode("utf-8"))


def write_receipt(out_dir, work, cfg: dict, meta: dict, outputs: list[str], gsc: dict,
                  signer: str = "SEO LENS engine") -> dict:
    out, work = Path(out_dir), Path(work)
    inputs = []
    for name in ("corpus.jsonl", "gsc.json", "x_trends.json", "trends.json"):
        p = work / name
        if p.exists():
            inputs.append({"name": name, "sha256": sha256_file(p), "bytes": p.stat().st_size})
    outs = [{"name": n, "sha256": sha256_file(out / n)} for n in outputs]
    ch = config_hash(cfg)
    rh = run_hash(inputs, ch, outs)
    ts = now_ct()
    signed = f"SIGNED: {signer} · seolens {__version__} ({LANE}) · {ts}"
    rec = {
        "tool": "seolens", "version": __version__, "lane": LANE, "timestamp": ts,
        "run_hash": rh, "config_hash": ch, "config": portable_config(cfg),
        "inputs": inputs,
        "gsc_sources": gsc.get("sources", []), "gsc_skipped": gsc.get("skipped", []),
        "counts": meta, "outputs": outs, "signed": signed,
    }
    (out / "receipt.json").write_text(json.dumps(rec, sort_keys=True, ensure_ascii=False, indent=1) + "\n", "utf-8")
    L = [f"# RECEIPT · {LANE} · seolens {__version__}", "",
         f"RUN_HASH: `{rh}`  (inputs + config + outputs; timestamp excluded)",
         f"CONFIG:   `{ch}`", f"TIME:     {ts}", "",
         "## Inputs", "", "| file | sha256 | bytes |", "|---|---|---|"]
    L += [f"| {i['name']} | `{i['sha256']}` | {i['bytes']} |" for i in inputs]
    if gsc.get("sources"):
        L += ["", "GSC sources:", ""]
        L += [f"- {s['file']} · {s['shape']} · {s['rows']} rows · `{s['sha256'][:16]}…`" for s in gsc["sources"]]
    if gsc.get("skipped"):
        L += ["", "GSC tables skipped: " + ", ".join(gsc["skipped"])]
    L += ["", "## Counts", "", "| item | value |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(meta.items())]
    L += ["", "## Outputs", "", "| file | sha256 |", "|---|---|"]
    L += [f"| {o['name']} | `{o['sha256']}` |" for o in outs]
    L += ["", signed, ""]
    (out / "receipt.md").write_text("\n".join(L), "utf-8")
    return rec
