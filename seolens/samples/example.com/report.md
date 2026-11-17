# SEO LENS report

Draft suggestions only. SEO LENS never edits the site.

## Data

| item | value |
|---|---|
| pages (/p/) | 3 |
| posts | 2 |
| words | 279 |
| phrases scored | 60 |
| GSC queries | 5 |
| GSC query×page rows | 4 |
| GSC impressions (sum) | 243 |
| clusters | 34 |

> **Thin data.** Under 1000 impressions or 50 queries. Treat rankings as hints, not findings; weights are starting values, not tuned.

## Quick wins (avg position 5–20)

| phrase | page | impr | pos | link | total |
|---|---|---|---|---|---|
| workflow templates | https://example.com/p/workflow-templates.html | 80 | 8.2 | PAIR | 0.9381 |
| workflow templates | https://example.com/2026/01/free-workflow-templates.html | 40 | 15.0 | PAIR | 0.8774 |
| ai chat memory | https://example.com/p/memory-notes.html | 60 | 14.5 | PAIR | 0.8677 |

## Gaps (searched, no page is about it)

| phrase | impr | pos | action | suggested slug |
|---|---|---|---|---|
| pricing plans | 40 | 25.0 | NEW POST | /pricing-plans.html |
| getting started workflow | 8 | 3.1 | NEW POST | /getting-started-workflow.html |

## Cannibalization (two pages chasing one cluster)

| cluster | severity | seed | owner | competing |
|---|---|---|---|---|
| C001 | HIGH | workflow templates | https://example.com/p/workflow-templates.html | https://example.com/2026/01/free-workflow-templates.html |
| C002 | MED | ai chat memory | https://example.com/p/memory-notes.html | https://example.com/2026/02/getting-started.html |

9 LOW (content-overlap only, no search demand) in cannibalization.csv.

## Page suggestions (plain language first)

| page | suggested title | suggested H1 | why | notes |
|---|---|---|---|---|
| https://example.com/2026/01/free-workflow-templates.html | Free Workflow Templates | Free Workflow Templates | 'free workflow templates': fit 0.93 | no meta description found |
| https://example.com/2026/02/getting-started.html | Getting Started | Getting Started | 'getting started': fit 1.00 | no meta description found |
| https://example.com/p/memory-notes.html | Keep AI Chat Memory | Keep AI Chat Memory | 'keep ai chat memory': fit 0.66 |  |
| https://example.com/p/route-card.html | Task Routing — Route Card | Task Routing | 'task routing': fit 0.65, 15 impr, pos 32.0 (INFERRED) | current title starts with a glyph; no meta description found |
| https://example.com/p/workflow-templates.html | Reusable Workflow Templates — Small Teams | Reusable Workflow Templates | 'reusable workflow templates': fit 0.80 |  |

## Method

total = 0.35·demand + 0.25·quickwin + 0.25·fit + 0.15·distinct − 0.5·penalty

- **demand**: ln(1+impressions) ÷ ln(1+site max), for the phrase as a Search Console query
- **quickwin**: demand of the linked page row when avg position is 5–20
- **fit**: TF-IDF on the page ÷ the page's strongest phrase (title/H1 count double)
- **distinct**: rarity across the site (IDF, 1.0 = on one page only)
- **penalty**: glyph/jargon share of the phrase, only when it has 0 impressions
- Candidates are 1–4-word n-grams that don't start/end on a stopword: a stand-in for noun phrases, not a parser.
- `seo_lens.py explain "<phrase>"` prints every term for one phrase.

See receipt.md for input/config/output hashes.
