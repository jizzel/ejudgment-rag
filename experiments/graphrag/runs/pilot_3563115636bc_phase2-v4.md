# Phase 3 pilot

Run `667f9ecf-00a7-4dd4-ac70-066859763b1b` (2026-11-06T12:32:51+00:00), git `6e2a8181bd`, dirty tree. Question set `3563115636bc`; graph `phase2-v4` (`8655a988915b3592`), seeds 5.

Hypothesis-generating: paired counts and descriptive differences only. `G*-oracle` takes the direction from the question's class label.

## all

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 22 | 0.347 | 16 | 0.471 | 0.152 | 0.429 | 0.000 | 0.000 | 5.000 | 1361.500 |
| B0R | 22 | 0.347 | 16 | 0.493 | 0.152 | 0.429 | 0.000 | 0.000 | 5.000 | 1547.200 |
| G1-top5-label | 22 | 0.405 | 17 | 0.557 | 0.211 | 0.429 | 0.157 | 0.000 | 10.636 | 1522.800 |
| G1-top5-both | 22 | 0.403 | 17 | 0.481 | 0.206 | 0.429 | 0.141 | 0.000 | 22.818 | 1548.100 |
| G2-top5-label | 22 | 0.410 | 16 | 0.557 | 0.205 | 0.429 | 0.247 | 0.111 | 16.546 | 1566.700 |
| G1-routed | 22 | 0.514 | 19 | 0.572 | 0.328 | 0.929 | 0.045 | 0.000 | 6.500 | 1518.100 |

| Paired Hit@20 | Questions | Both | Only first | Only second | Neither | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| B0 vs G1-top5-label | 22 | 16 | 0 | 1 | 5 | 1.0 |
| B0R vs G1-top5-label | 22 | 16 | 0 | 1 | 5 | 1.0 |
| B0R vs G1-top5-both | 22 | 16 | 0 | 1 | 5 | 1.0 |
| B0R vs G2-top5-label | 22 | 16 | 0 | 0 | 6 | 1.0 |
| B0R vs G1-routed | 22 | 16 | 0 | 3 | 3 | 0.25 |
| G1-top5-label vs G1-routed | 22 | 17 | 0 | 2 | 3 | 0.5 |

## local

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 8 | 0.812 | 8 | 0.625 | 0.286 | – | – | – | 5.000 | 2941.800 |
| B0R | 8 | 0.812 | 8 | 0.625 | 0.286 | – | – | – | 5.000 | 2996.500 |
| G1-top5-label | 8 | 0.812 | 8 | 0.625 | 0.286 | – | – | – | 5.000 | 2969.300 |
| G1-top5-both | 8 | 0.812 | 8 | 0.625 | 0.286 | – | – | – | 12.875 | 3033.000 |
| G2-top5-label | 8 | 0.812 | 8 | 0.625 | 0.286 | – | – | – | 5.000 | 2929.200 |
| G1-routed | 8 | 0.812 | 8 | 0.625 | 0.286 | – | – | – | 0.000 | 2943.800 |

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
| B0 | 3 | 0.000 | 0 | 0.000 | 0.000 | 0.667 | – | – | 5.000 | 371.400 |
| B0R | 3 | 0.000 | 0 | 0.000 | 0.000 | 0.667 | – | – | 5.000 | 589.800 |
| G1-top5-label | 3 | 0.111 | 1 | 0.000 | 0.111 | 0.667 | – | – | 11.333 | 691.800 |
| G1-top5-both | 3 | 0.111 | 1 | 0.000 | 0.111 | 0.667 | – | – | 17.667 | 686.200 |
| G2-top5-label | 3 | 0.000 | 0 | 0.000 | 0.000 | 0.667 | – | – | 15.667 | 691.700 |
| G1-routed | 3 | 0.111 | 1 | 0.000 | 0.111 | 0.667 | – | – | 3.000 | 570.800 |

| Paired Hit@20 | Questions | Both | Only first | Only second | Neither | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| B0 vs G1-top5-label | 3 | 0 | 0 | 1 | 2 | 1.0 |
| B0R vs G1-top5-label | 3 | 0 | 0 | 1 | 2 | 1.0 |
| B0R vs G1-top5-both | 3 | 0 | 0 | 1 | 2 | 1.0 |
| B0R vs G2-top5-label | 3 | 0 | 0 | 0 | 3 | 1.0 |
| B0R vs G1-routed | 3 | 0 | 0 | 1 | 2 | 1.0 |
| G1-top5-label vs G1-routed | 3 | 1 | 0 | 0 | 2 | 1.0 |

## incoming

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 8 | 0.094 | 6 | 0.576 | 0.064 | 0.250 | – | – | 5.000 | 1543.300 |
| B0R | 8 | 0.094 | 6 | 0.575 | 0.064 | 0.250 | – | – | 5.000 | 1751.800 |
| G1-top5-label | 8 | 0.162 | 6 | 0.750 | 0.143 | 0.250 | – | – | 16.875 | 1937.300 |
| G1-top5-both | 8 | 0.155 | 6 | 0.543 | 0.124 | 0.250 | – | – | 36.125 | 2246.200 |
| G2-top5-label | 8 | 0.171 | 6 | 0.750 | 0.145 | 0.250 | – | – | 30.625 | 2164.300 |
| G1-routed | 8 | 0.502 | 8 | 0.792 | 0.473 | 1.000 | – | – | 15.875 | 1895.800 |

| Paired Hit@20 | Questions | Both | Only first | Only second | Neither | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| B0 vs G1-top5-label | 8 | 6 | 0 | 0 | 2 | 1.0 |
| B0R vs G1-top5-label | 8 | 6 | 0 | 0 | 2 | 1.0 |
| B0R vs G1-top5-both | 8 | 6 | 0 | 0 | 2 | 1.0 |
| B0R vs G2-top5-label | 8 | 6 | 0 | 0 | 2 | 1.0 |
| B0R vs G1-routed | 8 | 6 | 0 | 2 | 0 | 0.5 |
| G1-top5-label vs G1-routed | 8 | 6 | 0 | 2 | 0 | 0.5 |

## lineage

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 3 | 0.127 | 2 | 0.250 | 0.223 | 0.667 | 0.000 | 0.000 | 5.000 | 524.000 |
| B0R | 3 | 0.127 | 2 | 0.417 | 0.223 | 0.667 | 0.000 | 0.000 | 5.000 | 721.600 |
| G1-top5-label | 3 | 0.262 | 2 | 0.417 | 0.320 | 0.667 | 0.157 | 0.000 | 8.333 | 747.800 |
| G1-top5-both | 3 | 0.262 | 2 | 0.417 | 0.335 | 0.667 | 0.141 | 0.000 | 19.000 | 840.500 |
| G2-top5-label | 3 | 0.381 | 2 | 0.417 | 0.381 | 0.667 | 0.247 | 0.111 | 10.667 | 747.100 |
| G1-routed | 3 | 0.151 | 2 | 0.417 | 0.254 | 1.000 | 0.045 | 0.000 | 2.333 | 713.500 |

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
| all | 22 | 14 | 0.929 | 1.000 | 0.727 |
| local | 8 | 0 | – | – | 0.000 |
| outgoing | 3 | 3 | 0.667 | 1.000 | 1.667 |
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
| p3-out-01 | Arthur v Arthur | 2023 | outgoing | 3 | False |
| p3-out-07 | Purohit and Another v Gambia | 2003 | outgoing | 1 | True |
| p3-out-08 | Republic v Jajah, Ex parte Asafo Adjei | 2023 | outgoing | 1 | True |

## Stress test p3-lin-02 (not in the scores above)

| System | questions | recall@20 | hit@20 | mrr@10 | passage_recall@20 | seed_recall | gold_edge_recall | complete_path_share | nodes_visited | latency_p50_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 1 | 0.030 | 1 | 0.000 | 0.030 | 1.000 | – | – | 5.000 | 402.300 |
| B0R | 1 | 0.030 | 1 | 0.500 | 0.030 | 1.000 | – | – | 5.000 | 630.200 |
| G1-top5-label | 1 | 0.182 | 1 | 0.500 | 0.164 | 1.000 | – | – | 36.000 | 752.400 |
| G1-top5-both | 1 | 0.151 | 1 | 0.333 | 0.149 | 1.000 | – | – | 53.000 | 948.500 |
| G2-top5-label | 1 | 0.182 | 1 | 0.500 | 0.164 | 1.000 | – | – | 87.000 | 962.500 |
| G1-routed | 1 | 0.212 | 1 | 0.500 | 0.209 | 1.000 | – | – | 21.000 | 780.100 |
