"""Traversal over the in-memory case graph.

``CITES`` edges point from the citing (later) case to the cited (earlier) one, so:

- "what did this case rely on?" reads **outgoing** edges;
- "how was this case treated later?" reads **incoming** edges (``CITED_BY``).

Expansion is bounded: depth, total nodes, branching per node, and an optional hub limit
(a heavily cited authority is reached but not expanded, so one famous case cannot flood
the candidates). Neighbours are visited in sorted order, so results are deterministic.
"""

from collections import deque
from collections.abc import Mapping, Set
from dataclasses import dataclass

Adjacency = Mapping[str, Set[str]]


@dataclass(frozen=True)
class Hop:
    case: str
    depth: int
    path: tuple[str, ...]  # from the start case to this one, both included


def expand(
    adjacency: Adjacency,
    start: str,
    *,
    max_depth: int = 1,
    max_nodes: int = 200,
    max_branching: int = 50,
    hub_degree: int | None = None,
) -> list[Hop]:
    """Breadth-first expansion from ``start`` (not included), each case visited once."""
    hops: list[Hop] = []
    seen = {start}
    queue: deque[Hop] = deque([Hop(start, 0, (start,))])
    while queue and len(hops) < max_nodes:
        current = queue.popleft()
        if current.depth >= max_depth:
            continue
        neighbours = sorted(adjacency.get(current.case, ()))
        if hub_degree is not None and current.depth > 0 and len(neighbours) > hub_degree:
            continue  # reached, but a hub is not expanded further
        for case in neighbours[:max_branching]:
            if case in seen:
                continue
            seen.add(case)
            hop = Hop(case, current.depth + 1, (*current.path, case))
            hops.append(hop)
            if len(hops) == max_nodes:
                break
            queue.append(hop)
    return hops


def distances(adjacency: Adjacency, start: str) -> dict[str, int]:
    """Shortest directed path length from ``start`` to every case it reaches."""
    found: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    seen = {start}
    while queue:
        case, depth = queue.popleft()
        for neighbour in adjacency.get(case, ()):
            if neighbour not in seen:
                seen.add(neighbour)
                found[neighbour] = depth + 1
                queue.append((neighbour, depth + 1))
    return found
