# Phase 2: the deterministic citation graph

> Research stream, `docs/graphrag/AGENTS.md`. Graph **`phase2-v1`**, built 2026-10-28 from profile `3325b81913b3` (resolver v3), whose independent audit justified the policy (`docs/graphrag/coverage-report.md`).
> - Statistics: `experiments/graphrag/runs/graph_phase2-v1.json` and `.md`.
> - Fingerprint: `78a13acec64db72b7ed5993f59ff544350f5467bd767d8f6a67a1fc2e09ba1d5`.

## What an edge means

`A --CITES--> B`: a passage of a judgment in case A contains a case reference that the resolver linked to a judgment in case B, with the recorded method and status.

It does **not** mean A followed, applied or approved B, relied on it, or that B is still good law. `CITED_BY` is the same edge read backwards. Nodes are cases (re-publications of one judgment grouped by `source_text_hash`), and each node lists its judgments and AKN URIs.

## Admission policy `phase2-v1`

Frozen by the owner on 2026-10-28 (`experiments/graphrag/graph/policy.py`).

| Method | v3 audit (complete edge) | Admitted |
|---|---:|---|
| `neutral_exact` (tier A) | 39/40 | yes |
| `name_with_report` (B) | 21/21 | yes |
| `name_with_date` (B) | 15/15 | yes |
| `name_with_identifier` (B) | 22/24; targeted re-audit 36/40 | no (below) |
| `name_only` (C) | 17/20 | no, candidate evidence only |

- **Statuses:** only `resolved_exact` and `resolved_unique_fuzzy` become edges. Temporal conflicts within admitted methods are review items.
- **Locked to its build:** the builder refuses any profile other than the audited build, `3325b81913b3`.
- **Sample size:** the audited samples are small. 39/40 is consistent with anything from about 87% to 99.6%.

## The graph

| | |
|---|---:|
| Cases (nodes) | 7,765 (8,242 judgments) |
| Edges | 3,886, from 4,576 occurrences (30 from OCR'd text) |
| Occurrences by method | report 2,517 · date 1,779 · neutral 280 |
| Cases that cite a corpus case | 1,870 |
| Cases cited by a corpus case | 468 |
| Isolated cases | 5,562 (72%) |
| Weakly connected components with an edge | 63; largest 1,728 cases, then 305 |
| Ordered pairs reachable along `CITES` | 6,020; shortest paths of length 1–4 |
| Largest in-degree | 115 |
| Edges pointing to a later decision | 0 |

**By court.** The Supreme Court is both cited and citing (314 of 1,115 cases are cited by a corpus case). Lower Ghanaian courts cite but are almost never cited. The African Court is the densest regional network (213 citing, 113 cited of 468).

Almost all citing cases are from the 2020s. Cited cases come mostly from the 2010s.

**Density for Phase 3.** There is enough for:
- **Incoming-citation questions** about well-cited Supreme Court and African Court decisions: 19 cases have more than 50 citing cases, and 49 have more than 20.
- **Bounded two-hop questions** within the two large components: 1,724 pairs at distance 2.

Multi-hop lines of authority across Ghanaian lower courts are thin.

## Provenance and reproducibility

- **Occurrences:** every occurrence keeps:
  - the citing judgment, chunk and offsets of the reference and its evidence sentence;
  - the extraction method and OCR flag;
  - the resolution method, tier and status;
  - the matched target judgments and the decision signals (identifiers, stage, date).
- **End-to-end audit** (`python -m experiments.graphrag.graph.verify`): all 4,576 occurrences pass, with 0 failures. Every chunk exists in the citing judgment and that judgment is eligible. The text at the recorded offsets is exactly the stored reference and evidence. Source offsets match. Every target is an eligible judgment of the target case, and every method is admitted. An integration test shows that a changed reference text or target case is caught.
- **Fingerprint:** SHA-256 over the policy, every node and every edge with its occurrence keys. It is independent of input order.
- **Run manifest:** `runs/graph_phase2-v1.json` records the source profile's run, git SHA (dirty tree, since nothing is committed yet) and every extractor and resolver version.

## RDF export

`artifacts/graph_phase2-v1.ttl` (6.8 MB; gitignored by location, though it holds no corpus text).

- **Judgments:** each is its AKN expression URI as GhaLII publishes it.
- **Generic citation relation:** `cito:cites` (CiTO), chosen because it makes no claim about treatment. No more specific CiTO property is used.
- **One node per occurrence:** an explicit `cito:Citation` node, CiTO's own n-ary citation pattern, so **neither reification nor RDF-star** is used. It carries:
  - `cito:hasCitingEntity` and `cito:hasCitedEntity`;
  - `prov:wasDerivedFrom` (the chunk) and `prov:wasGeneratedBy` (the build activity);
  - this project's `ejg:` properties for offsets, SHA-256 of the reference and evidence text, method, tier, status, extraction method and OCR flag.
- **Direct triples:** `<citing> cito:cites <cited>` triples are added for simple queries, derived from the citation nodes.
- **Not claimed:** no equivalence with other vocabularies.
- **Rights:** no passages, quotes or titles.
- **Validated** with rdflib 7.1.4 (2026-10-28, a throwaway `python:3.13-slim` container; not a project dependency). It parses without errors:
  - 101,952 triples;
  - 4,576 `cito:Citation` nodes, one per occurrence, none missing its citing or cited entity, chunk, build activity, offsets, evidence hash or method;
  - all 8,242 judgments typed, and every citing and cited entity is one of them;
  - 4,086 direct `cito:cites` triples, exactly the judgment pairs the citation nodes imply (more than the 3,886 case edges, because a re-published case has several judgments).

  The unit tests check structure, IRI syntax and that no text leaks.

## Name + case number: not admitted (decided 2026-10-29)

Resolver **v4** (build `d739505c538f`) fixed the causes of the v3 audit failures. Each fix has a test that fails without it.
- **Hyphenated title separators** ("X -vrs- Y") are read.
- **Same-day re-publications:** a target with the citing case's own date and parties is a re-publication of the citing case, even with a title slip.
- **Unlinked adjacent names:** an OCR-split name just before a neutral citation must agree with its target.

Its targeted, independent audit of `name_with_identifier` (40 edges, marked by Lexi, none from earlier sheets) scored **36/40 complete edges (90%)**. That fails the gate, so **the method is not admitted and `phase2-v1` stays the deterministic graph**.

**The four failures:**
- **13:** the reference (Republic v High Court, Ex parte Agbesi Awusu (No. 2) [2003–2004] 2 SCGLR 907) took the suit number J7/20/2021, which belongs to a separate authority later in the same sentence.
- **18:** two ECOWAS application numbers (APP/08/09 and APP/12/07) sit beside one name. The pairing in the text is unsafe, and the resolver used it.
- **20, 34:** Writ J1/5/2021 produced several rulings before the 4 March 2021 judgment. These references cite the rulings of 16 and 11 February 2021, but resolved to the final judgment. Their dates were in the text, in forms the reader misses ("Dated 2021 -02-16", "( 11th February, 2021)").

**The lesson:** a case, suit or application number identifies a *proceeding*, not necessarily a *decision*. This matters for:
- Ghana Supreme Court suits with interlocutory rulings;
- ECOWAS applications with rulings and judgments;
- African Court applications with provisional-measures, merits and reparations decisions;
- review and appeal stages.

A later resolver pass should split the method:

| Evidence | Treatment |
|---|---|
| Name + a *judgment* identifier (e.g. `ECW/CCJ/JUD/…`) | potentially deterministic |
| Name + proceeding number + a compatible explicit decision date or stage | potentially deterministic |
| Name + proceeding number alone | candidate resolution, not a deterministic edge |

That pass also needs to keep identifiers to the reference they belong to (row 13), refuse references with conflicting identifiers (row 18), and read the date forms above. It is deferred: it should not hold up the Phase 3 retrieval pilot, for which `phase2-v1` is already sufficient.

The 3 edges v4 would add to the admitted methods and the 11 it would remove are not in `phase2-v1` either; they await a future policy with its own audit.

## Limitations

- **The edge spans:** span precision was 108/120 in the v3 audit. They need fixing before Phase 3 uses them as fine-grained evidence passages; the evidence sentence (114/120) is what an edge points to.
- **Edges are only as complete as resolution.** Most law-report citations can't be mapped without bibliographic metadata, and 72% of cases are isolated. "No edge" means only that this build resolved none (rule 5).
- **Dates are the export's.** Some African Commission decisions carry what looks like a publication date, so the temporal check can only be as good as that metadata.
