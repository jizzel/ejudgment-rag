# Phase 3 pilot

Run `ebf1c152-3ef3-4529-ae5c-727e2960df78` (2026-11-05T09:20:20+00:00), git `8d46488018`, dirty tree. Question set `3563115636bc`; graph `phase2-v2` (`67b8d2d0516afed7`), seeds 5.

Hypothesis-generating: paired counts and descriptive differences only. `G*-oracle` takes the direction from the question's class label.

## all

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 22 | 0.338 | 16 | 0.467 | 0.152 | 0.429 | 0.000 | 0.000 | 5.000 | 1169.200 |
| B0R | 22 | 0.338 | 16 | 0.485 | 0.152 | 0.429 | 0.000 | 0.000 | 5.000 | 1359.100 |
| G1-top5-label | 22 | 0.380 | 16 | 0.553 | 0.193 | 0.429 | 0.157 | 0.000 | 10.364 | 1356.000 |
| G1-top5-both | 22 | 0.377 | 16 | 0.478 | 0.188 | 0.429 | 0.157 | 0.000 | 20.818 | 1405.000 |
| G2-top5-label | 22 | 0.398 | 16 | 0.553 | 0.202 | 0.429 | 0.232 | 0.093 | 16.591 | 1431.800 |
| G1-routed | 22 | 0.457 | 18 | 0.568 | 0.275 | 0.929 | 0.045 | 0.000 | 6.636 | 1414.600 |

| Paired Hit@20 | Questions | Both | Only first | Only second | Neither | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| B0 vs G1-top5-label | 22 | 16 | 0 | 0 | 6 | 1.0 |
| B0R vs G1-top5-label | 22 | 16 | 0 | 0 | 6 | 1.0 |
| B0R vs G1-top5-both | 22 | 16 | 0 | 0 | 6 | 1.0 |
| B0R vs G2-top5-label | 22 | 16 | 0 | 0 | 6 | 1.0 |
| B0R vs G1-routed | 22 | 16 | 0 | 2 | 4 | 0.5 |
| G1-top5-label vs G1-routed | 22 | 16 | 0 | 2 | 4 | 0.5 |

## local

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 8 | 0.792 | 8 | 0.615 | 0.286 | – | – | – | 5.000 | 1450.600 |
| B0R | 8 | 0.792 | 8 | 0.615 | 0.286 | – | – | – | 5.000 | 1681.400 |
| G1-top5-label | 8 | 0.792 | 8 | 0.615 | 0.286 | – | – | – | 5.000 | 1657.200 |
| G1-top5-both | 8 | 0.792 | 8 | 0.615 | 0.286 | – | – | – | 9.000 | 1709.100 |
| G2-top5-label | 8 | 0.792 | 8 | 0.615 | 0.286 | – | – | – | 5.000 | 1650.500 |
| G1-routed | 8 | 0.792 | 8 | 0.615 | 0.286 | – | – | – | 0.000 | 1633.900 |

| Paired Hit@20 | Questions | Both | Only first | Only second | Neither | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| B0 vs G1-top5-label | 8 | 8 | 0 | 0 | 0 | 1.0 |
| B0R vs G1-top5-label | 8 | 8 | 0 | 0 | 0 | 1.0 |
| B0R vs G1-top5-both | 8 | 8 | 0 | 0 | 0 | 1.0 |
| B0R vs G2-top5-label | 8 | 8 | 0 | 0 | 0 | 1.0 |
| B0R vs G1-routed | 8 | 8 | 0 | 0 | 0 | 1.0 |
| G1-top5-label vs G1-routed | 8 | 8 | 0 | 0 | 0 | 1.0 |

## outgoing

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 3 | 0.000 | 0 | 0.000 | 0.000 | 0.667 | – | – | 5.000 | 999.800 |
| B0R | 3 | 0.000 | 0 | 0.000 | 0.000 | 0.667 | – | – | 5.000 | 1191.100 |
| G1-top5-label | 3 | 0.000 | 0 | 0.000 | 0.000 | 0.667 | – | – | 10.000 | 1235.700 |
| G1-top5-both | 3 | 0.000 | 0 | 0.000 | 0.000 | 0.667 | – | – | 16.333 | 1284.900 |
| G2-top5-label | 3 | 0.000 | 0 | 0.000 | 0.000 | 0.667 | – | – | 13.000 | 1273.700 |
| G1-routed | 3 | 0.111 | 1 | 0.000 | 0.111 | 0.667 | – | – | 3.667 | 1193.800 |

| Paired Hit@20 | Questions | Both | Only first | Only second | Neither | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| B0 vs G1-top5-label | 3 | 0 | 0 | 0 | 3 | 1.0 |
| B0R vs G1-top5-label | 3 | 0 | 0 | 0 | 3 | 1.0 |
| B0R vs G1-top5-both | 3 | 0 | 0 | 0 | 3 | 1.0 |
| B0R vs G2-top5-label | 3 | 0 | 0 | 0 | 3 | 1.0 |
| B0R vs G1-routed | 3 | 0 | 0 | 1 | 2 | 1.0 |
| G1-top5-label vs G1-routed | 3 | 0 | 0 | 1 | 2 | 1.0 |

## incoming

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 8 | 0.090 | 6 | 0.575 | 0.064 | 0.250 | – | – | 5.000 | 1162.300 |
| B0R | 8 | 0.090 | 6 | 0.562 | 0.064 | 0.250 | – | – | 5.000 | 1359.100 |
| G1-top5-label | 8 | 0.155 | 6 | 0.750 | 0.136 | 0.250 | – | – | 16.625 | 1356.000 |
| G1-top5-both | 8 | 0.146 | 6 | 0.543 | 0.116 | 0.250 | – | – | 35.375 | 1503.100 |
| G2-top5-label | 8 | 0.160 | 6 | 0.750 | 0.136 | 0.250 | – | – | 31.750 | 1484.700 |
| G1-routed | 8 | 0.366 | 7 | 0.792 | 0.335 | 1.000 | – | – | 15.875 | 1414.600 |

| Paired Hit@20 | Questions | Both | Only first | Only second | Neither | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| B0 vs G1-top5-label | 8 | 6 | 0 | 0 | 2 | 1.0 |
| B0R vs G1-top5-label | 8 | 6 | 0 | 0 | 2 | 1.0 |
| B0R vs G1-top5-both | 8 | 6 | 0 | 0 | 2 | 1.0 |
| B0R vs G2-top5-label | 8 | 6 | 0 | 0 | 2 | 1.0 |
| B0R vs G1-routed | 8 | 6 | 0 | 1 | 1 | 1.0 |
| G1-top5-label vs G1-routed | 8 | 6 | 0 | 1 | 1 | 1.0 |

## lineage

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 3 | 0.127 | 2 | 0.250 | 0.223 | 0.667 | 0.000 | 0.000 | 5.000 | 421.600 |
| B0R | 3 | 0.127 | 2 | 0.417 | 0.223 | 0.667 | 0.000 | 0.000 | 5.000 | 611.400 |
| G1-top5-label | 3 | 0.262 | 2 | 0.417 | 0.320 | 0.667 | 0.157 | 0.000 | 8.333 | 686.800 |
| G1-top5-both | 3 | 0.262 | 2 | 0.417 | 0.335 | 0.667 | 0.157 | 0.000 | 18.000 | 620.100 |
| G2-top5-label | 3 | 0.381 | 2 | 0.417 | 0.381 | 0.667 | 0.232 | 0.093 | 10.667 | 611.100 |
| G1-routed | 3 | 0.151 | 2 | 0.417 | 0.254 | 1.000 | 0.045 | 0.000 | 2.667 | 579.700 |

| Paired Hit@20 | Questions | Both | Only first | Only second | Neither | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| B0 vs G1-top5-label | 3 | 2 | 0 | 0 | 1 | 1.0 |
| B0R vs G1-top5-label | 3 | 2 | 0 | 0 | 1 | 1.0 |
| B0R vs G1-top5-both | 3 | 2 | 0 | 0 | 1 | 1.0 |
| B0R vs G2-top5-label | 3 | 2 | 0 | 0 | 1 | 1.0 |
| B0R vs G1-routed | 3 | 2 | 0 | 0 | 1 | 1.0 |
| G1-top5-label vs G1-routed | 3 | 2 | 0 | 0 | 1 | 1.0 |

Provisional (unreviewed local controls): local-fact-06, local-fact-08, local-fact-10, local-fact-12, local-issue-01, local-issue-07, local-issue-10, local-issue-15.

## Routing (G1-routed)

| Class | Questions | Named case extracted | Anchor found | Direction correct | Resolved seeds |
|---|---:|---:|---:|---:|---:|
| all | 22 | 14 | 0.929 | 1.000 | 0.818 |
| local | 8 | 0 | – | – | 0.000 |
| outgoing | 3 | 3 | 0.667 | 1.000 | 2.333 |
| incoming | 8 | 8 | 1.000 | 1.000 | 1.000 |
| lineage | 3 | 3 | 1.000 | 1.000 | 1.000 |

| Question | Name | Year | Direction | Resolved | Anchor found |
|---|---|---:|---|---:|---|
| p3-in-05 | William v United Republic of Tanzania | 2018 | incoming | 1 | True |
| p3-in-06 | Kambole v Tanzania | 2020 | incoming | 1 | True |
| p3-in-07 | Abubakari v Tanzania | 2019 | incoming | 1 | True |
| p3-in-08 | Boi and Others v Adjei and Others | 2014 | incoming | 1 | True |
| p3-in-09 | Ashun v Accra Brewery Ltd | 2008 | incoming | 1 | True |
| p3-in-10 | Jaas Company Ltd and Another v Apau and Another | 2009 | incoming | 1 | True |
| p3-in-11 | Kunutsor v Tetteh | 2008 | incoming | 1 | True |
| p3-in-12 | Isiaga v United Republic of Tanzania | 2018 | incoming | 1 | True |
| p3-lin-01 | National Convention of Teachers Trade Union v Republic of Gabon | 2011 | incoming | 1 | True |
| p3-lin-03 | Gabriel and Another v United Republic of Tanzania | 2024 | incoming | 1 | True |
| p3-lin-06 | Kangberee v Mohammed | 2012 | outgoing | 1 | True |
| p3-out-01 | Arthur v Arthur | 2023 | outgoing | 5 | False |
| p3-out-07 | Purohit and Another v Gambia | 2003 | outgoing | 1 | True |
| p3-out-08 | Republic v Jajah, Ex parte Asafo Adjei | 2023 | outgoing | 1 | True |

## Stress test p3-lin-02 (not in the scores above)

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 1 | 0.030 | 1 | 0.000 | 0.030 | 1.000 | – | – | 5.000 | 320.300 |
| B0R | 1 | 0.030 | 1 | 0.500 | 0.030 | 1.000 | – | – | 5.000 | 532.300 |
| G1-top5-label | 1 | 0.179 | 1 | 0.500 | 0.164 | 1.000 | – | – | 36.000 | 666.300 |
| G1-top5-both | 1 | 0.149 | 1 | 0.333 | 0.149 | 1.000 | – | – | 53.000 | 838.200 |
| G2-top5-label | 1 | 0.164 | 1 | 0.500 | 0.149 | 1.000 | – | – | 89.000 | 818.900 |
| G1-routed | 1 | 0.209 | 1 | 0.500 | 0.209 | 1.000 | – | – | 21.000 | 594.000 |
