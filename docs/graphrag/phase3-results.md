# Phase 3 pilot: results

> Research stream, `docs/graphrag/AGENTS.md`. Run `4a0dede3` (2026-10-29, runner `pilot-runner-v2`), question set `3563115636bc`, graph `phase2-v1` (`78a13acec64db72b`), default models, 5 seeds. Report: `experiments/graphrag/runs/pilot_3563115636bc.md`; the same id in `evaluation_runs`. The tree was uncommitted (`git_dirty`).
>
> **It supersedes run `c092cd53`** (kept in `evaluation_runs`), which judged an outgoing hop's citing passage as if it were the cited case's text. Outgoing gold passages, recorded in the anchor, could therefore never match. The rerun changed only supporting-passage recall (outgoing 0 → 0.111, all G systems; small rises where G1-both made outgoing hops). Case recall, Hit@20, MRR and the path metrics are identical. Since that rerun the runner also checks that the graph files match their manifest, that the corpus is the one the graph was built from, and that its embeddings are fingerprinted.
>
> **Hypothesis-generating.** There are 22 scored questions and the paired counts are tiny. Every McNemar p is 1.0, so nothing here is significant (rule 7). The local controls come from the unreviewed gold set. The relational gold was decided by one reviewer (Lexi) from graph-independent text search.

## Summary

- **The graph helps where it can reach the gold, which is seldom.** Over the 14 relational questions, one hop from B0's top 5 (G1-oracle) raised case Recall@20 for incoming questions from 0.090 to 0.138 and MRR@10 from 0.575 to 0.750, and for lineage questions from 0.127 to 0.238. Hit@20 changed on one question in 22 (`p3-out-08`).
- **Local controls are unchanged** (8 of 8 identical in every system), so the expansion does no harm there. H1 holds.
- **Two hops add nothing.** G2-oracle equals G1-oracle on every scored question; no gold chain is ever traversed completely. The second hop has no edges to follow: only 2 of the 30 lineage gold edges are in the graph.
- **Two bottlenecks sit in front of the graph:**
  1. **Seeding:** B0 puts the named anchor in its top 5 for 6 of 14 scored relational questions, and for only 2 of 8 incoming ones, although every query names it.
  2. **Edge coverage:** 202 of 385 gold citation edges (52%) are in `phase2-v1`: 58% for incoming, 7% for lineage, 14% for outgoing.

  Where both are met (`p3-in-07`, `p3-in-08`, `p3-lin-01`), the gains are large: in-08 Recall@20 0.02 → 0.26, MRR 0.10 → 1.0.

## Results by class

Case Recall@20 / Hit@20 / MRR@10 (22 scored questions; B0R is B0's passages rescored without the graph):

| Class (n) | B0 | B0R | G1-oracle | G1-both | G2-oracle |
|---|---|---|---|---|---|
| local (8) | 0.792 / 8 / 0.615 | same | same | same | same |
| incoming (8) | 0.090 / 6 / 0.575 | 0.090 / 6 / 0.562 | 0.138 / 6 / 0.750 | 0.148 / 6 / 0.656 | 0.138 / 6 / 0.750 |
| outgoing (3) | 0 / 0 / 0 | 0 / 0 / 0 | 0.111 / 1 / 0 | 0.111 / 1 / 0 | 0.111 / 1 / 0 |
| lineage (3) | 0.127 / 2 / 0.250 | 0.127 / 2 / 0.417 | 0.238 / 2 / 0.417 | 0.214 / 2 / 0.417 | 0.238 / 2 / 0.417 |

- **Supporting-passage Recall@20** follows the same pattern: incoming 0.064 → 0.120, lineage 0.223 → 0.290, outgoing 0 → 0.111, local 0.286 everywhere.
- **Paired Hit@20:** G1-oracle against B0, and against B0R, gives 16 both / 0 only baseline / 1 only graph / 5 neither (p = 1.0). The single discordant question is `p3-out-08`, where the graph reaches 1 of its 3 gold cases, at rank 11–20.
- **Rescoring alone (B0R) changes no recall.** The G gains therefore come from the cases the graph adds, not from the cross-encoder pass.
- **Cost:** p50 latency 1.11 s (B0), 1.31 s (B0R), 1.35 s (G1-oracle), 1.37 s (G1-both). Expansion itself is cheap; the extra time is the rescoring that B0R also pays.
  - G1-both visits about twice as many cases as G1-oracle (16.6 against 7.5 on average).
  - Its wrong-direction neighbours cost ranking on two questions: `p3-in-06` MRR 1.0 → 0.25, and `p3-lin-03` recall 0.214 → 0.143. It gained on one: `p3-in-05` recall 0.119 → 0.190. So the direction matters.
- **Stress test `p3-lin-02`** (reported apart; gold stops at the first hop, 67 cases):
  - Recall@20 rises from 0.030 (B0) to 0.179 (G1-oracle and G2-oracle).
  - G2 visits 55 cases, 21 of them at depth 2, at 786 ms p50.
  - Depth 2 adds no gold here by construction, since the gold has no second hop.

## H2 and H3

- **H2 (relational questions gain):** weakly supported, and only where the graph has the edges and the seed is right. The mean gains are real but small, and Hit@20 hardly moves: B0 already finds at least one gold case for most incoming questions. Their gold sets are large (5–89 cases), so the graph's contribution shows in recall and MRR.
- **H3 (incoming gain most):**
  - Incoming has the largest MRR gain (+0.175) and the best graph coverage of its gold edges.
  - Lineage has the largest recall gain (+0.111), but almost all of it is `p3-lin-01` (0.167 → 0.500), its one seeded question with first-hop edges.
  - Outgoing questions, with only 3 left after the coverage retirements, cannot test it.
  - So H3 is consistent with the data, but rests on two or three questions.

## Error analysis

### 1. Seeding: B0 does not find the case the question names

| Question | Anchor rank in B0 | Graph edges to gold (one hop) | G1-oracle recall |
|---|---:|---:|---|
| `p3-in-05` William v Tanzania | 11 | 27 of 42 | 0.119 (= B0) |
| `p3-in-06` Kambole v Tanzania | 9 | 12 of 42 | 0.238 |
| `p3-in-07` Abubakari v Tanzania | **4** | 6 of 28 | 0.179 (B0 0.107) |
| `p3-in-08` Boi v Adjei | **2** | 34 of 50 | 0.260 (B0 0.020) |
| `p3-in-09` Ashun v Accra Brewery | not in top 20 | 18 of 24 | 0.125 |
| `p3-in-10` Jaas v Apau | 15 | 3 of 5 | 0 |
| `p3-in-11` Kunutsor v Tetteh | not in top 20 | 1 of 1 | 0 |
| `p3-in-12` Isiaga v Tanzania | 17 | 62 of 89 | 0.180 (= B0) |

- **The reach was there.** For the six unseeded incoming questions, the graph holds 123 edges to their 203 gold cases. One hop from the anchor could reach at most 61% of their gold before the caps, against the 0–0.24 they got. That ceiling isn't a system result: the 20-neighbour cap would bind for in-05, in-09 and in-12, and the reached cases still need ranking.
- **The cause is in B0's query analysis.** A relational question is recognised as a case name ("…cite William v United Republic of Tanzania (2018) and discuss it…"). But the party check splits the *whole question* on "v", so the two "sides" are "WHICH LATER DECISIONS CITE WILLIAM" and "UNITED REPUBLIC … DISCUSS LEGAL REASONING". Nearly any citation matches one word of each side, so the named case gets no exact-match priority.
- **Phase 5, not the pilot.** As designed, this is reported, not patched into the pilot. A router that extracts the case name from a relational question, and seeds the anchor itself, is the first Phase 5 change worth testing.

### 2. Edge coverage: the gold edges are not in the graph

The 385 gold edges are recorded with their cause in `runs/pilot_gold_edge_coverage.csv` (counts only). Each missing edge was classified by the resolver outcome of the citing judgment's mentions of the target. Mentions were matched by the target's party words, so the split between buckets is approximate.

| Bucket | Incoming (281) | Lineage (30) | Outgoing (7) | Stress (67) |
|---|---:|---:|---:|---:|
| in the graph | 163 | 2 | 1 | 36 |
| ambiguous (several candidate cases) | 48 | 12 | – | 24 |
| resolved to the target, by a tier `phase2-v1` does not admit | 42 | 12 | – | 1 |
| stage / identifier / date mismatch | 7 | 1 | – | 5 |
| no candidate | 5 | 2 | 5 | – |
| other (no mention found, caption only, fuzzy) | 16 | 1 | 1 | 1 |

- **Lineage fails on the tier that failed its audit.** The lineage anchors are African Court judgments, and later African Court judgments cite them by application number. Those are `name_with_identifier` resolutions, kept out of `phase2-v1` after their audit (36 of 40). That accounts for 12 of the 28 missing lineage edges; `p3-lin-03`'s anchor has no incoming edge at all. An identifier tier that also checks the decision's stage and date (Phase 2's open item) would directly serve lineage questions.
- **Ambiguity is the largest single loss** (84 edges): a citation that matches several candidate cases, typically many "X v Tanzania" judgments. These need disambiguation by date or identifier, not a looser rule.
- **Outgoing questions mostly lack candidates.** The authority is cited by a law-report citation the corpus judgment does not carry. This is the same law-report gap that retired most outgoing questions (see `phase3-pilot.md`).

### 3. The caps

- **Hub limit:** seeds are always expanded; the limit applies only from depth 1. That is where the lineage questions had no gold edges to follow anyway, so it cannot explain G2's lack of gain.
- **20-neighbour cap:** `p3-in-08`'s anchor has 36 incoming edges to gold, but at most 20 are visited.
- **Direction:** G1-both shows that expanding both directions, when the question names one, mostly adds noise.

## What this means for Phase 4 and Phase 5

- **Phase 5 (routing) has the bigger lever:**
  - Extract the named case from a relational question and seed it, ahead of B0's top 5.
  - Route the direction from the wording. G1-oracle beats G1-both on the questions where they differ, though the oracle is a label here, not a router.
- **Phase 4 (graph):**
  - An audited identifier tier with stage/date checks for regional-court citations (lineage).
  - Disambiguation for "X v Tanzania"-type ambiguity (incoming).
  - These are recall changes. Each must pass the edge audit gate before entering the graph, as `phase2-v1`'s tiers did.
- **Re-run this pilot unchanged** (same locked questions) after either change. Only then is "the graph helps" separable from "the seeds were right".

## Limits

- 22 scored questions plus one stress test; 12 retired for lack of corpus gold (mostly outgoing). The class sizes (8/8/3/3) make the outgoing and lineage rows anecdotes.
- The gold comes from one reviewer and a text-search finder whose recall is bounded (spelling, OCR, one-party references). Five gold rows keep their case but lost a quote cut off at "v."
- Local controls are unreviewed (`provisional`).
- The edge-coverage buckets come from a party-word match on mentions and are approximate.
- One run; latency is from one development machine with warm caches.
