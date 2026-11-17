# SEO LENS (R1)

Offline-first keyword + page-fit tool for **blog.4xela.ai**. Sibling of `acrball/` and `staracr/`:
**generate candidates → score → prune → explain → signed receipt.**

It answers four questions in plain language:
1. **Quick wins**: phrases people already find us for at positions 5–20.
2. **Gaps**: phrases people search where no page is really about the topic (→ NEW POST + slug).
3. **Cannibalization**: two pages chasing the same phrase cluster.
4. **Page suggestions**: title / H1 / meta description drafts, plain words first and glyph names after.

Draft only. SEO LENS never edits Blogger, never logs in to Google, and never scrapes Google results or autocomplete.

## Requirements
- Python **3.11+**, stdlib only. (3.9/3.10 also work with `pip install tomli`.)
- `pytest` only to run the tests.

## Quick start (on your Mac)

```bash
cd seolens
python3 seo_lens.py harvest --feed https://blog.4xela.ai      # only network step: ~5 requests, 1/s
python3 seo_lens.py ingest ~/Downloads/<GSC export>.zip        # optional but recommended
python3 seo_lens.py report --signer "Tyler"                    # → runs/<stamp>/
python3 seo_lens.py explain "universal runtime"                # every score term for one phrase
```

`harvest --feed` reads Blogger's own Atom feeds (`/feeds/posts/default`, `/feeds/pages/default`), which give full page HTML.
Checked live 2026-11-16: 171 pages + 9 posts, full content.
Fallbacks: `--sitemap https://blog.4xela.ai/sitemap.xml` · `--dir <folder of saved .html>` ·
no flag = rebuild `corpus.jsonl` from `work/cache/` with no network.

Everything after `harvest` runs offline.

### Getting the Search Console export
Search Console → **Performance** → date range (3 or 16 months) → **Export → Download CSV** (a zip).
`ingest` reads the zip as is: *Queries* and *Pages* are used; Countries, Devices, Dates and other tables are skipped and listed in the receipt.

The UI export has **no query × page pairs**. Without them each query is linked to its best-fit page and marked `INFERRED`.
For real pairs, export a table with both *query* and *page* columns (Search Console API, Looker Studio, or the
"Search Analytics for Sheets" add-on) and `ingest` it alongside the zip. Its rows are marked `PAIR`.

## Outputs (`runs/<stamp>/`)
| file | what |
|---|---|
| `report.md` | summary, quick wins, gaps, cannibalization (HIGH/MED), page suggestions, method |
| `quick_wins.csv` | phrase · page · impressions · position · link · action |
| `gaps.csv` | phrase · impressions · action (NEW POST / EXTEND) · suggested title + slug |
| `cannibalization.csv` | cluster · severity · owner · competing pages |
| `page_suggestions.csv` | current vs suggested title / H1 / description, with why + notes |
| `scores.csv` · `clusters.csv` | full working tables |
| `report.json` | the same findings for bots |
| `receipt.md` / `.json` | SHA-256 of inputs, config, outputs · counts · `RUN_HASH` · SIGNED line |

## Scoring (weights in `config/default.toml`, hashed into every receipt)

```
total = 0.35·demand + 0.25·quickwin + 0.25·fit + 0.15·distinct − 0.50·penalty
```
| term | meaning |
|---|---|
| demand | ln(1+impressions) ÷ ln(1+site max), for the phrase as a GSC query |
| quickwin | demand of the linked page row when its average position is 5–20 |
| fit | TF-IDF on the page ÷ the page's strongest phrase (title/H1 count ×2) |
| distinct | IDF ÷ IDF of a one-page phrase (rarity across the site) |
| penalty | share of glyph/jargon tokens (∆Z, XBCM…), only when the phrase has 0 impressions |

Candidates are 1–4-word n-grams that don't start or end on a stopword. That is a stand-in for noun phrases, not a parser.
Clusters use leader clustering on shared tokens + Jaccard / cosine. Each cluster's owner is the page with the most clicks, or the highest coverage if there are none.
Cannibalization severity: **HIGH** = both pages get impressions · **MED** = the cluster has demand · **LOW** = content overlap only.

Glyphs become plain words in suggestions through `[expand]` in the config, e.g. `urt → "Universal Runtime (URT)"`.

**Thin data:** the report warns when the site has fewer than 1000 impressions or fewer than 50 queries. On a small site, treat the rankings as hints.

## Guards
- Host allowlist (`blog.4xela.ai` only), robots.txt honoured, 1 request/s, named User-Agent.
- Real data lives only in `work/`, `runs/`, `private/` (all gitignored). Never commit a real GSC export.
- No credentials anywhere; a test fails if any appear.

## Tests
```bash
python3 -m pytest -q
```
40 tests on example.com fixtures (fake numbers) cover:
- extraction, n-gram rules, glyph flags
- harvest: feed paging, sitemap, allowlist, robots, rate limit, rebuild from cache
- ingest: zip, pairs, duplicates
- scoring maths, gaps, links, cannibalization, suggestions, explain
- **determinism**: same input gives the same RUN_HASH
- offline: all sockets are blocked during tests

## Layout
```
seo_lens.py            CLI entry
seolens/               text · extract · harvest · ingest · score · cluster · report · receipt · config · cli
config/default.toml    weights, thresholds, allowlist, glyph expansions
data/                  stopwords_en.txt · glyphs.txt
tests/                 fixtures/example.com/ + tests
samples/example.com/   a full report from the fixtures
```
