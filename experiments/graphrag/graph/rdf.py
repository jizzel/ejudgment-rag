"""RDF/Turtle export of the citation graph: a rights-safe *representation* of the same
evidence graph, never a second source of truth.

**Identity.** A judgment is its AKN expression URI as GhaLII publishes it
(``https://ghalii.org/akn/gh/judgment/ghasc/2012/8/eng@2012-02-22``). Cases (groups of
re-publications) and chunks get IRIs in this project's namespace (``ejg-case:``,
``ejg-chunk:``), because they are this project's constructs.

**Predicates, chosen deliberately.**
- ``cito:cites`` (CiTO, http://purl.org/spar/cito/) is the *generic* citation relation: it
  makes no claim about agreement, reliance or treatment, which is what a ``CITES`` edge
  asserts. No more specific CiTO property is used.
- Each occurrence is an explicit ``cito:Citation`` node (``cito:hasCitingEntity``,
  ``cito:hasCitedEntity``, ``cito:hasCitationCharacterization cito:cites``): CiTO's own
  n-ary pattern for a citation as a first-class entity. Provenance hangs on that node, so
  this export uses **neither RDF reification nor RDF-star**.
- ``prov:wasDerivedFrom`` points from the citation to its chunk, ``prov:wasGeneratedBy``
  to the build activity; ``dcterms:isPartOf`` places a chunk in its judgment and a judgment
  in its case.
- Offsets, hashes, method, tier and status are this project's own properties (``ejg:``);
  no equivalence with other vocabularies is claimed.
- A direct ``<citing judgment> cito:cites <cited judgment>`` triple is also written for
  plain queries; it is derived from, and justified only by, the citation nodes.

**Rights.** No corpus text: no passages, quotes or titles, only identifiers, offsets,
SHA-256 hashes of the reference and evidence text, and method metadata.
"""

import hashlib
from pathlib import Path
from typing import Any

NAMESPACE = "https://github.com/jizzel/ejudgment-rag/ns/graphrag#"
GHALII = "https://ghalii.org"
PREFIXES = {
    "cito": "http://purl.org/spar/cito/",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "ejg": NAMESPACE,
    "ejg-case": "https://github.com/jizzel/ejudgment-rag/ns/case/",
    "ejg-chunk": "https://github.com/jizzel/ejudgment-rag/ns/chunk/",
    "ejg-citation": "https://github.com/jizzel/ejudgment-rag/ns/citation/",
    "ejg-build": "https://github.com/jizzel/ejudgment-rag/ns/build/",
}
RDF_SCHEMA_VERSION = "graphrag-rdf-v1"


def iri(value: str) -> str:
    """An absolute IRI in angle brackets; characters Turtle forbids are percent-encoded."""
    safe = "".join(c if c not in '<>"{}|\\^`' and c > " " else f"%{ord(c):02X}" for c in value)
    return f"<{safe}>"


def judgment_iri(canonical_uri: str) -> str:
    return iri(GHALII + canonical_uri)


def literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f'"{value}"^^xsd:decimal'
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def sha256(text: str | None) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


def citation_id(occurrence: dict[str, Any]) -> str:
    key = f"{occurrence['chunk_id']}:{occurrence['start']}:{occurrence['end']}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _block(subject: str, pairs: list[tuple[str, str]]) -> str:
    body = " ;\n    ".join(f"{p} {o}" for p, o in pairs)
    return f"{subject}\n    {body} .\n"


def turtle(graph: Any, fingerprint: str, profile: dict[str, Any]) -> str:
    build = f"ejg-build:{fingerprint[:24]}"
    out = [f"@prefix {p}: <{u}> ." for p, u in PREFIXES.items()]
    out.append("")
    policy = graph.policy.describe()
    out.append(
        _block(
            build,
            [
                ("a", "prov:Activity"),
                ("ejg:graphFingerprint", literal(fingerprint)),
                ("ejg:admissionPolicy", literal(policy["name"])),
                ("ejg:sourceBuild", literal(policy["source_build"])),
                ("ejg:rdfSchemaVersion", literal(RDF_SCHEMA_VERSION)),
                ("ejg:gitSha", literal(profile.get("git_sha", ""))),
                *(
                    ("ejg:extractorVersion", literal(v))
                    for v in sorted(
                        {
                            **profile.get("mention_extractor_versions", {}),
                            **profile.get("resolver_versions", {}),
                        }.values()
                    )
                ),
                *(("ejg:admittedMethod", literal(m)) for m in policy["methods"]),
            ],
        )
    )
    uri_of: dict[str, str] = {}
    for case, node in sorted(graph.nodes.items()):
        for judgment in node["judgments"]:
            uri_of[judgment["id"]] = judgment["uri"]
            out.append(
                _block(
                    judgment_iri(judgment["uri"]),
                    [("a", "ejg:Judgment"), ("dcterms:isPartOf", f"ejg-case:{case}")],
                )
            )
    direct: set[tuple[str, str]] = set()
    chunks: set[str] = set()
    for _, occurrences in sorted(graph.edges.items()):
        for occ in occurrences:
            citing = judgment_iri(occ["uri"])
            cited = [judgment_iri(uri_of[t]) for t in occ["target_ids"]]
            direct.update((citing, c) for c in cited)
            chunk = f"ejg-chunk:{occ['chunk_id']}"
            if chunk not in chunks:
                chunks.add(chunk)
                out.append(_block(chunk, [("dcterms:isPartOf", citing)]))
            pairs = [
                ("a", "cito:Citation"),
                ("cito:hasCitingEntity", citing),
                *(("cito:hasCitedEntity", c) for c in cited),
                ("cito:hasCitationCharacterization", "cito:cites"),
                ("prov:wasDerivedFrom", chunk),
                ("prov:wasGeneratedBy", build),
                ("ejg:charStart", literal(occ["source_start"])),
                ("ejg:charEnd", literal(occ["source_end"])),
                ("ejg:evidenceStart", literal(occ["evidence_start"])),
                ("ejg:evidenceEnd", literal(occ["evidence_end"])),
                ("ejg:referenceSha256", literal(sha256(occ["text"]))),
                ("ejg:evidenceSha256", literal(sha256(occ["evidence"]))),
                ("ejg:resolutionMethod", literal(occ["method"])),
                ("ejg:evidenceTier", literal(occ["tier"])),
                ("ejg:resolutionStatus", literal(occ["status"])),
                ("ejg:extractionMethod", literal(occ["source_method"])),
                ("ejg:fromOcrText", literal(bool(occ["ocr"]))),
            ]
            out.append(_block(f"ejg-citation:{citation_id(occ)}", pairs))
    for citing_iri, cited_iri in sorted(direct):
        out.append(f"{citing_iri} cito:cites {cited_iri} .")
    out.append("")
    return "\n".join(out)


def write_turtle(path: Path, graph: Any, fingerprint: str, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(turtle(graph, fingerprint, profile))
