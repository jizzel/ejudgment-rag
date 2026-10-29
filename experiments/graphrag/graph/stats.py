"""Phase 2 graph statistics: aggregates only, no corpus text (committable)."""

from collections import Counter, defaultdict
from typing import Any

from experiments.graphrag.graph.traverse import distances

DEGREE_BUCKETS = ((0, 0), (1, 1), (2, 2), (3, 5), (6, 10), (11, 20), (21, 50), (51, 10**9))


def _bucket(degree: int) -> str:
    for low, high in DEGREE_BUCKETS:
        if low <= degree <= high:
            return str(low) if low == high else (f"{low}+" if high >= 10**9 else f"{low}-{high}")
    raise ValueError(degree)


def _histogram(degrees: list[int]) -> dict[str, int]:
    counts = Counter(_bucket(d) for d in degrees)
    return {label: counts.get(label, 0) for label in (_bucket(low) for low, _ in DEGREE_BUCKETS)}


def _components(nodes: list[str], edges: list[tuple[str, str]]) -> list[int]:
    """Sizes of weakly connected components, largest first (union-find)."""
    parent = {node: node for node in nodes}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for source, target in edges:
        a, b = find(source), find(target)
        if a != b:
            parent[a] = b
    return sorted(Counter(find(node) for node in nodes).values(), reverse=True)


def _case_meta(node: dict[str, Any]) -> tuple[str, str]:
    judgments = node["judgments"]
    court = judgments[0]["court"] if judgments else "unknown"
    dates = sorted(j["date"] for j in judgments if j["date"])
    decade = f"{dates[0][:3]}0s" if dates else "unknown"
    return court, decade


def graph_statistics(graph: Any) -> dict[str, Any]:
    nodes = list(graph.nodes)
    edges = list(graph.edges)
    outgoing, incoming = graph.outgoing(), graph.incoming()
    occurrences = [o for occ in graph.edges.values() for o in occ]

    path_lengths: Counter[int] = Counter()
    for source in sorted(outgoing):
        path_lengths.update(distances(outgoing, source).values())
    sizes = _components(nodes, edges)

    coverage: dict[str, dict[str, dict[str, int]]] = {"court": {}, "decade": {}}
    for key in ("court", "decade"):
        table: dict[str, Counter[str]] = defaultdict(Counter)
        for case, node in graph.nodes.items():
            court, decade = _case_meta(node)
            bucket = court if key == "court" else decade
            table[bucket]["cases"] += 1
            table[bucket]["citing"] += bool(outgoing.get(case))
            table[bucket]["cited"] += bool(incoming.get(case))
        coverage[key] = {b: dict(c) for b, c in sorted(table.items())}

    def earliest(case: str) -> str | None:
        dates = sorted(j["date"] for j in graph.nodes[case]["judgments"] if j["date"])
        return dates[0] if dates else None

    forward = sum(
        1
        for source, target in edges
        if (s := earliest(source)) is not None and (t := earliest(target)) is not None and t > s
    )
    return {
        "nodes": {
            "cases": len(nodes),
            "judgments": sum(len(n["judgments"]) for n in graph.nodes.values()),
        },
        "edges": {
            "edges": len(edges),
            "occurrences": len(occurrences),
            "occurrences_by_method": dict(Counter(o["method"] for o in occurrences).most_common()),
            "occurrences_by_tier": dict(Counter(o["tier"] for o in occurrences).most_common()),
            "edges_by_method": dict(
                Counter(m for occ in graph.edges.values() for m in {o["method"] for o in occ})
            ),
            "occurrences_from_ocr_text": sum(1 for o in occurrences if o["ocr"]),
            "occurrences_per_edge_max": max((len(o) for o in graph.edges.values()), default=0),
        },
        "degree": {
            "out_histogram": _histogram([len(outgoing.get(n, ())) for n in nodes]),
            "in_histogram": _histogram([len(incoming.get(n, ())) for n in nodes]),
            "max_out": max((len(v) for v in outgoing.values()), default=0),
            "max_in": max((len(v) for v in incoming.values()), default=0),
            "in_degree_top10": sorted((len(v) for v in incoming.values()), reverse=True)[:10],
        },
        "components": {
            "weakly_connected": len(sizes),
            "with_an_edge": sum(1 for s in sizes if s > 1),
            "isolated_cases": sum(1 for s in sizes if s == 1),
            "largest": sizes[0] if sizes else 0,
            "sizes_top10": [s for s in sizes if s > 1][:10],
        },
        "paths": {
            "reachable_pairs": sum(path_lengths.values()),
            "length_histogram": {str(k): v for k, v in sorted(path_lengths.items())},
            "longest_shortest_path": max(path_lengths, default=0),
        },
        "coverage": coverage,
        "temporal": {
            "review_items": len(graph.review),
            "review_items_by_method": dict(Counter(o["method"] for o in graph.review)),
            "edges_whose_target_case_is_later": forward,
            "occurrences_without_a_target_date": sum(
                1 for o in occurrences if not o["target_date"]
            ),
            "occurrences_without_a_citing_date": sum(1 for o in occurrences if not o["date"]),
        },
    }


def markdown(stats: dict[str, Any], manifest: dict[str, Any]) -> str:
    def table(values: dict[str, Any], label: str) -> list[str]:
        return [
            f"| {label} | Count |",
            "|---|---:|",
            *(f"| {k} | {v:,} |" for k, v in values.items()),
        ]

    policy = manifest["policy"]
    edges, degree, comp, paths, temporal = (
        stats["edges"],
        stats["degree"],
        stats["components"],
        stats["paths"],
        stats["temporal"],
    )
    out = [
        f"# Citation graph `{policy['name']}`",
        "",
        f"Built by `{manifest['graph_builder_version']}` from profile `{policy['source_build']}` "
        f"(audit `{policy['audit_sheet']}`), git `{manifest['git_sha'][:10]}`"
        f"{', dirty tree' if manifest['git_dirty'] else ''}. Fingerprint "
        f"`{manifest['graph_fingerprint']}`.",
        "",
        f"Admitted methods: {', '.join(f'`{m}`' for m in policy['methods'])}. "
        "An edge means a passage of the citing case contains a reference the resolver linked "
        "to the cited case; it says nothing about how the authority was treated.",
        "",
        f"**{stats['nodes']['cases']:,} cases** ({stats['nodes']['judgments']:,} judgments), "
        f"**{edges['edges']:,} edges** from {edges['occurrences']:,} occurrences "
        f"({edges['occurrences_from_ocr_text']:,} from OCR text).",
        "",
        *table(edges["occurrences_by_method"], "Occurrences by method"),
        "",
        "## Degree",
        "",
        "| Degree | Cases by out-degree (cites) | Cases by in-degree (cited by) |",
        "|---|---:|---:|",
        *(
            f"| {k} | {degree['out_histogram'][k]:,} | {degree['in_histogram'][k]:,} |"
            for k in degree["out_histogram"]
        ),
        "",
        f"Largest out-degree {degree['max_out']}, in-degree {degree['max_in']}; top in-degrees "
        f"{degree['in_degree_top10']}.",
        "",
        "## Components and paths",
        "",
        f"{comp['weakly_connected']:,} weakly connected components: {comp['with_an_edge']:,} "
        f"with an edge, {comp['isolated_cases']:,} isolated cases. Largest component "
        f"{comp['largest']:,} cases; next sizes {comp['sizes_top10'][1:]}.",
        "",
        f"{paths['reachable_pairs']:,} ordered pairs (A reaches B along `CITES`); longest "
        f"shortest path {paths['longest_shortest_path']}.",
        "",
        *table(paths["length_histogram"], "Shortest path length"),
        "",
        "## Coverage",
        "",
        "| Court | Cases | Citing a corpus case | Cited by a corpus case |",
        "|---|---:|---:|---:|",
        *(
            f"| {k} | {v['cases']:,} | {v.get('citing', 0):,} | {v.get('cited', 0):,} |"
            for k, v in stats["coverage"]["court"].items()
        ),
        "",
        "| Decade (case's earliest date) | Cases | Citing | Cited |",
        "|---|---:|---:|---:|",
        *(
            f"| {k} | {v['cases']:,} | {v.get('citing', 0):,} | {v.get('cited', 0):,} |"
            for k, v in stats["coverage"]["decade"].items()
        ),
        "",
        "## Temporal",
        "",
        f"- Review items (admitted methods, target dated after the citing case; not edges): "
        f"{temporal['review_items']:,} {temporal['review_items_by_method']}.",
        f"- Edges whose cited case is dated after the citing case: "
        f"{temporal['edges_whose_target_case_is_later']}.",
        f"- Occurrences without a target date: {temporal['occurrences_without_a_target_date']}; "
        f"without a citing date: {temporal['occurrences_without_a_citing_date']}.",
        "",
    ]
    return "\n".join(out)
