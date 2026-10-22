# GraphRAG research stream: execution contract

> **Status:** research plan and scoped agent contract for the `research/graphrag` branch.
> **Parent contract:** the repository root `AGENTS.md` remains binding. If this file conflicts with it, the root contract wins.
> **Scope:** research code under `experiments/graphrag/`, supporting tests and research documentation. Nothing here authorizes weakening the production system's provenance, rights, verification or evaluation guarantees.
> **Application context:** the immediate Ghent University application is time-sensitive, but the research stream is not a disposable application demo. It should remain useful if the application succeeds, fails, or leads to a later collaboration.

## Mission

Investigate when explicit graph structure improves legal information retrieval beyond E-Judgment's existing strong baseline, and how graph-aware retrieval can be added without sacrificing source-level provenance.

The research question is not **"Does GraphRAG beat RAG?"** It is:

> **When, for which legal information needs, and under what graph construction and traversal strategy does explicit relational structure improve retrieval beyond exact lookup plus lexical-dense hybrid retrieval and reranking?**

The long-term objective is an adaptive legal research architecture that can choose among:

1. exact citation or case-name lookup;
2. existing lexical + dense hybrid passage retrieval;
3. deterministic graph expansion;
4. hybrid retrieval plus graph expansion;
5. provenance-backed semantic relationship retrieval;
6. multi-step or agentic graph exploration;

while retaining the existing source-grounding and verification model.

## Research hypotheses

### H1: local-query baseline

For local questions whose answer is contained in one judgment or a small number of semantically matching passages, the existing hybrid system will remain competitive with or outperform graph expansion.

### H2: relational retrieval

Graph augmentation will improve retrieval for questions that explicitly ask about relationships between judgments, especially questions about cases cited by a judgment or later judgments that cite an earlier authority.

### H3: temporal crossover

The largest graph advantage is expected on **forward-looking subsequent-treatment questions**. A judgment can cite only authorities available to it at the time, while later judgments can cite that earlier judgment. Therefore:

- `CITES` edges are stored from the later/citing case to the earlier/cited case;
- "what did this case rely on?" traverses outgoing edges;
- "how was this case treated later?" traverses incoming edges;
- multi-hop doctrinal development often alternates semantic retrieval with forward traversal.

The graph must never interpret absence of an incoming or outgoing edge as proof that no citation exists.

### H4: adaptive retrieval

A query-adaptive system should outperform a policy that forces graph traversal for every question, because graph expansion introduces latency and irrelevant candidates when the information need is local.

### H5: provenance-preserving semantic graphs

LLM-assisted relation extraction may add useful edges such as `FOLLOWS`, `DISTINGUISHES`, `APPLIES`, `CRITICISES` or `OVERRULES`, but only if every relation remains an evidence-backed assertion with source spans and explicit extraction/verification state. An LLM-created edge is never authoritative merely because it exists in the graph.

These hypotheses may be rejected. A negative result is useful if the evaluation is fair.

---

# Non-negotiable research rules

## 1. Keep the production baseline strong

Do not weaken E-Judgment to make graph retrieval look good.

Every graph experiment must compare against the current default retrieval path:

- deterministic citation/case-name lookup where applicable;
- Postgres lexical retrieval;
- dense retrieval;
- reciprocal rank fusion;
- cross-encoder reranking;
- case grouping and re-publication collapsing.

A vector-only baseline may be reported as a secondary reference, but the main comparison is against the real E-Judgment baseline.

## 2. Graph edges need provenance

A text-derived edge must be traceable to source material.

At minimum, a citation edge stores or can reproduce:

- source judgment;
- target judgment when resolved;
- relation type;
- matched text;
- source chunk;
- character offsets within the chunk or source text;
- source URI;
- extraction method;
- resolver method and resolver version;
- resolution confidence/status;
- source quality metadata relevant to the edge.

For OCR-derived text, retain the source extraction method and OCR confidence where available. Do not present OCR confidence as semantic confidence.

## 3. Separate mention, resolution and legal treatment

These are different claims:

1. **Mention:** a passage contains text resembling a legal citation or case reference.
2. **Resolution:** the mention refers to a specific judgment in the corpus.
3. **Treatment:** the citing court followed, applied, distinguished, criticised, disapproved or overruled the cited authority.

Do not collapse them.

The deterministic graph initially asserts only a conservative relationship such as `CITES` or `MENTIONS_CASE` when resolution is sufficiently reliable. It does not infer treatment.

## 4. Temporal direction is first-class

A normal precedent citation should point from a later judgment to an earlier judgment.

A resolved edge whose target judgment date is later than its source judgment date must be flagged for review, not silently discarded or accepted. Possible explanations include:

- bad metadata;
- re-publication/expression dates;
- an incorrectly resolved case name;
- a reference to later procedural history in a republished text;
- extraction noise.

Temporal inconsistency is diagnostic evidence.

## 5. Absence is never legal evidence

Coverage will be incomplete because:

- some older authorities are cited by law-report citation rather than neutral citation;
- case-name references vary;
- some cited authorities predate the corpus or are missing from it;
- some text is OCR-derived;
- some source records are quarantined or lack usable text.

"No edge" means only "no resolved edge was found by this graph build."

## 6. No benchmark construction from system output

Do not inspect graph traversal results and then write questions whose gold answers are those results.

Question **intents** must be written before running competing retrieval systems.

Gold cases and gold passages must be established from source judgments and citing passages, not copied from a system's ranked output.

Any pilot derived from targeted graph sampling must document the sampling procedure and the resulting selection bias.

## 7. No significance theatre

A small pilot such as eight questions per class is exploratory.

Reuse the existing paired/McNemar machinery where useful, but report:

- per-question outcomes;
- paired counts;
- effect sizes/descriptive differences;
- confidence limitations.

Do not claim statistical significance or general legal-domain superiority from a tiny hand-curated set.

## 8. No new corpus acquisition by scraping

The existing export was created previously by a scraper. GhaLII's current terms prohibit scraping and bulk downloading.

Research may use the existing local export non-commercially under the documented CC BY-NC conditions and the repository's source-rights rules. New data must come only from:

- GhaLII's official API with permission/credentials; or
- another separately licensed source.

Do not offer the existing corpus as a dataset to collaborators. Code, schemas, derived aggregate statistics and methods may be shared subject to their own licences.

A request for GhaLII API research access is a parallel action, not a blocker for analysing the existing lawful local research corpus.

## 9. Framework independence first

The vacancy mentions tools such as LangChain. This project deliberately starts with small typed modules and explicit data contracts rather than an agent framework.

Reasons:

- easier provenance auditing;
- deterministic evaluation;
- fewer hidden retrieval decisions;
- easier ablation;
- easier comparison with the existing codebase.

A framework may later be introduced if it solves a measured problem. It is not a research objective.

## 10. Research code stays isolated until it earns promotion

Initial implementation belongs under:

```text
experiments/graphrag/
```

Do not change production search semantics, database schema, API responses or UI behaviour merely to support an experiment.

Stable components move into `src/ejudgment/` only after satisfying the promotion gates later in this document.

---

# Baseline facts to preserve

The current E-Judgment system is a **hybrid-retrieval RAG with a verification layer**, documented in:

- `docs/architecture.md`;
- `docs/rag-comparison.md`;
- root `AGENTS.md`.

The current research corpus contains thousands of Ghanaian judgments and roughly 159k passage chunks. Retrieval combines exact lookup, lexical search, dense search, RRF and a cross-encoder reranker. Generation is source-grounded and post-verified.

The current graph research exists because the baseline is still fundamentally **chunk-local**. It has no explicit representation for relationships such as:

- judgment cites judgment;
- judgment is cited by later judgment;
- judgment mentions/interprets a statutory provision;
- judge participates in judgment;
- court decides judgment;
- semantic treatment of an authority;
- multi-hop line of authority.

Do not rewrite `docs/rag-comparison.md` inside this plan. Amend that document separately after the research gives us evidence.

---

# Research architecture

## Core distinction

The graph has two layers.

### Evidence graph

High-confidence relations supported directly by existing metadata or a text span.

Examples:

```text
Judgment --CITES--> Judgment
Judgment --DECIDED_BY--> Judge
Judgment --DECIDED_AT--> Court
Judgment --MENTIONS_STATUTE--> StatutoryProvision
```

The first research milestone is primarily the judgment citation graph.

### Semantic assertion graph

Relations whose type requires interpretation.

Examples:

```text
Judgment --FOLLOWS--> Judgment
Judgment --APPLIES--> Judgment
Judgment --DISTINGUISHES--> Judgment
Judgment --CRITICISES--> Judgment
Judgment --DISAPPROVES--> Judgment
Judgment --OVERRULES--> Judgment
```

Every semantic edge is treated as an **assertion about a passage**, not an unquestionable graph fact.

Suggested conceptual record:

```text
relation_id
source_judgment_id
target_judgment_id
relation_type
source_chunk_id
support_start
support_end
support_text_hash
extractor_kind
extractor_model
extractor_version
confidence
verification_status
review_status
created_at
```

Do not create the production schema for this during early phases. Use experiment-local serializations first.

---

# Repository layout

Use the research branch:

```text
research/graphrag
```

Initial structure:

```text
docs/
└── graphrag/
    └── AGENTS.md

experiments/
└── graphrag/
    ├── README.md
    ├── coverage/
    │   ├── profile_mentions.py
    │   └── report.py
    ├── extraction/
    │   ├── neutral_citations.py
    │   ├── law_reports.py
    │   ├── case_names.py
    │   └── mentions.py
    ├── resolution/
    │   ├── exact.py
    │   ├── case_name.py
    │   └── audit.py
    ├── graph/
    │   ├── model.py
    │   ├── build.py
    │   ├── traverse.py
    │   └── rdf.py
    ├── retrieval/
    │   ├── expand.py
    │   ├── rank.py
    │   └── adaptive.py
    ├── evaluation/
    │   ├── questions.py
    │   ├── run.py
    │   └── report.py
    └── artifacts/
        └── .gitkeep
```

This is a target shape, not a requirement to create empty files up front. Build only what a phase needs.

Generated artifacts containing corpus-derived text should normally stay out of Git. Commit schemas, aggregate results, manually approved evaluation questions where rights permit, and reports without unnecessary source-text reproduction.

Unit/integration tests may live under a clearly scoped `tests/research/graphrag/` tree if that is cleaner than colocating them.

---

# Phase 0: freeze the research baseline and application track

## Goal

Ensure the GraphRAG work begins from a reproducible E-Judgment baseline and does not become a gate on the Ghent application.

## Work

1. Record:
   - current commit SHA;
   - corpus fingerprint;
   - retrieval model revisions;
   - current default retrieval settings;
   - baseline gold-set state;
   - current baseline Recall@20, MRR@10 and latency where reproducible.

2. Keep the Ghent application on a parallel track.
   - Experiment completion is **not** a prerequisite for submission.
   - Coverage statistics, a trustworthy graph build and an audited sample of edges are already enough to support a credible research paragraph.
   - Target application submission remains around **27-28 October 2026**, earlier if the package is ready, because the vacancy may fill before 31 October.

3. Prepare a concise research log template for every experimental run:
   - code SHA;
   - corpus fingerprint;
   - graph build ID;
   - resolver versions;
   - query set hash;
   - retrieval configuration;
   - model versions;
   - timestamp;
   - aggregate metrics.

## Exit criteria

- baseline is reproducible;
- graph work is isolated on the research branch;
- application work is not waiting for later phases.

---

# Phase 1: citation and case-reference coverage audit

## Why this phase comes first

The largest technical risk is graph sparsity.

Ghanaian judgments frequently cite authorities using:

- neutral citations;
- Ghana Law Reports and other report citations;
- party names such as `X v Y`;
- abbreviated or historical citation styles.

Some cited authorities are not present in the corpus at all.

Therefore the graph benchmark must not be designed until we know what relationships can actually be resolved.

## Questions

Measure at minimum:

1. How many judgment chunks contain neutral-citation-shaped mentions?
2. How many contain law-report-shaped citations?
3. How many likely case-name references exist?
4. How many mentions resolve uniquely to a corpus judgment?
5. How many are ambiguous?
6. How many point to an authority absent from the corpus?
7. How does coverage vary by:
   - decade/year;
   - court;
   - source extraction method;
   - OCR vs machine-readable text;
   - citation style?
8. How many judgments have:
   - at least one outgoing resolved citation;
   - at least one incoming citation;
   - no graph degree;
   - a path length >= 2 within the resolved graph?

## Extraction order

### A. Neutral citations

Start with deterministic patterns and exact normalization.

These are expected to have high precision but potentially low recall.

### B. Law-report citations

Profile patterns such as GLR references separately.

Do **not** fabricate a mapping from report citations to GhaLII judgments. If the corpus does not contain a reliable report-citation field, report the gap.

Later resolution may use source text, case name and metadata, but it must remain auditable.

### C. Case-name mentions

Reuse the existing query/case-name normalization concepts where possible:

- normalized party sides;
- `v`, `vs`, `v.`, `versus` variants;
- punctuation normalization;
- existing PostgreSQL trigram support.

Candidate generation may be fuzzy. Final deterministic graph inclusion must require a documented resolution policy.

Example statuses:

```text
resolved_exact
resolved_unique_fuzzy
ambiguous
target_absent
unresolved
temporal_conflict
```

A fuzzy score alone is not enough to create an unquestioned edge.

## Deliverables

- coverage profiler;
- machine-readable aggregate statistics;
- resolver error taxonomy;
- sample of unresolved mentions;
- manually audited random sample of resolved edges;
- short coverage report.

## Edge audit

Randomly sample resolved edges across:

- citation type;
- court;
- time period;
- OCR/non-OCR source.

For each edge inspect:

- whether the mention exists;
- whether the target case is correct;
- whether the span is correct;
- whether temporal ordering is plausible.

Report edge precision with numerator and denominator, not just a percentage.

## Gate

**Do not freeze the evaluation-question classes or counts before this phase finishes.**

If the graph is too sparse for the planned 24-question pilot, change the pilot rather than lowering resolver precision.

---

# Phase 2: deterministic, provenance-preserving legal graph

## Goal

Build the highest-confidence graph the corpus supports without semantic LLM inference.

## Initial node types

Required:

- Judgment.

Cheap metadata-backed nodes may be added where useful:

- Court;
- Judge;
- Year/date.

Statute/section nodes are optional in this phase unless extraction proves reliable enough.

## Required edge

```text
Judgment --CITES--> Judgment
```

The reverse `CITED_BY` relation is queryable but need not be stored as a duplicate edge.

## Citation edge semantics

A `CITES` edge means:

> a source passage in judgment A contains a case reference that the resolver linked to judgment B with the recorded resolution status.

It does **not** mean:

- A followed B;
- A approved B;
- A relied on B as decisive authority;
- B remains good law.

## Temporal checks

For each resolved edge:

```text
source judgment date >= target judgment date
```

is the expected normal relation.

Violations are recorded as review items.

Do not use expression/publication date blindly where AKN re-publications complicate chronology. Keep enough metadata to inspect the anomaly.

## Graph storage

During research, prefer portable experiment artifacts over a graph database:

- JSONL/Parquet for edge records;
- in-memory adjacency maps for traversal;
- PostgreSQL only when reuse of the existing corpus is necessary.

Do not add Neo4j simply to obtain a graph-shaped persistence layer.

## RDF / semantic-web representation

Produce a standards-oriented RDF export as an experiment artifact.

Reasons:

- canonical judgment identity already uses AKN URIs;
- the Ghent vacancy explicitly values semantic technologies and existing schemas;
- RDF provides a useful comparison with a property-graph/in-memory representation.

Requirements:

- use the existing canonical AKN URI as the judgment identifier where possible;
- choose predicates deliberately;
- preserve edge provenance rather than exporting bare triples only;
- document whether provenance uses reification, RDF-star or another explicit pattern;
- do not invent ontology equivalences merely to make the RDF look richer.

An RDF export is a representation of the same evidence graph, not a separate source of truth.

## Deliverables

- deterministic graph builder;
- reproducible graph fingerprint;
- graph statistics:
  - nodes;
  - edges;
  - degree distribution;
  - connected components;
  - path-length distribution;
  - coverage by court/year;
  - temporal anomalies;
- RDF/Turtle export for a rights-safe derived representation;
- edge provenance audit.

## Gate

Advance to retrieval evaluation only if:

- edge precision is acceptable;
- provenance can be traced end to end;
- graph density is sufficient to support at least one meaningful relational question class.

---

# Phase 3: graph-augmented retrieval pilot

## Goal

Measure whether graph structure adds retrieval value beyond the current hybrid baseline.

## Systems

### B0: current baseline

Existing default E-Judgment retrieval.

### G1: one-hop expansion

1. retrieve seed cases with B0;
2. traverse outgoing and/or incoming citation edges according to query intent;
3. retrieve evidence passages associated with expanded cases/edges;
4. rerank candidates against the original query using existing relevance machinery.

### G2: bounded multi-hop expansion

Same as G1, with bounded traversal depth and explicit controls for:

- maximum nodes;
- maximum edges;
- per-node branching;
- path cycles;
- repeated visits;
- high-degree authority hubs.

### Optional G3: graph as an additional ranking signal

Only after G1/G2 are measurable, test graph-derived signals such as:

- distance from a semantic seed;
- incoming citation support;
- path multiplicity;
- recency conditioned on query type.

Do not blindly insert graph popularity into RRF and call it useful.

## Directional retrieval

The system must distinguish:

- **authority search:** traverse outgoing edges from a known/largely matched case;
- **subsequent-treatment search:** traverse incoming edges;
- **line-of-authority search:** bounded multi-hop traversal;
- **local substantive query:** graph may be skipped.

## Question construction protocol

Do not decide "8 per class" until Phase 1 shows what is feasible.

Candidate classes include:

1. local/single-case controls;
2. direct outgoing-authority questions;
3. direct incoming/subsequent-citation questions;
4. multi-hop lineage questions;
5. global/aggregate questions, only if the graph supports them.

For the pilot:

- write question intents before running B0/G1/G2;
- lock wording before evaluation;
- derive gold cases from source judgments/citing passages;
- record how each question was sampled;
- ensure at least some questions are not selected merely because the graph already exposed a convenient path;
- keep existing local questions as controls.

## Metrics

Required:

- Recall@20;
- MRR@10;
- multi-gold case recall where appropriate;
- latency;
- candidate-set expansion;
- number of graph nodes/edges visited;
- retrieval failures by question class.

Useful graph-specific metrics:

- path recall;
- seed recall;
- expansion precision;
- first-relevant-hop distance.

Report results per question class and per direction, not only one aggregate number.

## Statistical interpretation

At pilot scale:

- use paired outcomes;
- reuse McNemar tooling if convenient;
- report exact counts;
- do not make significance claims from a tiny, constructed set;
- treat the result as hypothesis-generating.

## Deliverables

- locked pilot question set;
- B0/G1/G2 evaluation runner;
- run manifest/fingerprint;
- results table;
- error analysis;
- short research note.

## Decision outcomes

All three outcomes are valuable:

### Graph wins on relational questions

Supports H2/H3 and motivates adaptive routing.

### Graph helps only marginally

Investigate resolver coverage, seeding, traversal policy and reranking before claiming graph value.

### Graph underperforms

Document why. If the deterministic graph is too sparse or noisy, that directly motivates richer graph construction research rather than hiding the result.

---

# Phase 4: semantic legal-treatment assertions

## Goal

Move from "A cites B" to evidence-backed candidate interpretations of how A treats B.

## Relation taxonomy

Start small. Candidate types may include:

- follows;
- applies;
- approves;
- distinguishes;
- criticises;
- disapproves;
- overrules.

Do not freeze the taxonomy until a sample of Ghanaian judgments is inspected. Legal language and reporting conventions should drive it.

## Extraction architecture

Prefer a staged pipeline:

1. deterministic citation/case mention identifies the source-target pair;
2. collect a bounded context window around the mention;
3. LLM or classifier proposes a treatment label plus exact supporting span;
4. deterministic checks verify:
   - cited target appears in context;
   - quoted support exists verbatim;
   - output schema is valid;
5. NLI or specialised classifier may verify relation compatibility;
6. unresolved or low-confidence assertions remain candidates;
7. human review provides an evaluation set.

Use Ollama/local models first where practical so the pipeline is reproducible and corpus text stays local.

## Trust model

A semantic edge must expose:

- proposed relation;
- evidence passage;
- extractor/model;
- verification status;
- human review status.

The retrieval system may distinguish:

```text
deterministic
model_extracted_unverified
model_verified
human_verified
```

Never silently mix them.

## Deliverables

- treatment taxonomy;
- labelled development sample;
- extraction pipeline;
- relation-level precision/recall where a reviewed set exists;
- error taxonomy;
- comparison of deterministic citation-only versus semantic-treatment retrieval.

## Gate

Semantic treatment edges do not become production retrieval signals until their error rate is known and the UI/API can expose their evidential status.

---

# Phase 5: query-adaptive retrieval

## Goal

Test H4: use graph work only when the query requires it.

## Router

Start with transparent rules/features before a learned or LLM router.

Potential signals:

- exact case citation detected;
- explicit temporal language: "later", "subsequent", "after";
- relational verbs: "cite", "follow", "distinguish", "overrule";
- aggregate language: "line of authority", "development", "trend";
- number of entities/cases recognized;
- confidence of baseline retrieval;
- graph degree of seed case.

Possible actions:

```text
EXACT
HYBRID
HYBRID_PLUS_INCOMING_GRAPH
HYBRID_PLUS_OUTGOING_GRAPH
MULTIHOP_GRAPH
```

## Evaluation

Compare:

- always-hybrid;
- always-graph-enhanced;
- rule-based adaptive;
- learned/LLM-adaptive only if enough labelled queries exist.

Metrics include retrieval quality, latency and graph work performed.

A router that preserves quality while avoiding unnecessary traversal is a successful result.

---

# Phase 6: controlled agentic graph exploration

## Goal

Explore the Ghent/GraphWalker-style research problem only after the graph and evaluation framework are trustworthy.

Agentic traversal is not the starting point.

## Research questions

- how should the system select starting nodes?
- when should it branch?
- can independent graph paths be explored in parallel?
- how should redundant traversal be detected?
- when should the system stop?
- how should uncertainty be exposed?
- how should every reasoning step remain traceable to graph edges and source passages?
- how does agentic traversal compare with deterministic BFS/bounded expansion on the same queries?

## Constraints

Every agent action must be logged as structured data:

```text
query
step
current_node
available_edges
chosen_edge
reason
supporting_source
visited_set
stop_condition
```

The model may choose among available graph operations. It may not invent unavailable nodes or edges.

Plain typed tools should remain the reference implementation even if LangChain or another framework is tested later.

## Deliverables

- deterministic traversal baseline;
- agentic traversal strategy;
- trace logs;
- multi-hop evaluation;
- cost/latency comparison;
- failure analysis.

---

# Phase 7: production promotion and research communication

## Production promotion gates

A research component may move into `src/ejudgment/` only when:

1. its semantics are documented;
2. provenance is preserved;
3. tests cover false-positive and ambiguous cases;
4. graph build is reproducible;
5. evaluation shows a clear use case;
6. failure modes are visible to the user;
7. rights implications are reviewed;
8. no graph edge is presented as stronger legal treatment than its evidence supports;
9. existing search behaviour does not regress without an explicit product decision.

Possible future production components:

- `src/ejudgment/graph/`;
- `src/ejudgment/retrieval/graph.py`;
- "cites" / "cited by" evidence views;
- adaptive retrieval mode;
- semantic treatment view with review status.

## Research outputs

Potential outputs include:

- Ghent application evidence;
- PhD correspondence;
- technical report/preprint;
- reproducible graph-retrieval benchmark methodology;
- conference/workshop submission;
- public technical walkthrough or video;
- open-source graph tooling without corpus redistribution.

The Ghent vacancy values outreach. Once results are mature, produce at least one clear public artifact, for example:

- architecture explainer;
- short demonstration video;
- blog post;
- conference-style poster.

Do not publish corpus text beyond what the underlying licence permits.

---

# Immediate application track

The application should not wait for every research phase.

## Minimum credible evidence before submission

Any one of the following is useful:

- measured citation/reference coverage;
- deterministic graph statistics;
- audited edge precision;
- a small RDF export showing AKN-based identifiers and source provenance;
- an initial B0 vs G1 comparison;
- a documented negative finding about graph sparsity.

The motivation letter should describe work accurately, for example:

> I am currently extending E-Judgment, a provenance-preserving hybrid legal RAG system, with a research branch that first measures citation-graph coverage and constructs auditable case-to-case relations before testing graph-aware retrieval against the existing hybrid baseline.

Do not claim GraphRAG performance results until they exist.

## Application-specific fit points to retain

Use these honestly:

- hybrid retrieval baseline already implemented;
- source-level provenance and post-generation verification;
- AKN identifiers already provide a standards-oriented identity layer;
- RDF export is a natural semantic-web extension;
- OCR is part of the ingestion pipeline with quality/confidence metadata;
- local Ollama usage demonstrates hands-on LLM deployment;
- deliberate avoidance of hidden framework behaviour demonstrates engineering judgment;
- the project has a public-facing UI and can support outreach/demo work.

---

# External-data and collaboration track

## GhaLII API access

Prepare a concise research access request that states:

- the non-commercial research purpose;
- the existing export is not being refreshed by scraping;
- new data would only be obtained through the official API;
- attribution and source links are preserved;
- the research studies retrieval/graph methods, not republication of the corpus;
- data would not be offered onward as an open dataset without permission.

Do not state or imply that permission has been granted until it has.

## External collaboration

If Ghent or another group is interested before formal PhD commencement:

- share code, schemas, aggregate statistics and method descriptions;
- share corpus-derived samples only where the licence clearly permits;
- do not transfer the local corpus by default;
- document any new data-sharing agreement separately.

---

# Failure modes to actively look for

## Sparse graph

Symptom: few resolved edges, especially in older judgments.

Response:

- report it;
- quantify unresolved law-report and case-name references;
- improve resolution cautiously;
- do not lower precision just to inflate graph density.

## Hub explosion

Symptom: famous authorities dominate expansion.

Response:

- cap branching;
- use query relevance after expansion;
- test degree-normalised signals;
- report candidate growth.

## Temporal leakage

Symptom: query/evaluation construction uses future citations in a way unavailable to the historical case.

Response:

- distinguish historical "what could this court have relied on?" from retrospective "how was this case treated later?";
- encode the direction explicitly in the question class.

## Circular evaluation

Symptom: graph paths generate both the questions and the gold answers.

Response:

- freeze intents first;
- validate against source passages;
- record sampling process;
- include baseline/local controls.

## Semantic-edge hallucination

Symptom: treatment relation sounds legally plausible but the cited passage does not support it.

Response:

- keep the candidate unverified;
- require verbatim support;
- run relation verification;
- sample for human review.

## Rights drift

Symptom: an experiment starts fetching missing judgments from the public site.

Response:

- stop;
- use official API only after access is documented.

---

# Research log: required fields

Every significant run should record:

```text
run_id
git_sha
timestamp
corpus_fingerprint
graph_build_id
mention_extractor_versions
resolver_versions
rdf_schema_version
query_set_hash
baseline_config
graph_config
embedding_model
reranker_model
llm_model_if_any
metrics
notes
```

Results without enough information to reproduce the run should not be used in application claims or research writing.

---

# Definition of success

The research succeeds if it produces a defensible answer to **where graph structure helps and why**, not merely if a graph-enhanced number is higher.

A strong outcome would establish some combination of:

- a high-precision provenance-preserving citation graph;
- measured limits of citation resolution in Ghanaian case law;
- clear differences between local, backward-authority, forward-treatment and multi-hop retrieval;
- an adaptive routing policy;
- a reliable method for evidence-backed semantic treatment relations;
- a reproducible comparison between graph representations such as RDF and a property/in-memory graph;
- traceable agentic graph exploration.

A negative or mixed result is acceptable if it is measured honestly and yields a concrete next research question.

The central principle remains:

> **Broaden reasoning without weakening evidence.**
