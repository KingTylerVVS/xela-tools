from seolens.extract import extract_html
from seolens.text import count_phrase, phrase_key, tokenize_segments

from conftest import PAGES


def test_tokenize_keeps_hyphens_splits_sentences():
    segs = tokenize_segments("Pre-agent specs. Workflow: done!")
    assert segs == [["pre-agent", "specs"], ["workflow"], ["done"]]


def test_ngrams_never_start_or_end_on_stopword(lex):
    grams = set(lex.ngrams(["the", "workflow", "templates", "for", "teams"]))
    assert "workflow templates" in grams
    assert "workflow templates for teams" in grams
    assert not any(g.split()[0] in ("the", "for") or g.split()[-1] in ("the", "for") for g in grams)


def test_short_unigrams_dropped_unless_glyph(lex):
    assert "ai" not in set(lex.ngrams(["ai"]))
    assert "ez" in set(lex.ngrams(["ez"]))


def test_glyph_detection(lex):
    assert lex.is_glyph("∆z") and lex.is_glyph("xbcm") and lex.is_glyph("§")
    assert not lex.is_glyph("workflow")
    assert lex.glyph_frac(["∆z", "route", "card"]) == 1 / 3
    assert lex.glyph_frac(["xbcm"]) == 1.0
    assert lex.glyph_frac(["memory", "notes"]) == 0.0


def test_count_phrase_contiguous():
    segs = tokenize_segments("ai chat memory. chat memory ai. ai chat memory again")
    assert count_phrase(segs, phrase_key("AI chat memory").split()) == 2


def test_extract_prefers_post_body_and_skips_chrome():
    ex = extract_html((PAGES / "p-workflow-templates.html").read_text("utf-8"))
    assert ex["title"] == "Workflow Templates for Small Teams"
    assert ex["description"] == "Reusable workflow templates for small teams."
    assert ex["canonical"] == "https://example.com/p/workflow-templates.html"
    assert "junk" not in ex["text"]                 # script skipped
    assert "Popular posts" not in ex["text"]        # aside skipped
    assert "Posted by" not in ex["text"]            # outside post-body
    assert "Example Notebook" not in ex["text"]     # header skipped
    assert ex["h1"] == ""                           # only h1 is in <header>
    assert "Reusable workflow templates cut setup time" in ex["text"]


def test_extract_without_post_body_uses_body_and_h1():
    ex = extract_html("<html><head><meta property='og:description' content='og d'></head>"
                      "<body><h1>Big Title</h1><p>Some text here</p><script>x</script></body></html>")
    assert ex["h1"] == "Big Title"
    assert ex["description"] == "og d"
    assert "Some text here" in ex["text"] and "x" not in ex["text"].split()
