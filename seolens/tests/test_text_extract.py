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


# ---------- fix R1 (µEZ✦BLOG 11-17): dots/colons inside domains, versions, URLs, times ----------

def test_domain_stays_in_one_sentence():
    from seolens.text import segments
    segs = segments("SEO LENS is an offline keyword and page-fit tool for blog.4xela.ai. It reads pages.", lower=False)
    assert segs[0] == "SEO LENS is an offline keyword and page-fit tool for blog.4xela.ai"
    assert len(segs) == 2


def test_version_url_time_not_split():
    from seolens.text import segments
    assert segments("Python 3.11 or newer.", lower=False) == ["Python 3.11 or newer"]
    assert segments("see https://x.y/z now", lower=False) == ["see https://x.y/z now"]
    assert segments("At 10:30 we met: done.", lower=False) == ["At 10:30 we met", " done"]


def test_tokens_keep_inner_dots_strip_outer():
    segs = tokenize_segments("Run it on blog.4xela.ai with Python 3.11. Done.")
    assert segs == [["run", "it", "on", "blog.4xela.ai", "with", "python", "3.11"], ["done"]]


def test_sentence_end_before_quote_or_bracket():
    from seolens.text import segments
    assert len(segments('He said "done." Next one', lower=False)) == 2
    assert len(segments("Done (really.) Next", lower=False)) == 2


def test_description_suggestion_keeps_domain():
    from seolens.report import _sentence_with
    text = "SEO LENS is an offline keyword and page-fit tool for blog.4xela.ai. It reads pages."
    assert _sentence_with(text, "page-fit tool").endswith("blog.4xela.ai")


def test_seo_topic_words_are_not_stopwords(lex):
    for w in ("search", "blog", "post", "posts"):
        assert not lex.is_stop(w)
    assert "search console csv" in set(lex.ngrams(["search", "console", "csv"]))
