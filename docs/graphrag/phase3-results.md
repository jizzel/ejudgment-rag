# Phase 3 pilot: results, and a Phase 5 routing probe

> Research stream, `docs/graphrag/AGENTS.md`. Run `da7ac400` (2026-10-29, runner `pilot-runner-v4`, router `router-v2`), question set `3563115636bc`, graph `phase2-v1` (`78a13acec64db72b`), default models, 5 seeds. Report: `experiments/graphrag/runs/pilot_3563115636bc.md`; the same id in `evaluation_runs`. The tree was uncommitted (`git_dirty`).
>
> **What changed since the first write-up.** Run `eba62711` added one system, `G1-routed` (see "Routed entry point" below), and renames the others for what they are. The five earlier systems reproduce run `76cff131` exactly: all 115 per-question records match (rankings, hops and metrics).
>
> | Earlier name | Name now | What it is |
> |---|---|---|
> | `G1-oracle` | `G1-top5-label` | Seeds: B0's top 5 cases. Direction: the question's class label. One hop. |
> | `G1-both` | `G1-top5-both` | Seeds: B0's top 5. Both directions. One hop. |
> | `G2-oracle` | `G2-top5-label` | As `G1-top5-label`, two hops. |
>
> Only the direction was ever an oracle, never the seed; `report.LEGACY_NAMES` reads older run files under the new names.
>
> **Superseded runs:**
> - **`c092cd53`** judged an outgoing hop's citing passage as the cited case's text, so outgoing gold passages could never match. Fixing it changed only supporting-passage recall.
> - **`4a0dede3`** let graph-expanded cases ignore the question's filters, and did not record the ranking settings. Fixing it changed no metric.
>
> - **`eba62711`** left the router's own lookup out of `G1-routed`'s latency, and gave a citation-only anchor ("Has [2019] GHASC 41 been followed?") a zero-width span, so its direction went unread. Both are fixed. The pilot names every anchor by its parties, so no ranking or metric changed (all 138 records identical); only `G1-routed`'s latency now includes routing.
>
> - **`1f7d7f73`** ran router `router-v1`, which read an active perfect ("…that Mensah v Mensah has cited", "had relied on") as passive and routed it incoming. `router-v2` reads passive only with a form of "be". No pilot question uses that wording, so all 138 records are identical.
>
> All stay in `evaluation_runs`. The runner now also checks that the graph files match their manifest, that the corpus is the one the graph was built from, and that its embeddings are fingerprinted.
>
> **Hypothesis-generating.** There are 22 scored questions and the paired counts are small. The lowest McNemar p is 0.25, so nothing here is significant (rule 7). The local controls come from the unreviewed gold set. The relational gold was decided by one reviewer (Lexi) from graph-independent text search.

## Summary

- **Entering the graph at the named case is what makes it useful for "later treatment" questions.** On incoming questions, one hop from the case the question names (`G1-routed`) gives:

  | | B0R (rescoring only) | G1-top5-label (B0's top 5) | G1-routed |
  |---|---|---|---|
  | Recall@20 | 0.090 | 0.138 | 0.463 |
  | MRR@10 | 0.562 | 0.750 | 0.792 |
  | Hit@20 | 6 of 8 | 6 of 8 | 8 of 8 |
  | Supporting-passage recall | 0.064 | 0.120 | 0.431 |

  The traversal, the caps and the reranker are the same; only the entry point differs.
- **Where routing finds the right case but the graph has no edges, nothing improves.** Lineage and outgoing questions stay where they were. Their anchors have no gold edges in `phase2-v1`, so for them edge coverage is the binding constraint.
- **Local controls are unchanged** in every system, so expansion does no harm there.
- **Two hops add nothing,** because the edges they would follow are missing. Only 2 of the 30 lineage gold edges are in the graph, and no complete gold chain exists. This measures that *multi-hop traversal cannot make up for missing first- and second-hop edges*, not that multi-hop retrieval has no value.
- **Two separable bottlenecks:**
  1. **Entry point:** B0 puts the named anchor in its top 5 for only 6 of 14 scored relational questions (2 of 8 incoming). The router finds it for 13 of 14.
  2. **Edge coverage:** 202 of 385 gold citation edges (52%) are in `phase2-v1`: 58% for incoming, 7% for lineage, 14% for outgoing.

## Results by class

Case Recall@20 / Hit@20 / MRR@10, 22 scored questions:

| Class (n) | B0 | B0R | G1-top5-label | G1-top5-both | G2-top5-label | G1-routed |
|---|---|---|---|---|---|---|
| local (8) | 0.792 / 8 / 0.615 | same | same | same | same | same |
| incoming (8) | 0.090 / 6 / 0.575 | 0.090 / 6 / 0.562 | 0.138 / 6 / 0.750 | 0.148 / 6 / 0.656 | 0.138 / 6 / 0.750 | **0.463 / 8 / 0.792** |
| outgoing (3) | 0 / 0 / 0 | 0 / 0 / 0 | 0.111 / 1 / 0 | 0.111 / 1 / 0 | 0.111 / 1 / 0 | 0.111 / 1 / 0 |
| lineage (3) | 0.127 / 2 / 0.250 | 0.127 / 2 / 0.417 | 0.238 / 2 / 0.417 | 0.214 / 2 / 0.417 | 0.238 / 2 / 0.417 | 0.127 / 2 / 0.417 |
| all (22) | 0.338 / 16 / 0.467 | 0.338 / 16 / 0.485 | 0.386 / 17 / 0.553 | 0.386 / 17 / 0.519 | 0.386 / 17 / 0.553 | 0.489 / 19 / 0.568 |

- **Supporting-passage Recall@20 (all questions):** 0.152 (B0, B0R), 0.198 (G1-top5-label), 0.307 (G1-routed). For incoming questions: 0.064, 0.120 and 0.431.
- **Paired Hit@20 (all questions):**

  | Pair | Both | Only the first | Only the second | Neither | McNemar p |
  |---|---:|---:|---:|---:|---:|
  | B0R vs G1-top5-label | 16 | 0 | 1 | 5 | 1.0 |
  | B0R vs G1-routed | 16 | 0 | 3 | 3 | 0.25 |
  | G1-top5-label vs G1-routed | 17 | 0 | 2 | 3 | 0.5 |

  G1-routed lost no question that another system hit.
- **Rescoring alone (B0R) changes no recall,** so the gains come from the cases the graph adds.
- **Cost:** p50 latency 1.13 s (B0), 1.30 s (B0R), 1.35 s (G1-top5-label), 1.41 s (G1-top5-both), 1.32 s (G1-routed, routing included).
  - Routing itself (extraction plus the indexed lookups) takes 4.6 ms at the median and 12.8 ms at most.
  - Expansion is cheap; most of the extra time is the rescoring B0R also pays.
  - Latencies vary between runs on this machine.
- **G1-top5-both** visits about twice as many cases as G1-top5-label (16.6 against 7.5 on average). Its wrong-direction neighbours cost ranking on two questions and helped on one.
- **Stress test `p3-lin-02`** (reported apart; gold stops at the first hop, 67 cases): Recall@20 is 0.030 (B0), 0.179 (G1-top5-label) and 0.209 (G1-routed).

## Routed entry point (Phase 5 probe)

`experiments/graphrag/pilot/router.py`, `G1-routed`. Deterministic, no model and no new SQL:
1. **Extract** the case the question names: the party span around "v"/"vs"/"vrs" with its "(year)", or a neutral citation.
2. **Resolve** it with the search's own lookups (`repository.case_name_matches`, `citation_matches`), keeping that year. If name and year don't single out one decision, every case tied at the best match is seeded, at most 5.
3. **Route the direction** from the wording: the voice around the name ("cite X" / "X has been followed" → incoming; "did X cite" / "cited in X" → outgoing), then temporal cues (later / earlier). When the cues are absent or disagree, it expands both ways.
4. **Expand one hop** from the resolved case only, with the same caps (20 neighbours, hub 50, 50 nodes) and the same rescoring. Nothing resolved means no expansion, so the result equals B0R. There is no fallback to B0's seeds.

**Routing accuracy on the pilot:**
- Named case extracted for all 14 scored relational questions, and for none of the 8 local controls.
- The anchor was among the resolved seeds for 13 of 14.
- The direction was right for 14 of 14.

These figures are optimistic: the rules were written after the locked questions had been seen. They are deliberately generic (a name span, a year, verbs and temporal words) and are tested on held-out phrasings (`tests/research/graphrag/test_router.py`). A held-out fixture title ("Party0 Vrs Other0") found a real bug, a separator that matched only lower-case "v", fixed before the run. Still, a fresh question set is needed to measure the router, not this one.

### Per question

| Question | B0R | G1-top5-label | G1-routed | Why |
|---|---|---|---|---|
| `p3-in-05` William v Tanzania | 0.119 | 0.119 | **0.405** | anchor unseeded by B0 (rank 11); 20 of its 27 gold edges visited (cap) |
| `p3-in-06` Kambole v Tanzania | 0.214 | 0.238 | **0.381** | anchor at rank 9 in B0 |
| `p3-in-07` Abubakari v Tanzania | 0.107 | 0.179 | 0.179 | B0 already seeded it (rank 4) |
| `p3-in-08` Boi v Adjei | 0.020 | 0.260 | 0.260 | B0 already seeded it (rank 2) |
| `p3-in-09` Ashun v Accra Brewery | 0.083 | 0.125 | **0.667** | anchor not in B0's top 20 |
| `p3-in-10` Jaas v Apau | 0 | 0 | **0.600** (hit) | anchor at rank 15 |
| `p3-in-11` Kunutsor v Tetteh | 0 | 0 | **1.0** (hit) | anchor not in B0's top 20; its single citing case reached |
| `p3-in-12` Isiaga v Tanzania | 0.180 | 0.180 | 0.213 | 62 gold edges in the graph, 20 visited: the cap binds |
| `p3-lin-01` Teachers' Union v Gabon | 0.167 | **0.500** | 0.167 | the anchor has no incoming edge; G1-top5-label's gain came from B0 seeding a first-hop case |
| `p3-lin-03` Gabriel v Tanzania | 0.214 | 0.214 | 0.214 | the anchor has no incoming edge |
| `p3-lin-06` Kangberee v Mohammed | 0 | 0 | 0 | the anchor has no outgoing edge |
| `p3-out-01` Arthur v Arthur (2023) | 0 | 0 | 0 | ambiguous: ≥ 6 "Arthur v Arthur" decisions of 2023 tie, and the 5-seed cap cut the anchor |
| `p3-out-07` Purohit v Gambia | 0 | 0 | 0 | the anchor has no outgoing edge to its gold |
| `p3-out-08` Republic v Jajah | 0 | 0.333 | 0.333 | the one gold edge in the graph, reached either way |

### Interpretation

- **Incoming:** the pilot's limited graph gains were mainly constrained by *query-to-graph entry-point selection*, not by traversal. With the named case seeded, the same one hop reached 4–8 times B0's recall on the four questions B0 had not seeded well (in-05, in-09, in-10, in-11).
- **What still limits incoming questions:**
  - the 20-neighbour cap (in-05, in-09, in-12), kept fixed here so the probe changed one thing only;
  - the 42% of incoming gold edges absent from the graph.
- **Lineage and outgoing:** routing finds the anchor, but `phase2-v1` has no edge from it to the gold. Here edge coverage dominates.
- **Name ambiguity:** `p3-out-01` shows the one routing failure. That is the same "same parties, several decisions" ambiguity that costs the graph 84 edges (see below).

## Hypotheses

- **H1 (local questions don't gain): supported within the pilot.** All 8 local controls are identical in every system.
- **H2 (relational questions gain): preliminary support, conditional on reachability.** The graph helps when the correct seed and the required edges both exist.
  - Seeds from B0's top 5 gave small gains (Recall@20 0.338 → 0.386).
  - Seeding the named case gave large ones on incoming questions, where the edges exist (0.090 → 0.463).
  - It gave none where they don't (lineage, outgoing).
- **H3 (incoming gains most): consistent with the observations but not meaningfully tested.**
  - With B0's seeds, incoming has the larger MRR gain but lineage the larger mean recall gain. With routed seeds, incoming gains most.
  - The outgoing and lineage classes have 3 questions each, and their gold edges are largely absent from the graph. The comparison is between a class the graph covers and classes it barely covers.

## Error analysis

### 1. Entry point: B0 does not find the case the question names

| Question | Anchor rank in B0 | Graph edges to gold (one hop) |
|---|---:|---:|
| `p3-in-05` William v Tanzania | 11 | 27 of 42 |
| `p3-in-06` Kambole v Tanzania | 9 | 12 of 42 |
| `p3-in-07` Abubakari v Tanzania | **4** | 6 of 28 |
| `p3-in-08` Boi v Adjei | **2** | 34 of 50 |
| `p3-in-09` Ashun v Accra Brewery | not in top 20 | 18 of 24 |
| `p3-in-10` Jaas v Apau | 15 | 3 of 5 |
| `p3-in-11` Kunutsor v Tetteh | not in top 20 | 1 of 1 |
| `p3-in-12` Isiaga v Tanzania | 17 | 62 of 89 |

- **Why B0 misses the anchor:** its case-name check splits the *whole question* on "v". For in-05 the two "sides" are "WHICH LATER DECISIONS CITE WILLIAM" and "UNITED REPUBLIC … DISCUSS LEGAL REASONING". Nearly any citation matches one word of each side, so the named case gets no exact-match priority.
- **Not changed in B0:** that check belongs to the default search. A router in front of it (as above) addressed this without altering B0.

### 2. Edge coverage: the gold edges are not in the graph

The 385 gold edges are in `runs/pilot_gold_edge_coverage.csv` (counts only). Each missing edge was classified by the resolver outcome of the citing judgment's mentions of the target. Mentions were matched by the target's party words, so the split between buckets is approximate.

| Bucket | Incoming (281) | Lineage (30) | Outgoing (7) | Stress (67) |
|---|---:|---:|---:|---:|
| in the graph | 163 | 2 | 1 | 36 |
| ambiguous (several candidate cases) | 48 | 12 | – | 24 |
| resolved to the target, by a tier `phase2-v1` does not admit | 42 | 12 | – | 1 |
| stage / identifier / date mismatch | 7 | 1 | – | 5 |
| no candidate | 5 | 2 | 5 | – |
| other (no mention found, caption only, fuzzy) | 16 | 1 | 1 | 1 |

- **Lineage fails on the tier that failed its audit.** Later African Court judgments cite earlier ones by application number. Those are `name_with_identifier` resolutions, kept out of `phase2-v1` after their audit (36 of 40): a number identifies the litigation, not always the decision. That accounts for 12 of the 28 missing lineage edges.
- **Ambiguity is the largest single loss** (84 edges): several decisions share a party pair (many "X v Tanzania"), the same failure as `p3-out-01`'s routing.
- **Outgoing questions mostly lack candidates.** The authority is cited by a law-report citation that no corpus judgment carries.

### 3. Outgoing: a coverage finding, triangulated

Only 3 of the 9 outgoing questions written have any corpus gold; the other 6 were retired because the authorities their anchors rely on are not in the export. This is reported as a finding, not balanced away. It matches Phase 1 from the other side:
- **Phase 1 (`coverage-report.md`, reference level):** Ghanaian courts cite law reports (GLR 21,593 and SCGLR 19,895 references). A report citation alone is never resolvable, since the corpus has no report-citation field.
- **Phase 3 (question level):** "what did this case rely on" questions frequently have no corpus gold. Of 32 accepted outgoing authorities, 27 were absent, and both rounds of lookup for the lineage questions resolved nothing.

### 4. The caps

- **20-neighbour cap:** it binds once the anchor is seeded (in-05, in-09, in-12). It was kept fixed so the routing probe changed one thing only.
- **Hub limit:** applies from depth 1 only; it did not limit any scored result.
- **Direction:** expanding both ways (G1-top5-both) mostly adds noise when the question names one direction. The router's direction was right on all 14 questions.

## Next

- **Phase 4: two resolver experiments, each behind a fresh edge audit.** Neither enters the graph for improving benchmark recall; that would tune the graph to these questions.
  - **R1, identifier + stage + date:** case or application number plus parties plus decision stage plus decision date → the specific judgment. It targets the 12 lineage edges that resolve correctly through the excluded identifier tier.
  - **R2, ambiguous-name disambiguation:** "X v Tanzania" candidates narrowed by adjacent date, application number, stage and report metadata. It targets the 84 ambiguous edges and `p3-out-01`'s routing failure.
- **Phase 5:**
  - The router needs a fresh, blind question set to be measured; this set was seen when the router was written.
  - The 20-neighbour cap is the next single variable for incoming questions.
- **Re-run this locked set unchanged** after any of these, so the effect of each change can be separated.

## Limits

- **Sample:** 22 scored questions plus one stress test; 12 retired for lack of corpus gold (mostly outgoing). Class sizes are 8 local, 8 incoming, 3 outgoing and 3 lineage, so the outgoing and lineage rows are anecdotes.
- **Gold:** one reviewer and a text-search finder whose recall is bounded (spelling, OCR, one-party references). Five gold rows keep their case but lost a quote cut off at "v."
- **Local controls** are unreviewed (`provisional`).
- **The router was written after seeing the questions;** its pilot accuracy is optimistic.
- **The edge-coverage buckets** come from a party-word match on mentions and are approximate.
- **One run per configuration;** latency is from one development machine.
