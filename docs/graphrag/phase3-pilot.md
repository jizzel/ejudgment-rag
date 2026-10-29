# Phase 3: graph-augmented retrieval pilot

> Research stream, `docs/graphrag/AGENTS.md`. Status 2026-10-29: **run** (`da7ac400`, with the Phase 5 routing probe `G1-routed`); results and error analysis in [`phase3-results.md`](phase3-results.md). The dry-run notes below test the machinery and are not findings.

## Question set status

- **Written and locked:** Lexi wrote the 22 relational intents blind from the seed sheet (8 outgoing, 8 incoming, 6 lineage, the lineage split 3 incoming and 3 outgoing). Each uses a different seed, and the anchors were chosen without seeing connectivity. With 8 seeded local controls, all 30 intents were locked on 2026-10-29 in `evals/graphrag_pilot.jsonl`.
- **Checked before locking:** every anchor is an eligible judgment and is the case of the seed it cites.
- **Two incoming questions retired:**
  - `p3-in-03` (Ellembelle District Assembly v Mensah, [2023] GHADC 77) and `p3-in-04` (Edusei v Sodji, [2023] GHACC 719).
  - The graph-independent gold finder found no other judgment naming both parties or carrying the citation, so no citing decision exists to score against.
  - They stay in the file with their locked intents and the reason. Two replacement intents are to be written blind from unused seeds.
  - That 2 of 10 incoming anchors have no citing decision in the corpus is itself a coverage observation.
- **Gold-finder fixes:** the finder dropped party names shorter than four letters ("Adu", "Boi"), and capped sheets at 300 rows after sorting by date, which would have dropped the latest citing cases. Both are fixed, and the cap (now 1,000) is reported if reached.
- **Replacements:** `p3-in-09` (Ashun v Accra Brewery) and `p3-in-10` (Jaas Company v Apau) were written blind by Lexi from unused seeds and locked on 2026-10-29.
- **Three more retired after gold review** (Lexi, 2026-10-29), because no defensible gold exists:
  - `p3-in-01`: its 26 candidates were partial-name collisions;
  - `p3-in-02`: its 130 candidates did not establish a later decision citing this specific anchor;
  - `p3-out-03`: its candidate passages name no corpus case used as authority.

  Active: 8 local, 7 outgoing, 6 incoming, 6 lineage; replacements are pending.
- **Gold imported (2026-10-29)** from Lexi's marked sheets, which match her review summary row for row. Every gold passage occurs verbatim in its chunk.
  - incoming: `p3-in-05` 42, `p3-in-06` 42, `p3-in-07` 28 and `p3-in-08` 56 gold cases;
  - outgoing: `p3-out-01` 1, `p3-out-07` 3 and `p3-out-08` 3 gold cases.
- **Gold is corpus-only** (decided 2026-10-29). A system can only retrieve what the export holds, so a cited authority the corpus lacks is left out of gold and recorded in `runs/pilot_outside_corpus.csv` (identifiers only).
  - **Most authorities are absent:** of the 32 authorities accepted for `p3-out-02/04/05/06/08`, 27 (84%) are not in the export, among them classic reported authorities such as Djin v Musah, Tuakwa v Bosom, Fenuku v John-Teye and Gregory v Tandoh. Six accepted lineage first hops are absent too.
  - **Retired for having no corpus gold:** `p3-out-02`, `p3-out-04`, `p3-out-05`, `p3-out-06` and `p3-lin-04`.
  - **Active now:** 8 local, 6 incoming (2 without gold yet: `p3-in-09`, `p3-in-10`), 3 outgoing and 5 lineage.
  - **What this says about outgoing questions:** answering "what did this case rely on" is mostly a coverage problem in this corpus. That is the law-report gap Phase 1 measured, now seen from the question side.
- **Lineage gold is a set of complete chains** (`gold_paths`), not one path. A question can have many: `p3-lin-02` has 71 accepted first hops, a much larger gold universe than the other lineage questions, which the analysis must note.
- **Second-hop sheets** (`pilot_gold_<id>_hop2.csv`) were generated from the 90 accepted first hops.
  - 6 first hops are not in the corpus at all and cannot be gold: both of `p3-lin-04`'s, 1 of `p3-lin-05`'s and 3 of `p3-lin-06`'s. `p3-lin-04` therefore has no chain left.
  - `p3-lin-05` is deliberately partial (two ECOWAS authorities with established URIs).
  - Sheet sizes: 769, 6,731, 125, 0, 11 and 75 candidate rows for `lin-01` to `lin-06`.
- **Gold review round 2 (Lexi, imported 2026-10-29)**, matching her round-2 summary row for row:
  - incoming: `p3-in-09` 24 and `p3-in-10` 5 gold cases;
  - lineage chains: `p3-lin-01` 5 and `p3-lin-03` 18 complete paths (the duplicate publication of Zabron is not a separate first hop).
  - **Five quotes were cut short** where "v." was taken for a full stop ("See Ashun v.", "Femi Falana v.", …). Each row stays gold, but its passage is left out (the import copies `artifacts/pilot_gold_<id>_import.csv` say which). `gold_finder` now reports a quote under 20 characters with its row instead of crashing.
  - **Lookup queue:** none of the 28 authorities queued for `p3-lin-05`/`lin-06` resolves to an eligible corpus judgment consistent in name and year. The checks were `gold_finder lookup` by name, a surname search dated before the citing judgment, and for Tidjani its suit number in the text. Outcomes are in `runs/pilot_lookup_queue_round2.csv`. The closest miss is Assemblies of God v Obeng: the corpus has the Court of Appeal decision of 22 April 2005, but the authority is the Supreme Court decision of 3 February 2010.
  - **`p3-lin-05` retired:** Hammani Tidjani v Nigeria (ECW/CCJ/APP/01/06) is not in the corpus.
  - **`p3-lin-06` keeps one chain, not two.** The Ackah v Pergah Transport row named `/akn/gh/judgment/ghasc/2010/16/eng@2010-04-21`, which does not exist in the corpus: the passage cites the Supreme Court report [2010] SCGLR 728, and the export holds only the 2007 Court of Appeal decision ([2007] GHACA 14). The row is recorded as outside the corpus.
  - **`p3-lin-02` is a stress test** (`questions stress-test`). Narrowed to the 7 December 2018 reparations decision (its locked anchor), it still has 67 first hops, and its 6,731 second-hop candidates were not marked. Its gold stops at the first hop. It runs with the rest but is reported apart and is in no primary score. The designation is part of the gold hash, so it cannot change after locking.
  - **Replacements:** `p3-out-09` (Republic v High Court (Commercial Division) Tamale, s-008), `p3-in-11` (Kunutsor v Tetteh, s-108) and `p3-in-12` (Isiaga v Tanzania, s-120). Each anchor matches its seed and none of the seeds had been used. They were locked on 2026-10-29, and their gold sheets hold 21, 1 and 172 candidate rows.
- **Replacement gold (Lexi, imported 2026-10-29):**
  - `p3-in-11`: 1 citing decision.
  - `p3-in-12`: 89 citing decisions, one evidence passage each. Excluded were references only to the 2021 reparations decision, passages that only report a party's submission, and one ambiguous stage/date reference.
  - **`p3-out-09` retired.** Its anchor relies on 12 substantive authorities: 7 foreign and 5 Ghanaian (Mornah v Attorney-General, Ex parte Abubakari (No 1), Amponsah v Minister of Defence, Ex parte Double Crown, Sumani Munji v Iddrissu). None of the 5 resolves to the cited decision in the corpus (`runs/pilot_lookup_queue_round3.csv`). The nearest title, [2009] GHASC 11, is *Ex parte Millicom*, not Double Crown.
- **Lineage passages:** a first hop that no marked chain continues is not a gold case, so its passage is not gold either. `import_lineage` now drops such passages, which `lock-gold` had flagged in `p3-lin-01` (1) and `p3-lin-03` (2). The chains are unchanged.
- **Gold locked 2026-10-29.** 8 local, 8 incoming, 3 outgoing and 3 lineage questions, plus the `p3-lin-02` stress test; 12 retired.
  - Outgoing questions are now the thinnest class: 3 of the 9 written (counting the replacement) have corpus gold, with 1, 3 and 3 gold cases.
- **The coverage asymmetry is a finding, not something to design around:**
  - Outgoing questions are limited by the historical law reports the export lacks. Of the outgoing authorities and second hops looked up, most are absent, and `p3-lin-06` lost 27 of 29 accepted second hops this way.
  - Incoming questions are well supported (5 to 56 citing decisions each).
  - The pilot reports per class, so this shows up as fewer outgoing and lineage questions, not as a tuned design.

## Question

Does the `phase2-v1` citation graph add retrieval value beyond the default E-Judgment search, and for which information needs? The hypotheses:
- **H1:** local questions don't gain.
- **H2:** relational questions do.
- **H3:** questions about later treatment (incoming citations) gain most.

## Design (decided 2026-10-29)

| | |
|---|---|
| **Questions** | 8 local controls, 8 outgoing ("what did X rely on for Y"), 8 incoming ("which later decisions applied X on Y"), 6 two-hop lineage: 30. Hypothesis-generating; paired counts only. |
| **Who writes** | Lexi writes the 22 relational intents blind, from the seed sheet, and verifies all gold. The 8 local controls are a seeded draw from `evals/gold.jsonl` (issue and fact-pattern questions; provisional, since that set is unreviewed). |
| **Gold** | Found without the resolver or the graph (`pilot/gold_finder.py`: text search over the corpus) and decided by a person. Never copied from a system's output (rule 6). |
| **Direction** | `G1-top5-label` and `G2-top5-label` take it from the question's class label: an oracle for the direction only (their seeds are B0's top 5). There is also a direction-blind "both ways" variant, and `G1-routed` reads it from the wording. |

### Systems

All use the same query string and filters, and the default models. The run stops if search is degraded.

| System | What it does |
|---|---|
| **B0** | Default search: exact lookup, lexical + dense, RRF, cross-encoder rerank, case grouping. Top 20 cases, as served. |
| **B0R** | B0's passages rescored by the cross-encoder, no graph. The G systems rescore every candidate the same way, so **G vs B0R isolates the graph's contribution** from the rescoring. |
| **G1-top5-label** (was `G1-oracle`) | B0's top 5 cases as seeds, one hop in the labelled direction, citing passages and nearest passages added, everything rescored. |
| **G1-top5-both** (was `G1-both`) | One hop both ways, whatever the question asks. |
| **G2-top5-label** (was `G2-oracle`) | Two hops in the labelled direction. |
| **G1-routed** (Phase 5 probe, added after the first run) | The case the question names, resolved with the search's own lookups, as the only seed; the direction from the wording; one hop with the same limits. Unresolved: no expansion (= B0R). |

**Expansion limits:** 50 nodes for G1 and 100 for G2, 20 neighbours per node, and a hub limit. A case cited by more than 50 others is reached but not expanded. Cycles and repeat visits are suppressed.

**Candidate passages for a reached case:**
- the citing passages of the edge it was reached by (at most 2);
- for an outgoing hop, also the reached case's own passage nearest the query.

### Metrics

Reported per class and per direction, paired against B0 and B0R:
- **Case:** Recall@20 (share of gold cases), Hit@20, MRR@10.
- **Evidence:** supporting-passage Recall@20. A returned passage of the gold case contains the gold passage, or lies inside it.
- **Graph:** seed recall (did B0 find the case the question names?), gold node and gold edge recall, complete paths, unnecessary nodes visited, first relevant hop.
- **Cost:** latency p50/p95, nodes visited, candidate growth.
- **Paired Hit@20:** exact counts and the exact McNemar p as a number. No significance claims (rule 7).

## Workflow

1. **Seed sheet:** `python -m experiments.graphrag.pilot.seeds` → `artifacts/pilot_seeds.csv` (done).
   - It holds 120 candidate anchors from 52 strata (court × incoming-degree band × period). 57 of them are cases no corpus judgment is linked to.
   - The writer sees only citation, court, date and GhaLII link. Degrees and strata are in `pilot_seeds_key.csv`.
2. **Write the intents:** Lexi fills `experiments/graphrag/pilot/intents_template.csv` (one row per question; lists separated by `;`):
   - `class`, `query` (the exact wording), `intent`;
   - `anchor_uris` (the seed's AKN path), optional `anchor_citations` (report citations, for the gold finder only);
   - `direction` (lineage only), `sampling` (e.g. "seed s-017"), `written_by`.
3. **Import and lock the intents:**
   - `questions import-intents --sheet <csv>`;
   - `questions draw-locals` (8 local controls);
   - `questions lock-intents`, which freezes the wording before any gold finding or run.
4. **Find gold**, per question:
   - `gold_finder sheet --question <id>` writes `artifacts/pilot_gold_<id>.csv`;
   - Lexi marks `relevant` and `on_issue`, adds a verbatim `gold_text`, and for outgoing questions the `cited_uri` (`gold_finder lookup --citation …` or `--name …` helps);
   - `gold_finder import --question <id> --sheet <csv>` (`--path a,b,c` for lineage).
5. **Lock the gold:** `questions lock-gold`. Before that, `questions retire --id … --reason …` takes out a question with no defensible gold, and `questions stress-test --id … --reason …` moves one out of the primary scores.
6. **Run:** `python -m experiments.graphrag.pilot.run`. It refuses an unlocked or changed set, writes `runs/pilot_<hash>.json/.md` and an `evaluation_runs` row, and puts per-question records in `artifacts/`.
7. **Write up:** a research note with the results, an error analysis per failed question, and what it means for H1–H3, Phase 4 and Phase 5.

## Dry run (machinery only, 2026-10-29)

Three placeholder questions against the dev database: an incoming question on Mensah v Mensah [2012] GHASC 8, an outgoing one on Sky v Parliament of Ghana [2024] GHASC 66, and one drawn local control. Their gold was taken from the graph itself, so **the numbers are circular and are not results**. It confirmed that:
- every system runs on the real models, the expansion caps hold, and local controls with no direction equal B0R;
- latency is about 1–6 s per question, almost all of it B0's search.

It also showed a design point that the metric now records: **seeds decide what the graph can reach**. For "Which later decisions applied Mensah v Mensah on sharing property acquired during marriage?", B0's top 5 were other matrimonial-property cases, not Mensah v Mensah. So incoming expansion started from the wrong cases, although 115 corpus cases cite it.

Seed recall is now reported per question. If it is low on the real set, finding the case a question names is a Phase 5 router matter, to be reported rather than patched into the pilot.

## Limits

- **The gold finder:** recall is bounded by spelling variants, OCR and references by one party name. It is the same gold for every system.
- **The graph:** `phase2-v1` holds 3,886 edges, 72% of cases are isolated, and Ghanaian lower courts are rarely cited. The pilot measures the graph as it is.
- **Unreviewed controls:** local controls come from the unreviewed gold set and are provisional.
