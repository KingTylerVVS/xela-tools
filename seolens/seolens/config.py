"""Config loading (TOML, stdlib tomllib) + hashing."""
from __future__ import annotations

import copy
import hashlib
import json
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9/3.10 (macOS system python)
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        raise SystemExit("SEO LENS needs Python 3.11+ (or: pip install tomli). Try: brew install python@3.12")
from pathlib import Path

from .text import Lexicon

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "default.toml"
PATH_KEYS = (("lexicon", "stopwords"), ("lexicon", "glyphs"))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _resolve_paths(data: dict, base: Path) -> dict:
    for sec, key in PATH_KEYS:
        if sec in data and key in data[sec]:
            data[sec][key] = str((base / data[sec][key]).resolve())
    return data


def _load(path) -> dict:
    p = Path(path)
    return _resolve_paths(tomllib.loads(p.read_text("utf-8")), p.parent)


def deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path=None, overrides: dict | None = None) -> dict:
    cfg = _load(DEFAULT_CONFIG)
    if path:
        cfg = deep_merge(cfg, _load(path))
    if overrides:
        cfg = deep_merge(cfg, _resolve_paths(copy.deepcopy(overrides), Path.cwd()))
    return cfg


def portable_config(cfg: dict) -> dict:
    """Config with lexicon paths replaced by content hashes (same on every machine)."""
    c = copy.deepcopy(cfg)
    for sec, key in PATH_KEYS:
        c[sec][key] = "sha256:" + sha256_file(cfg[sec][key])
    return c


def config_hash(cfg: dict) -> str:
    blob = json.dumps(portable_config(cfg), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256_bytes(blob.encode("utf-8"))


def lexicon(cfg: dict) -> Lexicon:
    return Lexicon.from_files(cfg["lexicon"]["stopwords"], cfg["lexicon"]["glyphs"])
