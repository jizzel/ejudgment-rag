"""Phase 3 pilot runner: the baseline against graph expansion on the same questions.

    python -m experiments.graphrag.pilot.run [--policy phase2-v1] [--seed-k 5]
    python -m experiments.graphrag.pilot.run --dry-run --file <placeholder.jsonl>

Systems (docs/graphrag/AGENTS.md, Phase 3), all on the same query string and filters:

- **B0**: the default E-Judgment search (exact lookup, lexical + dense, RRF, cross-encoder
  rerank, case grouping), top 20 cases, as served.
- **B0R**: B0's own passages rescored by the cross-encoder, no graph. G systems rescore every
  candidate the same way, so G against B0R isolates what the graph adds from the
  rescoring itself.
- **G1-oracle**: B0's top ``seed_k`` cases are seeds; one hop along ``CITES`` (outgoing:
  what a case relied on) or ``CITED_BY`` (incoming: later treatment) in the direction the
  question's class states (an oracle: query-adaptive routing is Phase 5). A question with
  no direction (local controls) gets B0R.
- **G1-both**: one hop both ways, whatever the question asks (the naive baseline a router
  must beat).
- **G2-oracle**: as G1-oracle, two hops.

Expansion is bounded (nodes, branching, hub degree; cycles and repeat visits suppressed:
``graph.traverse.expand``). Candidate passages for a reached case are the edge's citing
passages (the occurrence chunks: for an outgoing hop they lie in the citing case, for an
incoming hop in the reached case) and, for an outgoing hop, the reached case's own
passage nearest the query. Cases are ranked by their best cross-encoder score.

Read-only. The run stops if search is degraded (no embedding model, missing vectors, no
reranker): the comparison is only meaningful against the default search.
"""

import argparse
import hashlib
import json
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, bindparam, text

from ejudgment.config import Settings, get_settings
from ejudgment.db import make_engine
from ejudgment.domain.schemas import SearchRequest, SearchResponse
from ejudgment.embeddings.base import EmbeddingProvider, Reranker
from ejudgment.embeddings.loading import load_providers
from ejudgment.evaluation.retrieval import corpus_version, store_run
from ejudgment.retrieval.repository import CONTEXT_HASH_SQL, vector_literal
from ejudgment.retrieval.service import search
from ejudgment.verification.support import normalise
from experiments.graphrag.graph.build import Graph, corpus_mismatches
from experiments.graphrag.graph.policy import POLICIES
from experiments.graphrag.graph.traverse import Hop, expand
from experiments.graphrag.manifest import ARTIFACTS_DIR, RUNS_DIR, research_manifest, write_json
from experiments.graphrag.pilot.questions import PILOT_FILE, PilotQuestion, load_pilot, run_problems
from experiments.graphrag.pilot.report import markdown, summarise

VERSION = "pilot-runner-v2"
SYSTEMS = ("B0", "B0R", "G1-oracle", "G1-both", "G2-oracle")


@dataclass(frozen=True)
class RunConfig:
    top_k: int = 20
    seed_k: int = 5
    g1_max_nodes: int = 50
    g2_max_nodes: int = 100
    g2_depth: int = 2
    max_branching: int = 20
    hub_degree: int | None = 50
    occurrences_per_edge: int = 2


@dataclass
class GraphView:
    outgoing: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    incoming: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # (citing case, cited case) -> occurrence chunk ids
    occurrences: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    group_of_uri: dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""
    # The corpus snapshot the graph was built from (its manifest's corpus fingerprint).
    corpus: dict[str, Any] = field(default_factory=dict)

    def adjacency(self, direction: str) -> dict[str, set[str]]:
        return self.outgoing if direction == "outgoing" else self.incoming


class GraphArtifactError(RuntimeError):
    """The graph files do not match their build manifest, or the manifest is missing."""


def load_view(artifacts: Path, policy: str, runs: Path = RUNS_DIR) -> GraphView:
    """The graph as built, verified: its fingerprint is recomputed from the node and edge
    files and must equal the build manifest's, so a report never names a graph other than
    the one evaluated (docs/graphrag/AGENTS.md, provenance)."""
    manifest_path = runs / f"graph_{policy}.json"
    if not manifest_path.exists():
        raise GraphArtifactError(f"no build manifest {manifest_path}: build the graph first")
    manifest = json.loads(manifest_path.read_text())
    if policy not in POLICIES:
        raise GraphArtifactError(f"unknown admission policy {policy}")
    graph = Graph(POLICIES[policy])
    view = GraphView()
    with (artifacts / f"graph_{policy}_nodes.jsonl").open() as handle:
        for line in handle:
            node = json.loads(line)
            graph.nodes[node["case"]] = node
            for judgment in node["judgments"]:
                view.group_of_uri[judgment["uri"]] = node["case"]
    with (artifacts / f"graph_{policy}_edges.jsonl").open() as handle:
        for line in handle:
            edge = json.loads(line)
            source, target = edge["source_case"], edge["target_case"]
            graph.edges[(source, target)] = edge["occurrences"]
            view.outgoing[source].add(target)
            view.incoming[target].add(source)
            view.occurrences[(source, target)] = [o["chunk_id"] for o in edge["occurrences"]]
    fingerprint = graph.fingerprint()
    if fingerprint != manifest.get("graph_fingerprint"):
        raise GraphArtifactError(
            f"graph files fingerprint {fingerprint[:16]} differs from the manifest's "
            f"{str(manifest.get('graph_fingerprint'))[:16]}: rebuild the graph"
        )
    view.fingerprint = fingerprint
    view.corpus = manifest.get("corpus_fingerprint") or {}
    return view


def plan(
    system: str, question: PilotQuestion, config: RunConfig
) -> tuple[tuple[str, ...], int, int]:
    """Directions, depth and node budget of a system for a question."""
    labelled = question.traversal_direction()
    if system in ("B0", "B0R"):
        return (), 0, 0
    if system == "G1-both":
        return ("outgoing", "incoming"), 1, config.g1_max_nodes
    directions = (labelled,) if labelled else ()
    if system == "G1-oracle":
        return directions, 1, config.g1_max_nodes
    return directions, config.g2_depth, config.g2_max_nodes


def expand_seeds(
    view: GraphView,
    seeds: list[str],
    directions: tuple[str, ...],
    depth: int,
    budget: int,
    config: RunConfig,
) -> list[tuple[Hop, str]]:
    """Every case reached from the seeds, each once (its first, shortest hop), within budget."""
    reached: dict[str, tuple[Hop, str]] = {}
    for direction in directions:
        for seed in seeds:
            for hop in expand(
                view.adjacency(direction),
                seed,
                max_depth=depth,
                max_nodes=budget,
                max_branching=config.max_branching,
                hub_degree=config.hub_degree,
            ):
                # A seed reached along an edge still counts: its citing passage is the
                # evidence the edge contributes, which B0's passages may not include.
                current = reached.get(hop.case)
                if current is None or hop.depth < current[0].depth:
                    reached[hop.case] = (hop, direction)
                if len(reached) >= budget:
                    return sorted(reached.values(), key=lambda h: (h[0].depth, h[0].case))
    return sorted(reached.values(), key=lambda h: (h[0].depth, h[0].case))


def hop_candidates(view: GraphView, hop: Hop, direction: str, config: RunConfig) -> list[str]:
    """Occurrence chunks of the edge a hop crossed (the passage that makes the citation)."""
    parent = hop.path[-2]
    key = (parent, hop.case) if direction == "outgoing" else (hop.case, parent)
    return view.occurrences.get(key, [])[: config.occurrences_per_edge]


def nearest_chunks(
    conn: Connection, embedder: EmbeddingProvider, query: str, groups: list[str]
) -> dict[str, str]:
    """For each case, its chunk nearest the query (current vectors only, as in search)."""
    if not groups:
        return {}
    dim = int(embedder.dimension)
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (c.source_text_hash) c.source_text_hash AS grp, c.id::text AS id "
            "FROM chunk_embeddings e JOIN chunks c ON c.id = e.chunk_id "
            "JOIN judgments j ON j.id = c.judgment_id "
            "WHERE e.model_id = :model AND e.model_revision = :revision "
            f"AND e.context_hash = {CONTEXT_HASH_SQL} AND j.eligibility_status = 'eligible' "
            "AND c.source_text_hash IN :groups "
            f"ORDER BY c.source_text_hash, (e.embedding::vector({dim})) <=> "
            f"CAST(:q AS vector({dim})), c.id"
        ).bindparams(bindparam("groups", expanding=True)),
        {
            "model": embedder.model_id,
            "revision": embedder.model_revision,
            "groups": groups,
            "q": vector_literal(embedder.embed_query(query)),
        },
    )
    return {row.grp: row.id for row in rows}


def chunk_texts(conn: Connection, ids: list[str]) -> dict[str, tuple[str, str]]:
    """chunk id -> (content, canonical URI of the judgment the chunk belongs to)."""
    if not ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT c.id::text AS id, c.content, j.canonical_uri FROM chunks c "
            "JOIN judgments j ON j.id = c.judgment_id WHERE c.id::text IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": sorted(set(ids))},
    )
    return {row.id: (row.content, row.canonical_uri) for row in rows}


def rank_cases(
    query: str,
    candidates: list[tuple[str, str, str]],
    texts: dict[str, tuple[str, str]],
    reranker: Reranker,
    top_k: int,
) -> list[dict[str, Any]]:
    """Cases by their best cross-encoder passage. ``candidates``: (case, chunk id, role)."""
    unique = sorted({(case, chunk, role) for case, chunk, role in candidates if chunk in texts})
    scores = reranker.score(query, [texts[chunk][0] for _, chunk, _ in unique]) if unique else []
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (case, chunk, role), score in zip(unique, scores, strict=True):
        by_case[case].append({"chunk_id": chunk, "role": role, "score": float(score)})
    ranked = []
    for case, passages in by_case.items():
        passages.sort(key=lambda p: (-p["score"], p["chunk_id"]))
        ranked.append({"case": case, "score": passages[0]["score"], "passages": passages})
    ranked.sort(key=lambda c: (-c["score"], c["case"]))
    return ranked[:top_k]


def returned_passages(
    ranked: list[dict[str, Any]], texts: dict[str, tuple[str, str]], view: GraphView
) -> list[tuple[str, str]]:
    """(source case, text) of every ranked passage, each marked with its ``source_case``.

    Evidence is judged in the case a passage comes from. An outgoing hop's citing passage
    ranks the cited case, but it is the citing case's text: labelled with the ranked case,
    a gold passage recorded in the anchor could never match."""
    out = []
    for c in ranked:
        for p in c["passages"]:
            if p["chunk_id"] in texts:
                content, uri = texts[p["chunk_id"]]
                p["source_case"] = view.group_of_uri.get(uri, uri)
                out.append((p["source_case"], content))
    return out


def b0_cases(response: SearchResponse, view: GraphView) -> list[dict[str, Any]]:
    out = []
    for case in response.cases:
        group = view.group_of_uri.get(case.judgment.canonical_uri, case.judgment.canonical_uri)
        out.append(
            {
                "case": group,
                "score": case.score,
                "passages": [
                    {"chunk_id": str(p.chunk_id), "role": "b0", "score": p.rerank_score}
                    for p in case.passages
                ],
            }
        )
    return out


# --- metrics ---------------------------------------------------------------------------


def case_metrics(ranked: list[str], gold: set[str], top_k: int) -> dict[str, Any]:
    ranks = [i for i, case in enumerate(ranked, start=1) if case in gold]
    found = {case for case in ranked[:top_k] if case in gold}
    return {
        "recall@20": len(found) / len(gold) if gold else None,
        "hit@20": bool(found),
        "first_rank": ranks[0] if ranks else None,
        "rr@10": 1 / ranks[0] if ranks and ranks[0] <= 10 else 0.0,
    }


def evidence_hit(
    passages: list[tuple[str, str]], gold_passages: list[tuple[str, str]]
) -> dict[str, Any]:
    """Gold passages (case, text) found among returned passages (case, text): the passage
    contains the gold text or lies inside it, after normalisation, in the same case."""
    if not gold_passages:
        return {"passage_recall@20": None}
    found = 0
    for gold_case, gold_text in gold_passages:
        target = normalise(gold_text)
        if any(
            case == gold_case and (target in normalise(text) or normalise(text) in target)
            for case, text in passages
        ):
            found += 1
    return {"passage_recall@20": found / len(gold_passages)}


def path_metrics(
    hops: list[tuple[Hop, str]], seeds: list[str], gold_paths: list[list[str]]
) -> dict[str, Any]:
    """Over every gold chain: node and edge recall of their union, the share of chains
    traversed completely, cases visited off every chain, and the first hop reaching one."""
    chains = [path for path in gold_paths if len(path) >= 2]
    if not chains:
        return {}
    visited = set(seeds) | {hop.case for hop, _ in hops}
    traversed = {(hop.path[-2], hop.case) for hop, _ in hops}
    nodes = {case for path in chains for case in path}
    edges = {edge for path in chains for edge in zip(path, path[1:], strict=False)}
    complete = [all(e in traversed for e in zip(p, p[1:], strict=False)) for p in chains]
    depth_of = {hop.case: hop.depth for hop, _ in hops}
    reached_gold = [depth_of[c] for path in chains for c in path[1:] if c in depth_of]
    return {
        "gold_chains": len(chains),
        "gold_node_recall": len(nodes & visited) / len(nodes),
        "gold_edge_recall": len(edges & traversed) / len(edges),
        "complete_paths": sum(complete),
        "complete_path_share": sum(complete) / len(chains),
        "unnecessary_nodes": len(visited - nodes),
        "first_relevant_hop": min(reached_gold) if reached_gold else None,
    }


# --- running ---------------------------------------------------------------------------


def run_question(
    conn: Connection,
    question: PilotQuestion,
    view: GraphView,
    settings: Settings,
    embedder: EmbeddingProvider,
    reranker: Reranker,
    config: RunConfig,
    systems: Sequence[str] = SYSTEMS,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    response = search(
        conn,
        SearchRequest(query=question.query, filters=question.filters, top_k=config.top_k),
        settings,
        embedder=embedder,
        reranker=reranker,
    )
    search_ms = (time.perf_counter() - started) * 1000
    info = response.query_info
    if info.degraded or not info.reranked or info.mode_used != "hybrid":
        raise RuntimeError(
            f"{question.id}: search is not the default ({info.mode_used}, reranked="
            f"{info.reranked}, degraded={info.degraded_reason}); not a fair comparison"
        )
    baseline = b0_cases(response, view)
    seeds = [c["case"] for c in baseline[: config.seed_k]]
    b0_candidates = [(c["case"], p["chunk_id"], "b0") for c in baseline for p in c["passages"]]
    gold = {view.group_of_uri.get(u, u) for u in question.gold_case_uris}
    gold_passages = [
        (view.group_of_uri.get(p.canonical_uri, p.canonical_uri), p.text)
        for p in question.gold_passages
    ]
    gold_paths = [[view.group_of_uri.get(u, u) for u in path] for path in question.gold_paths]
    anchors = {view.group_of_uri.get(u, u) for u in question.anchor_uris}
    # Seed recall: did B0 find the case(s) the question names? Graph expansion can only
    # start from a seed (docs/graphrag/AGENTS.md, Phase 3 graph-specific metrics).
    seed_recall = len(anchors & set(seeds)) / len(anchors) if anchors else None

    records = []
    for system in systems:
        t0 = time.perf_counter()
        directions, depth, budget = plan(system, question, config)
        hops = expand_seeds(view, seeds, directions, depth, budget, config) if directions else []
        if system == "B0":
            ranked = baseline[: config.top_k]
            texts = chunk_texts(conn, [p["chunk_id"] for c in ranked for p in c["passages"]])
        else:
            candidates = list(b0_candidates)
            for hop, direction in hops:
                candidates += [
                    (hop.case, chunk, f"citing_{direction}")
                    for chunk in hop_candidates(view, hop, direction, config)
                ]
            outgoing = sorted({hop.case for hop, d in hops if d == "outgoing"})
            nearest = nearest_chunks(conn, embedder, question.query, outgoing)
            candidates += [(case, chunk, "nearest") for case, chunk in nearest.items()]
            texts = chunk_texts(conn, [chunk for _, chunk, _ in candidates])
            # An outgoing hop's citing passage lies in the seed but ranks the reached case.
            ranked = rank_cases(question.query, candidates, texts, reranker, config.top_k)
        elapsed = (time.perf_counter() - t0) * 1000 + search_ms
        returned = returned_passages(ranked, texts, view)
        cases = [c["case"] for c in ranked]
        metrics = {
            **case_metrics(cases, gold, config.top_k),
            **evidence_hit(returned, gold_passages),
            **path_metrics(hops, seeds, gold_paths),
            "seed_recall": seed_recall,
        }
        records.append(
            {
                "id": question.id,
                "class": question.question_class,
                "direction": question.traversal_direction(),
                "provisional": question.provisional,
                "stress_test": question.stress_test,
                "system": system,
                "directions": list(directions),
                "depth": depth,
                "seeds": seeds,
                "hops": [
                    {"case": h.case, "depth": h.depth, "path": list(h.path), "direction": d}
                    for h, d in hops
                ],
                "nodes_visited": len(set(seeds) | {h.case for h, _ in hops}),
                "candidate_cases": len(
                    {c for c, _, _ in b0_candidates} | {h.case for h, _ in hops}
                ),
                "ranked": [
                    {
                        "case": c["case"],
                        "score": c["score"],
                        "passages": [
                            {
                                "chunk_id": p["chunk_id"],
                                "source_case": p.get("source_case"),
                                "role": p["role"],
                            }
                            for p in c["passages"]
                        ],
                    }
                    for c in ranked
                ],
                "gold_cases": sorted(gold),
                "latency_ms": round(elapsed, 1),
                "metrics": metrics,
            }
        )
    return records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.pilot.run")
    parser.add_argument("--file", type=Path, default=PILOT_FILE)
    parser.add_argument("--policy", default="phase2-v1")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--out-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--seed-k", type=int, default=RunConfig.seed_k)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="unlocked placeholder questions; writes artifacts/pilot_dry_run.json only",
    )
    args = parser.parse_args(argv)

    questions = [q for q in load_pilot(args.file) if not q.retired]
    if not args.dry_run:
        problems = run_problems(questions)
        if problems:
            sys.stderr.write("the question set is not ready:\n" + "\n".join(problems) + "\n")
            return 1
    config = RunConfig(seed_k=args.seed_k)
    try:
        view = load_view(args.artifacts, args.policy, args.out_dir)
    except GraphArtifactError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    settings = get_settings()
    embedder, reranker = load_providers(settings)
    if embedder is None or reranker is None:
        sys.stderr.write("the pilot needs the embedding model and the reranker\n")
        return 1
    engine = make_engine(settings)
    records: list[dict[str, Any]] = []
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            # Search runs on the live corpus and expansion on the graph's snapshot: they must
            # be the same, or old chunk ids would silently drop out of the comparison.
            changed = corpus_mismatches(view.corpus, corpus_version(conn, None))
            if changed:
                sys.stderr.write(
                    "the corpus differs from the one the graph was built from "
                    f"({', '.join(changed)}): rebuild the graph first\n"
                )
                return 1
            for question in questions:
                records += run_question(conn, question, view, settings, embedder, reranker, config)
            manifest = research_manifest(
                conn,
                kind="graphrag_pilot" if not args.dry_run else "graphrag_pilot_dry_run",
                embedder=embedder,
                query_set_hash=hashlib.sha256(args.file.read_bytes()).hexdigest(),
                graph_config={
                    **asdict(config),
                    "policy": args.policy,
                    "graph_fingerprint": view.fingerprint,
                },
                models={
                    "embedding": {
                        "model_id": embedder.model_id,
                        "revision": embedder.model_revision,
                    },
                    "reranker": {
                        "model_id": getattr(reranker, "model_id", None),
                        "revision": getattr(reranker, "model_revision", None),
                    },
                },
                notes=f"{VERSION}; systems {', '.join(SYSTEMS)}",
            )
        summary = summarise(records)
        manifest["metrics"] = summary
        if args.dry_run:
            write_json(args.artifacts / "pilot_dry_run.json", {**manifest, "records": records})
            sys.stdout.write(
                f"dry run: {len(questions)} questions -> {args.artifacts / 'pilot_dry_run.json'}\n"
            )
            return 0
        stem = f"pilot_{manifest['query_set_hash'][:12]}"
        write_json(args.out_dir / f"{stem}.json", manifest)
        (args.out_dir / f"{stem}.md").write_text(markdown(summary, manifest))
        write_json(args.artifacts / f"{stem}_records.json", {"records": records})
        # The stored row carries the report's run id, so the two can be matched.
        run_id = store_run(
            engine,
            {**manifest, "kind": "graphrag_pilot"},
            summary,
            records,
            run_id=uuid.UUID(manifest["run_id"]),
        )
    finally:
        engine.dispose()
    sys.stdout.write(
        f"pilot run {run_id}: {len(questions)} questions -> {args.out_dir / stem}.md\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
