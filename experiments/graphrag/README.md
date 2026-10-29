# GraphRAG research code

Research stream on when explicit citation structure improves retrieval beyond E-Judgment's hybrid baseline. The contract is [`docs/graphrag/AGENTS.md`](../../docs/graphrag/AGENTS.md); the root `AGENTS.md` stays binding.

Nothing here changes production search, the schema, the API or the UI. All database access is read-only, and nothing contacts GhaLII.

## What exists (Phase 0, Phase 1 and the Phase 1.5 resolver hardening)

| Module | Purpose |
|---|---|
| `manifest.py` | The research-log manifest every run writes: git SHA (and whether the tree was dirty), corpus fingerprint (`ejudgment.evaluation.retrieval.corpus_version`), extractor/resolver versions, graph build id, query-set hash, configuration. |
| `baseline.py` | Phase 0. Links the newest stored retrieval evaluation that ran with the current configuration (gold file, ranking settings, model ids and revisions, embedding template) *and* corpus and vector fingerprint, and records it with the gold-set state. Refuses, listing what differs, if there is none. |
| `extraction/citations.py` | Bracketed and unbracketed citations, classified by court or series token: neutral (`[2019] GHASC 12`), law report (`[1992] 1 GLR 123`) or unclassified. |
| `extraction/case_names.py` | `A v B` references, each side bounded and reduced to its significant words; surname anchors; ex parte applicants. |
| `extraction/identifiers.py` | Signals that single out one decision of a case: application, communication and suit numbers, stage labels, explicit judgment dates. |
| `extraction/mentions.py` | Joins a name with the citations right after it into one reference (parallel citations included); reads each reference's signals and caption markers; computes its evidence sentence. |
| `resolution/index.py` | Eligible judgments grouped into cases by `source_text_hash`, indexed by neutral citation and title words. |
| `resolution/resolve.py` | The resolution policy, its statuses, methods and evidence tiers (A neutral exact; B name + identifier, report year or judgment date; C name only). See the module docstring. |
| `resolution/audit.py` | Seeded audit sheets for a person to mark, sampled per tier and stratified within it; `--exclude` leaves out references an earlier sheet covered. |
| `coverage/profile_mentions.py` | Streams every eligible chunk in one read-only transaction and writes references with resolutions. |
| `graph/policy.py` | Phase 2 admission policies, each frozen against one audited build (`phase2-v1`: `neutral_exact`, `name_with_report`, `name_with_date` over `3325b81913b3`). |
| `graph/build.py` | The deterministic `CITES` graph: case nodes, edges with every occurrence's provenance, review items, fingerprint. |
| `graph/traverse.py` | Bounded traversal: outgoing (authorities relied on) and incoming (later treatment), with depth, node, branching and hub limits. |
| `graph/stats.py` | Degree, components, path lengths, coverage by court and decade, temporal anomalies. |
| `graph/rdf.py` | Turtle export: AKN URIs, `cito:Citation` nodes with PROV provenance, no corpus text. |
| `graph/verify.py` | End-to-end provenance audit of every occurrence against the database. |
| `pilot/questions.py` | Phase 3 question format; intents and gold locked separately before any run. |
| `pilot/seeds.py` | Blind seed sheet of candidate anchors (degree hidden from the writer). |
| `pilot/gold_finder.py` | Gold candidates by text search, independent of the resolver and the graph; import of marked sheets. |
| `pilot/run.py` | B0, B0R (rescoring control), G1-oracle, G1-both and G2-oracle on the locked set. |
| `pilot/report.py` | Per class and system, paired against B0 and B0R. |
| `coverage/report.py` | Aggregate statistics (Phase 1 questions 1–8) by method and tier, graph shape per policy (`tier_A`, `tiers_A_B`, `tiers_A_B_C`), and with `--audit` precision as n/N per method and tier against the Phase 2 gate. |

Tests: `tests/research/graphrag/` (unit, no database) and `tests/integration/test_graphrag_coverage.py` (end to end on the synthetic fixture).

## Running

```bash
poetry run python -m ejudgment.worker.evaluate                # only if no evaluation matches the current corpus
poetry run python -m experiments.graphrag.baseline            # -> runs/baseline_<date>.json

poetry run python -m experiments.graphrag.coverage.profile_mentions        # ~35 s for 159k chunks
poetry run python -m experiments.graphrag.coverage.report --build <id>     # -> runs/coverage_<id>.json/.md
poetry run python -m experiments.graphrag.resolution.audit --build <id> \
    [--per-tier A=40,B=60,C=20] [--exclude artifacts/edge_audit_<old>.csv ...]   # -> artifacts/edge_audit_<id>.csv, review_<id>.csv
# after the edge audit sheet is filled in (y/n for mention_ok, target_ok, span_ok, evidence_ok, temporal_ok):
poetry run python -m experiments.graphrag.coverage.report --build <id> --audit experiments/graphrag/artifacts/edge_audit_<id>.csv
# a targeted re-audit of one method:
poetry run python -m experiments.graphrag.resolution.audit --build <id> --methods name_with_identifier --per-tier B=40 --review 0 --exclude ...

poetry run python -m experiments.graphrag.graph.build [--policy phase2-v1]   # -> artifacts/graph_<policy>_{nodes,edges,review}.jsonl, .ttl; runs/graph_<policy>.json/.md
poetry run python -m experiments.graphrag.graph.verify [--policy phase2-v1]  # every occurrence traced to the database; exit 1 on any failure

# Phase 3 pilot (docs/graphrag/phase3-pilot.md)
poetry run python -m experiments.graphrag.pilot.seeds                       # -> artifacts/pilot_seeds.csv (+ key)
poetry run python -m experiments.graphrag.pilot.questions import-intents --sheet <csv>
poetry run python -m experiments.graphrag.pilot.questions draw-locals && poetry run python -m experiments.graphrag.pilot.questions lock-intents
poetry run python -m experiments.graphrag.pilot.gold_finder sheet --question <id>     # then mark it, and:
poetry run python -m experiments.graphrag.pilot.gold_finder import --question <id> --sheet <csv> [--path a,b,c]
poetry run python -m experiments.graphrag.pilot.questions lock-gold
poetry run python -m experiments.graphrag.pilot.run                         # -> runs/pilot_<hash>.json/.md + evaluation_runs
```

The build id hashes the extractor and resolver versions, the corpus digests and the run's configuration (so a `--limit` run gets its own id). Bump the `VERSION` constant of a module whenever its output changes, so that a new build gets a new id.

## What may be committed

- **Committed:** code, tests, and the aggregate files in `runs/`: counts, court codes, citation keys and report-series names, never passage text.
- **Never committed:** everything in `artifacts/`, which is gitignored. The mention files and audit sheets quote the corpus, and the corpus must not be redistributed (docs/graphrag/AGENTS.md rule 8).

## Research log fields

Each run's JSON carries `run_id`, `git_sha`, `git_dirty`, `timestamp`, `corpus_fingerprint`, `graph_build_id`, `mention_extractor_versions`, `resolver_versions`, `rdf_schema_version`, `query_set_hash`, `baseline_config`, `graph_config`, `models`, `metrics` and `notes`. A result without these is not used in claims.
