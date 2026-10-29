# Phase 1: citation and case-reference coverage

> Research stream, `docs/graphrag/AGENTS.md`. Two builds, both from read-only profiles of the same corpus (2026-10-22):
>
> - **`ed63d4715792`** (resolver v1, run `11c9b58a`): the first coverage profile. Its 80-edge audit and 60-item error review are complete.
> - **`405c7303a68d`** (resolver v2, "Phase 1.5"): fixes for the failures that audit found. Its independent 120-edge audit is complete.
> - **`3325b81913b3`** (resolver v3): fixes for the v2 audit's target errors, and the gate moved from the reference span to the evidence sentence. Its independent 120-edge audit is complete.
>
> Every count comes from `experiments/graphrag/runs/coverage_<build>.json` and `.md`. No admission decision has been made under the Phase 2 gate (below) yet, so no citation graph has been built.

## Baseline (Phase 0)

`runs/baseline_2026-10-22.json`:
- **Run:** evaluation run `e819c5f2`, matched to the current configuration. That means the same gold file, ranking settings, embedding and reranker models (id and revision) and embedding template, and the same corpus and vector fingerprint: judgments, chunks, embeddings, HNSW indexes, schema.
- **Metrics:** hybrid + rerank Recall@20 0.8824, MRR@10 0.6327, passage Recall@20 0.29, p50 latency 200 ms; identical quality to run `2121c24d`.
- **Provisional:** the gold set is 60 questions, 0 of them reviewed by a lawyer.
- **Not yet pinned to a commit:** the manifest was written from an uncommitted tree (`git_dirty: true`, which now also counts untracked files). Rerun `experiments.graphrag.baseline` after committing to pin the SHA.

## What the corpus contains

Scope: 159,083 chunks of 8,242 eligible judgments, which form 7,765 cases once re-publications are grouped. Build `405c7303a68d` finds 109,011 references to other authorities.

| Reference | References | Resolvable how |
|---|---:|---|
| Case name, no citation | 54,477 | Title matching, decided by an identifier or judgment date where one is given |
| Case name + law-report citation | 39,017 | Title matching, narrowed by the report year |
| Law-report citation alone | 13,843 | **Never.** The corpus has no report-citation field (no fabricated mapping). |
| Neutral citation | 701 | Exact lookup |
| Unrecognised bracketed citation | 973 | Never |

**Ghanaian courts cite law reports, not neutral citations.**
- Report citations: GLR 21,593 and SCGLR 19,895, then GMJ, All ER, AC and DennisLaw (`DLSC`).
- Neutral citations appear in only 0.4% of chunks (GHASC 318, GHACA 20), and many of those are foreign (UKHL 61, UKSC 47, SCC 47).
- A neutral-citation graph alone is almost empty: 247 edges.

**Neutral citations that point nowhere.** 309 of the 378 absent citations are to foreign courts. The other 69 (48 distinct, e.g. `[2021] GHASC 27` ×10) match no imported judgment, quarantined ones included.

**Regional courts link far better.** The African Court, African Commission and ECOWAS Court resolve about 20% of their references, against 4.5–6.6% for Ghanaian courts: they cite their own decisions, which the corpus largely holds. Almost all citing text is from the 2010s and 2020s.

## First build and its audit (`ed63d4715792`)

| Method | Mention | Target | Span | Temporal | Complete edge |
|---|---:|---:|---:|---:|---:|
| Name only | 34/34 | 30/34 | 25/34 | 34/34 | **22/34** |
| Name + report year | 31/31 | 29/31 | 27/31 | 31/31 | **26/31** |
| Neutral exact | 15/15 | 13/15 | 13/15 | 15/15 | **13/15** |
| **All** | **80/80** | **72/80** | **65/80** | **80/80** | **61/80** |

Marked by Lexi.

**Finding references works; picking the right case is the problem.** Every sampled mention existed and every date order was plausible. The 8 wrong targets fall into four patterns:

1. **Right litigation, wrong decision (4).** Merits, reparations and provisional-measures decisions in the same African Court case: Guehi, Mtikila (twice), Zongo. Party names identify a *case family*, not one judgment.
2. **Missed name/citation conflicts (2), both in tier A.** "Fuseini v. Rep. (J4/32/2014) [2018] GHASC 28" resolved to Tafali v Yakubu, because the name was not linked to the citation.
3. **A caption or running header taken as a citation (1).**
4. **A first name matched as if it were the party (1).** "John Gandonu …" was linked to "Republic v John".

The 15 span errors were boundary slips: labels ("Communication", "Pg", "JUDGMENT", "Referred"), footnote numbers, and truncated multi-party names.

**Error review** (60 unresolved, ambiguous and conflicting references):

| Error family | Count |
|---|---:|
| Corpus gap: the cited authority is not in the corpus | 44 |
| Caption or self-reference leakage | 5 |
| Resolver policy: unused identifier, report-year window, procedural stage, title variant | 7 |
| Truncated name or ex parte extraction | 2 |
| OCR corruption | 2 |

## Phase 1.5: resolver v2 (`405c7303a68d`)

Each change answers a failure above. Each is covered by a test that fails without it.

- **Evidence tiers.** Every resolved reference records its method and tier:
  - **A:** an exact neutral citation;
  - **B:** a case name plus an application, communication or suit number (`name_with_identifier`), a law-report year (`name_with_report`), or an explicit judgment date (`name_with_date`);
  - **C:** a case name alone, kept as candidate evidence only.
- **Graph policies.** One set of records serves every graph policy, chosen by tier: `tier_A`, `tiers_A_B` (strict) and `tiers_A_B_C` (broad). There are never separate builds.
- **Which decision.** Party names identify the litigation. Three signals read next to the reference must then agree with the candidate:
  - identifiers (`Communication 224/98`, `ECW/CCJ/APP/11/18`, `J4/43/2013`);
  - stage labels, in brackets or after "Judgment/Ruling/Order on|for";
  - an explicit judgment date ("Judgment of 23 June 2022").

  A candidate that contradicts any of them is dropped (`identifier_mismatch`, `decision_date_mismatch`, `procedural_stage_mismatch`). Without a stage label, a reference means a main judgment: no stage, or one including the merits.
- **Every signal must agree.** A neutral citation contradicted by the adjacent name, identifier, date or stage is `ambiguous`, never an edge. Names now link to citations across suit numbers and identifier phrases, which is what missed the Fuseini conflict.
- **Self references.** The following are `self_reference`, not edges:
  - **Captions:** party-role labels, "Represented by", running headers such as "Page 7 of 56", "pg. 9 X v Y", "– JUDGMENT".
  - **Opening caption zone:** names in a judgment's first 1,500 characters without a citing cue.
  - **Own suit number:** a reference that carries the citing judgment's own suit number.

  The judgment's own case among other candidates is `ambiguous`.
- **Names.** When a name's side has more words than the title's side, the title must still hold the surname. That is the left side's word nearest the separator, the right side's first party's last word, and the word before an alias. Abbreviations are read as words ("Rep." is Republic).
- **Evidence spans.** Each record carries the reference span *and* the sentence holding it (`evidence`). An edge points to that sentence, and the audit checks it (`evidence_ok`).
- **OCR flag.** OCR-derived references carry an explicit `ocr` flag, shown in the report by tier (A 4, B 39, C 40 resolved).
- **Review fixes:**
  - the temporal check uses the citing case's earliest copy, so every re-publication gets the same answer;
  - the build id includes the run configuration, so a `--limit` run can't overwrite a full one;
  - the baseline must match the whole configuration and vector fingerprint.

**Resolution in v2:**

| Tier | Resolved | Ambiguous | Absent / unresolved | Self reference | Temporal conflict |
|---|---:|---:|---:|---:|---:|
| A: neutral exact | 280 | 43 | 378 absent | 0 | 0 |
| B: name + identifier / report / date | 5,676 | 752 | 38,091 | 439 | 4 |
| C: name only | 3,332 | 4,087 | 28,706 | 12,207 | 200 |

**Graph shape by policy** (statistics only, no graph build):

| | Tier A | Tiers A+B (strict) | Tiers A+B+C (broad) |
|---|---:|---:|---:|
| Distinct case → case edges | 247 | 5,098 | 6,989 |
| Cases cited at least once | 127 | 694 | 898 |
| Cases with no edge | 7,426 | 5,321 | 4,711 |
| Cases starting a path of length 2 | 1 | 870 | 1,398 |

The strict policy grew from 2,334 edges in v1 to 5,098, mainly because identifiers and judgment dates now corroborate names that had no report citation (1,354 and 1,839 resolved references). Whether those edges are right is exactly what the new audit must show.

**Regression check on the first audit.** This is not evidence of precision: these are the references the rules were tuned on.
- None of the 8 wrong targets is still an edge.
- 69 of the 72 correct targets still resolve to the same case.
- The 3 dropped are references whose own evidence contradicts the target: the Springfield/ENI running header carrying the citing judgment's own suit number, and two Yehans references whose suit number J4/34/2018, judgment date (24 Oct 2018) and report year (2018) point to a later decision than the corpus's 2011 judgment.
- The 7 recoverable misses from the review now resolve where the identifier is present: Media Rights Agenda, Constitutional Rights Project, Kodeih. The rest remain misses: Ackah v Pergah (report-year window), Muller v Home Finance and Onyanchi (title spelling variants), Joana v Madagascar (truncated name).

## v2 audit (`405c7303a68d`)

120 edges, none of them in the first sheets, marked by Lexi: 40 tier A, 60 tier B, 20 tier C.

| Method / tier | Target | Span | Evidence | Mention | Temporal | Complete edge | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| Neutral exact (A) | 38/40 | 38/40 | 40/40 | 40/40 | 40/40 | 38/40 | no |
| Name + report (B) | 23/23 | 19/23 | 23/23 | 23/23 | 23/23 | 19/23 | no |
| Name + date (B) | 15/15 | 13/15 | 15/15 | 15/15 | 15/15 | 13/15 | no |
| Name + identifier (B) | 20/22 | 16/22 | 22/22 | 21/22 | 22/22 | 14/22 | no |
| **Tier B** | **58/60** | **48/60** | **60/60** | **59/60** | **60/60** | **46/60** | no |
| Name only (C) | 16/20 | 15/20 | 19/20 | 20/20 | 20/20 | 15/20 | no |
| **All** | **112/120** | **101/120** | **119/120** | **119/120** | **120/120** | **99/120** | no |

**Target identity improved but is not yet at 97%.**
- Tier B is 58/60. Report-year and judgment-date matches had no wrong targets (23/23, 15/15).
- Tier A is 38/40. Both errors are African Commission neutral citations next to a list of *other* communications; that context wasn't linked to the citation, so the conflict check never saw it.
- Name + identifier had two errors:
  - a running header that names a re-publication of the citing case;
  - a decision dated 11 February 2021 resolved to the 4 March 2021 publication.
- All four name-only errors cite an authority with a report citation right beside the name that the extractor didn't attach ("Kotei v Kotei [1974] 2 GLR 172", "(2013) CCJELR 257", "(2012) 48 GMJ", "[1961] GLR (Pt II) 671"). Attached, the report year would have rejected each target.

**Spans are now the main failure (101/120), but the evidence sentence is almost always right (119/120).** Most span errors are boundaries of long party names:
- truncated leading words ("African Commission on", "Zimbabwe Lawyers for", "Chief", "Huri-");
- truncated right sides;
- footnote markers or trailing labels ("CA NO").

The target was right in 13 of these 19 span failures.

## Resolver v3 (`3325b81913b3`)

Each change answers a v2 audit error, and each is covered by a test that fails without it.

| Change | v2 errors it targets |
|---|---|
| Report citations attach to the name even with an OCR-spaced year ("[1 974]"), "page" or "at page" before the number ("(2013) CCJELR page 257", "(2012) 48 G. M.J at page 44") or a part label ("GLR (Pt,II) 671") | the four name-only errors: Kotei, Wade, Accra Brewery, Boateng |
| Case numbers *before* a reference count, back to the start of its sentence or the previous reference, also in text that lost its spaces ("9Communications64/92,68/92and78/92 – … v Malawi (1994) ACHPR 7") | the two tier A errors |
| Dates written "11th day of February, 2021" | Mahama v Electoral Commission |
| A "Page N of M" up to 80 characters after a name marks a running header, and a target that re-publishes the citing case itself is a self-reference (`republication_of_citing_case`) | Kohl v Consolidated Bank |
| No sentence break after an initial ("G. M.J") | the one evidence-sentence failure |
| Spans drop leading marks ("2°") and a trailing "CA NO", and allow 12-token party names | span slips (reported, not gated) |

**Regression check.** This is not evidence of precision: the rules were tuned on these rows.
- **v2 audit:** none of its 8 wrong targets is still an edge, and all 112 correct ones resolve to the same case.
- **First audit:** 68 of its 72 correct ones still do. A fourth one is now dropped: "Ackah vrs. Pergah Transport & Others [2010] SCGLR page 728" now carries its report citation. That citation names the 2010 Supreme Court decision, not the 2007 Court of Appeal judgment it was linked to, so the first audit's mark there looks mistaken.

| Tier | Resolved | Ambiguous | Absent / unresolved | Self reference | Temporal conflict |
|---|---:|---:|---:|---:|---:|
| A | 280 | 45 | 379 absent | 0 | 0 |
| B | 6,137 | 918 | 38,809 | 998 | 25 |
| C | 2,891 | 3,702 | 26,941 | 12,923 | 157 |

| | Tier A | Tiers A+B (strict) | Tiers A+B+C (broad) |
|---|---:|---:|---:|
| Distinct case → case edges | 247 | 5,470 | 7,071 |
| Cases cited at least once | 127 | 747 | 910 |
| Cases starting a path of length 2 | 1 | 963 | 1,426 |

**Temporal conflicts in tier B rose from 4 to 25**, all `name_with_identifier`. Reading case numbers before references surfaced them. Most are African Commission communications whose corpus date is far later than the decision: Amnesty International v Sudan (Communication 48/90) is dated 2018-11-15, apparently a publication date. The rest are Ghanaian decisions in the same suit dated a few days after the citing judgment. They are review items, not edges, and point to date metadata worth checking.

## v3 audit (`3325b81913b3`)

120 edges, none of them in the four earlier sheets, marked by Lexi (span marked more strictly than before). Rough 95% intervals (Wilson) show how much the small samples allow:

| Method / tier | Target | Evidence | Mention | Temporal | Span (reported) | Complete edge | ~95% interval | Gate |
|---|---:|---:|---:|---:|---:|---:|---|---|
| Neutral exact (A) | 39/40 | 39/40 | 40/40 | 40/40 | 40/40 | 39/40 | 87–99.6% | **yes** |
| Name + report (B) | 21/21 | 21/21 | 21/21 | 21/21 | 19/21 | 21/21 | 85–100% | **yes** |
| Name + date (B) | 15/15 | 15/15 | 15/15 | 15/15 | 12/15 | 15/15 | 80–100% | **yes** |
| Name + identifier (B) | 22/24 | 22/24 | 24/24 | 24/24 | 20/24 | 22/24 | 74–98% | no |
| **Tier B** | **58/60** | **58/60** | **60/60** | **60/60** | **51/60** | **58/60** | 89–99% | no (96.7%) |
| Name only (C) | 17/20 | 17/20 | 20/20 | 20/20 | 17/20 | 17/20 | 64–95% | no |
| **All** | **114/120** | **114/120** | **120/120** | **120/120** | **108/120** | **114/120** | | |

Tiers A and B together give 97/100 complete edges (about 92–99%). The gate, though, is judged per method and tier, and tier B misses it only through `name_with_identifier`.

**The six failures:**
- **32 (A):** "Adjei v Ak werter [2023] GHAHC 31". OCR split the name, so it was not linked to the citation and its conflict with the target (Republic v Jajah) went unchecked.
- **62, 98 (B, `name_with_identifier`):** one root cause. The citing judgment's own running header ("SUIT NO: H1/21/2022, Collins Amponsah Boateng vrs …, 28th July, 2022") resolved to its other publication. The re-publication rule missed it for two reasons:
  - the citing title separates parties with "-vrs-";
  - the title has a typo ("Retired Majot"), so the party words differ.
- **102, 105, 110 (C):**
  - SERAP v Nigeria resolved to the 2012 judgment instead of the 2010 ruling in the same application;
  - Ackah v Pergah resolved to the 2007 Court of Appeal judgment instead of the 2010 Supreme Court decision;
  - Republic v Osei Bonsu II resolved to a 2024 case instead of the 2007–2008 SCGLR authority.

**Span** is 108/120, now mostly boundary slips: omitted party text, footnote or OCR prefixes, cut identifiers. It doesn't block the graph, but it must improve before edge spans serve as fine-grained evidence in Phase 3.

## Phase 2 gate

A method or tier enters the deterministic graph only when its audited point estimates meet all of these. `coverage.report` reports each per method and tier, with a "Meets gate" column.

| Check | Threshold |
|---|---:|
| Complete edge (mention, target, evidence, temporal) | ≥ 95% |
| Target identity (`target_ok`: the right *decision*) | ≥ 97% |
| Evidence sentence (`evidence_ok`) | ≥ 95% |
| Temporal sanity | 100%, anomalies kept as review items |

- **Spans are not gated.** Decided 2026-10-28, after the v2 audit: an edge points to its evidence sentence, not to the exact reference span. Span precision (`span_ok`) is still measured and reported, so boundary slips stay visible without blocking the graph.
- **v2 under this gate:**
  - Name + report year (23/23 on every check) and name + judgment date (15/15) meet the thresholds on point estimates.
  - Tier A (38/40), name + identifier (20/22) and name only (16/20) do not.
  - With 15–23 edges, meeting a 97% threshold only fails to contradict it; it doesn't prove it (rule 7).
- **Tier C** is not expected to qualify. It stays candidate evidence for discovery and later entity-resolution work.
- **Samples** are drawn per tier and stratified within it (method, court, decade, OCR), excluding every reference in earlier sheets.
- **Smaller is acceptable:** a smaller graph that passes is preferable to a larger one that doesn't.

## Limitations

- **Extraction recall is not measured:** there is no gold set of mentions. Known misses:
  - text that lost its spaces ("GhanaRailwaycorporation,ExparteAppiah");
  - title spelling variants (Onyanchi/Onyachi);
  - references by one party name alone ("in Ackah's case");
  - report series printed with a gap ("[1982–83] GLR page 129").
- **Heuristic signals:** caption, stage and date signals are heuristics. A cue-less name in a judgment's opening 1,500 characters is treated as caption.
- **Report-year window:** law reports that lag the decision by more than two years (e.g. `GMJ`, `JELR`) are not resolved by report year.
- **Edges point at cases:** an edge is a re-publication group, recorded with the specific judgments that matched.
- **"No edge" proves nothing:** it means only that this build resolved none (rule 5).

## Next

1. **The deterministic graph is `phase2-v1`:** `neutral_exact`, `name_with_report` and `name_with_date` over build `3325b81913b3`. See `docs/graphrag/phase2-graph.md`.
2. **`name_with_identifier` is not admitted:** its targeted v4 audit scored 36/40. A case number identifies a proceeding, not a decision. Splitting the method, as described in `phase2-graph.md`, is deferred resolver work.
3. **Before Phase 3:** fix span boundaries. Span precision was 108/120 (v3) and 29/40 (targeted v4 sample).
