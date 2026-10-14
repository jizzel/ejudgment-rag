# Benchmark: our search vs GhaLII's site search

How often does each system put the right judgment in front of a researcher? This benchmark
runs the gold questions (`evals/gold.jsonl`) through both systems with the same query strings
and filters, and compares where the gold case appears in each.

It answers: *for a given question, does a lawyer find the right case in the first 20 results,
and how near the top?* It does not compare answers, speed or the full research process; see
"Not compared" below.

## The rule: GhaLII is searched by hand

GhaLII's terms of use prohibit scraping and bulk downloading (AGENTS.md, Source rights). So:

- A person runs every GhaLII search in an ordinary browser at a normal pace. No scripts,
  browser automation, scraping extensions, saved result pages or "export all".
- Record only the rank, the URL of the gold result and the result count. Never copy snippets
  or judgment text from GhaLII into the sheet.
- About 120 searches in all (60 questions × 2 query styles), spread over one or two sittings.
  That is ordinary use of a public search page.

Nothing in the tooling contacts GhaLII. It prepares the sheets and scores what was recorded.

## What is compared

**Two query styles ("arms")** for every question:

| Arm | Query |
|---|---|
| `verbatim` | The gold question exactly as written (how people use our search) |
| `keywords` | Keywords a researcher would type into a search box, written for each question by someone who has seen neither the gold answers nor either system's results, and never revised afterwards |

The keyword arm keeps the comparison fair to GhaLII, whose search is keyword-based. Our search
runs on the very same keyword string.

**Metrics** (answerable questions; the same definitions as `worker.evaluate`):

- **Recall@20**: the gold case is among the first 20 results.
- **MRR@10**: 1/rank of the first gold case if it is in the top 10, else 0, averaged.
- **Paired comparison**: the questions both systems found, only ours found, only GhaLII found,
  and neither found. Also an exact McNemar p-value on the questions only one system found.
  With about 50 questions, only a large difference will be significant.
- **By category**: citation, case name, issue, fact pattern.

A gold case counts wherever any of its publications appears. GhaLII publishes about 10% of
judgments under several URIs with identical text, and the recording sheet lists every
citation that counts.

**Outside-the-corpus questions** (9): only GhaLII's result count is recorded. Neither system
abstains at the search stage (ours returns nearest neighbours by design), so they are not
scored.

### Not compared

- **Speed:** the two systems run on different hardware and networks, so timings wouldn't be comparable.
- **Answers:** GhaLII has no answer generation.
- **Passages:** GhaLII shows snippets, but recording them would mean copying its text.
- **Research time** needs a separate timed study with lawyers.

## Roles

- **Query writer** (ideally a lawyer): sees only the questions and their filters, and writes one
  keyword query each. Must not see `look_for`, `evals/gold.jsonl` or any search results first.
- **Recorder**: runs the searches on GhaLII and fills the sheet. May be the same person, but
  only after the keyword queries are finished.

## Steps

### 1. Keyword queries

```bash
poetry run python -m ejudgment.worker.benchmark_ghalii queries --out evals/benchmarks/queries.csv
```

The directory is created if needed. Give `queries.csv` to the query writer. It has `id`, `category`, `question`, `filters` and an
empty `keyword_query` column. Fill in every row, the out-of-corpus questions included, then
leave the file unchanged.

### 2. Recording sheet

```bash
poetry run python -m ejudgment.worker.benchmark_ghalii sheet \
  --queries evals/benchmarks/queries.csv --out evals/benchmarks/ghalii-YYYY-MM-DD.csv
```

The sheet adds:

- `filters_to_apply`: the GhaLII facets to set, e.g. "Court: Supreme Court; Years: 2015-2020".
- `look_for`: every citation and URL that counts as the gold case.

It needs the database, which provides the citations and re-publications.

### 3. Searching GhaLII (by hand)

For each row, and for each arm (`verbatim` uses `question`, `keywords` uses `keyword_query`):

1. **Search:** open GhaLII's search page and type the query exactly as given.
2. **Facets:** set the facets in `filters_to_apply`.
   - If GhaLII lets you limit results to judgments, do so for every search, and note it once.
   - If a facet doesn't exist, search without it and say so in `notes`. Our search would
     then be the stricter of the two.
3. **Ordering:** keep GhaLII's default relevance ordering.
4. **Find the gold case:** read the results in order, pages 1 and 2 if a page shows 10.
   Find the first result whose citation or link matches `look_for`.
5. **Fill in the sheet:**
   - **`<arm>_rank`:** its position as displayed, counting every result above it (1–20).
     Write `none` if no gold case is in the first 20.
   - **`<arm>_url`:** that result's link, copied from the browser. Leave it empty with `none`.
   - **`<arm>_result_count`:** the total number of results GhaLII reports. It is optional for
     answerable questions and required for out-of-corpus ones, which get no rank or URL.
   - **`searched_on`:** the date (`YYYY-MM-DD`).
   - **`notes`:** anything unusual: a facet that was missing, the search failing, or GhaLII
     correcting the query.

Never change a query after seeing its results, on either arm.

### 4. Score

```bash
poetry run python -m ejudgment.worker.benchmark_ghalii score --sheet evals/benchmarks/ghalii-YYYY-MM-DD.csv
```

1. **Check the sheet.** Scoring first checks every row and lists all the problems in one
   go, then stops. A problem is a missing rank, a rank above 20, a missing URL, a URL that
   isn't a gold case of that question (a recording slip), or a count missing on an
   out-of-corpus question. It also catches a row that appears twice, and a row whose question
   or filters (the `filters` column) no longer match the gold set. A question edited
   after the sheet was made has to be searched again, because our side always searches the
   current wording.
2. **Run our search.** It runs our default search (hybrid + rerank, top 20) on the same
   query strings and filters.
3. **Store the run.** It saves an `evaluation_runs` row with `config.kind = "ghalii_benchmark"`.
   The config has the gold-file and sheet hashes, models, settings, corpus version and search dates,
   plus the per-question ranks of both systems. It prints the metrics.

Commit the filled sheet under `evals/benchmarks/`. It holds only questions, queries, ranks and
GhaLII URLs, no corpus text, and makes the run reproducible.

## Reading the result honestly

- **Provisional:** the gold questions are engineer-drafted and unreviewed. Every figure is
  provisional until a lawyer has reviewed them. The run also reports `reviewed` metrics over
  approved questions only.
- **Corpus differences:** GhaLII's collection is larger and newer than our export snapshot.
  It also includes the 551 judgments our export only has as placeholder pages. Newer
  judgments may legitimately rank above an older gold case on GhaLII.
- **How the gold cases were chosen:** they were found by keyword search in the database and
  by reading the judgments, never by our search ranking. That if anything favours keyword
  search, but the questions were written knowing our corpus.
- **The sheet is one point in time:** GhaLII's ranking may change. Our side is re-run at
  scoring time, so score soon after recording, and don't change search settings in between.
- **Small numbers:** with about 50 answerable questions, report the paired counts alongside
  the percentages and don't over-read differences of a few questions.
