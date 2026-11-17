"""Tokenising, n-grams and the stopword / glyph lexicon (stdlib only)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Sentence-ish boundaries: n-grams never cross these.
SEG_SPLIT = re.compile(r"[.!?;:\n\r\t•·|…—–]+")
# A token is a run of anything that is not whitespace or punctuation (hyphens and % stay inside tokens).
TOKEN = re.compile(r"[^\s,()\[\]{}\"“”‘’'`/\\<>*#=+~^&@.!?;:|•·…—–]+")
STRIP = "-_'’"


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").replace("\xa0", " ").lower()


def segments(text: str, lower: bool = True) -> list[str]:
    t = normalize(text) if lower else unicodedata.normalize("NFC", text or "").replace("\xa0", " ")
    return [s for s in SEG_SPLIT.split(t) if s.strip()]


def tokens(segment: str) -> list[str]:
    out = []
    for raw in TOKEN.findall(segment):
        t = raw.strip(STRIP)
        if t:
            out.append(t)
    return out


def tokenize_segments(text: str) -> list[list[str]]:
    return [ts for ts in (tokens(s) for s in segments(text)) if ts]


def phrase_tokens(phrase: str) -> list[str]:
    return [t for seg in tokenize_segments(phrase) for t in seg]


def phrase_key(phrase: str) -> str:
    """Canonical form used for every phrase / query comparison."""
    return " ".join(phrase_tokens(phrase))


def count_phrase(segs: list[list[str]], ptoks: list[str]) -> int:
    n = len(ptoks)
    if not n:
        return 0
    c = 0
    for seg in segs:
        for i in range(len(seg) - n + 1):
            if seg[i:i + n] == ptoks:
                c += 1
    return c


def _read_list(path: str | Path) -> frozenset[str]:
    out = set()
    for line in Path(path).read_text("utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(normalize(line))
    return frozenset(out)


@dataclass(frozen=True)
class Lexicon:
    stopwords: frozenset
    glyphs: frozenset

    @classmethod
    def from_files(cls, stop_path, glyph_path) -> "Lexicon":
        return cls(_read_list(stop_path), _read_list(glyph_path))

    def is_glyph(self, t: str) -> bool:
        return t in self.glyphs or any(ord(c) > 127 for c in t)

    def is_stop(self, t: str) -> bool:
        return t in self.stopwords or len(t) < 2 or not any(c.isalpha() for c in t)

    def glyph_frac(self, toks: list[str]) -> float:
        content = [t for t in toks if self.is_glyph(t) or not self.is_stop(t)]
        if not content:
            return 0.0
        return sum(1 for t in content if self.is_glyph(t)) / len(content)

    def ngrams(self, seg: list[str], min_n: int = 1, max_n: int = 4, min_unigram_len: int = 3):
        """1–4-grams that neither start nor end on a stopword (noun-phrase stand-in)."""
        L = len(seg)
        for i in range(L):
            if self.is_stop(seg[i]):
                continue
            for n in range(min_n, max_n + 1):
                j = i + n
                if j > L:
                    break
                if self.is_stop(seg[j - 1]):
                    continue
                if n == 1 and len(seg[i]) < min_unigram_len and not self.is_glyph(seg[i]):
                    continue
                yield " ".join(seg[i:j])
