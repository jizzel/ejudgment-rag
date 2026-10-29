"""Phase 1: find and resolve every case reference in the corpus, read-only.

    poetry run python -m experiments.graphrag.coverage.profile_mentions [--limit N]

Writes ``artifacts/mentions_<build>.jsonl`` (one line per reference, with a short context
window: corpus text, so gitignored) and ``artifacts/mentions_<build>.meta.json`` (the
manifest and the chunk counts the coverage rates are measured against).
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from experiments.graphrag.extraction.mentions import (
    EXTRACTOR_VERSIONS,
    Reference,
    evidence_span,
    find_references,
)
from experiments.graphrag.manifest import ARTIFACTS_DIR, research_manifest, write_json
from experiments.graphrag.resolution.index import CorpusIndex, load_index
from experiments.graphrag.resolution.resolve import VERSION as RESOLVER_VERSION
from experiments.graphrag.resolution.resolve import Source, resolve, target_date

VERSIONS = {**EXTRACTOR_VERSIONS, "resolver": RESOLVER_VERSION}
CONTEXT_CHARS = 200


@dataclass(frozen=True)
class SourceInfo:
    method: str  # extraction method of the chunked source's pages
    ocr_confidence: float | None  # mean Tesseract word confidence; not a semantic confidence


@dataclass(frozen=True)
class ChunkRow:
    id: str
    ordinal: int
    judgment_id: str
    group: str
    char_start: int
    content: str
    source_id: str
    page_reference_status: str


def decade(value: date | None) -> str:
    return f"{value.year // 10 * 10}s" if value else "unknown"


def source_info(conn: Connection) -> dict[str, SourceInfo]:
    rows = conn.execute(
        text(
            "SELECT source_id::text AS id, "
            "CASE WHEN count(DISTINCT extraction_method) = 1 THEN min(extraction_method) "
            "ELSE 'mixed' END AS method, avg(ocr_confidence) AS conf "
            "FROM document_pages GROUP BY source_id"
        )
    )
    return {
        row.id: SourceInfo(row.method, round(float(row.conf), 1) if row.conf is not None else None)
        for row in rows
    }


def chunk_rows(conn: Connection, limit: int | None) -> Iterator[ChunkRow]:
    sql = (
        "SELECT c.id::text AS id, c.ordinal, c.judgment_id::text AS judgment_id, "
        "c.source_text_hash, c.char_start, c.content, c.source_id::text AS source_id, "
        "c.page_reference_status FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
        "WHERE j.eligibility_status = 'eligible' ORDER BY c.judgment_id, c.ordinal"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    # Streamed with a server-side cursor; the option is set on this statement only
    # (Connection.execution_options would change the whole connection in place).
    result = conn.execute(text(sql).execution_options(stream_results=True, yield_per=1000))
    for row in result:
        yield ChunkRow(
            id=row.id,
            ordinal=row.ordinal,
            judgment_id=row.judgment_id,
            group=row.source_text_hash,
            char_start=row.char_start,
            content=row.content,
            source_id=row.source_id,
            page_reference_status=row.page_reference_status,
        )


def reference_record(
    index: CorpusIndex, chunk: ChunkRow, info: SourceInfo, reference: Reference
) -> dict[str, Any]:
    source = index.judgments[chunk.judgment_id]
    citing = Source(
        group=chunk.group,
        # The case's earliest copy, so every re-publication gets the same temporal answer.
        date=index.group_date(chunk.group),
        identifiers=index.identifiers[chunk.judgment_id],
        offset=chunk.char_start + reference.start,
        judgment_id=chunk.judgment_id,
    )
    result = resolve(index, reference, citing)
    evidence_start, evidence_end = evidence_span(chunk.content, reference.start, reference.end)
    targets = sorted((index.judgments[jid] for jid in result.target_ids), key=lambda j: j.uri)
    target = target_date(index, result)
    content = chunk.content
    name = reference.name
    return {
        "chunk_id": chunk.id,
        "ordinal": chunk.ordinal,
        "judgment_id": source.id,
        "uri": source.uri,
        "citation": source.citation,
        "court": source.court,
        "date": source.date.isoformat() if source.date else None,
        "decade": decade(source.date),
        "group": chunk.group,
        "source_method": info.method,
        "ocr": info.method == "ocr",
        "ocr_confidence": info.ocr_confidence,
        "page_reference_status": chunk.page_reference_status,
        "start": reference.start,
        "end": reference.end,
        "source_start": chunk.char_start + reference.start,
        "source_end": chunk.char_start + reference.end,
        "text": content[reference.start : reference.end],
        "context_before": content[max(0, reference.start - CONTEXT_CHARS) : reference.start],
        "context_after": content[reference.end : reference.end + CONTEXT_CHARS],
        # The sentence that holds the reference: what an edge points to as its evidence.
        "evidence_start": evidence_start,
        "evidence_end": evidence_end,
        "evidence": content[evidence_start:evidence_end],
        "identifiers": sorted(reference.identifiers),
        "stages": sorted(reference.stages),
        "decision_date": reference.decision_date.isoformat() if reference.decision_date else None,
        "caption_marker": reference.caption_marker,
        "cue_before": reference.cue_before,
        "kind": reference.kind,
        "name": (
            {
                "text": name.text,
                "left_word": name.left_word,
                "right_word": name.right_word,
                "right_anchor": name.right_anchor,
                "ex_parte_word": name.ex_parte_word,
            }
            if name
            else None
        ),
        "citations": [
            {"kind": c.kind, "key": c.key, "token": c.token, "text": c.text}
            for c in reference.citations
        ],
        "status": result.status,
        "method": result.method,
        "tier": result.tier,
        "reason": result.reason,
        "candidates": result.candidates,
        "name_agrees": result.name_agrees,
        "foreign": result.foreign,
        "pre_temporal_status": result.pre_temporal_status,
        "target_group": result.target_group,
        "target_ids": [j.id for j in targets],
        "target_uris": [j.uri for j in targets],
        "target_citation": targets[0].citation if targets else None,
        "target_date": target.isoformat() if target else None,
    }


def profile(conn: Connection, out: Path, limit: int | None = None) -> dict[str, Any]:
    """Profiles every eligible chunk into ``out``; returns the meta record (also written)."""
    conn.execute(text("SET TRANSACTION READ ONLY"))
    index = load_index(conn)
    sources = source_info(conn)
    chunks: Counter[str] = Counter()
    by_court: Counter[str] = Counter()
    by_decade: Counter[str] = Counter()
    by_method: Counter[str] = Counter()
    judgments: set[str] = set()
    references = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as handle:
        for chunk in chunk_rows(conn, limit):
            source = index.judgments[chunk.judgment_id]
            info = sources.get(chunk.source_id, SourceInfo("unknown", None))
            chunks["all"] += 1
            by_court[source.court] += 1
            by_decade[decade(source.date)] += 1
            by_method[info.method] += 1
            judgments.add(chunk.judgment_id)
            for reference in find_references(chunk.content):
                record = reference_record(index, chunk, info, reference)
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                references += 1
    manifest = research_manifest(
        conn,
        kind="graphrag_coverage",
        versions=VERSIONS,
        graph_config={"limit": limit},
        notes="Phase 1 citation and case-reference coverage profile (read-only).",
    )
    meta = {
        "manifest": manifest,
        "denominators": {
            "chunks": chunks["all"],
            "judgments": len(judgments),
            "cases": len({index.judgments[j].group for j in judgments}),
            "chunks_by_court": dict(by_court),
            "chunks_by_decade": dict(by_decade),
            "chunks_by_source_method": dict(by_method),
        },
        "references": references,
        "mentions_file": out.name,
    }
    return meta


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.coverage.profile_mentions")
    parser.add_argument("--limit", type=int, default=None, help="profile only the first N chunks")
    parser.add_argument("--out-dir", type=Path, default=ARTIFACTS_DIR)
    args = parser.parse_args(argv)

    engine = make_engine(get_settings())
    staging = args.out_dir / "mentions_staging.jsonl"
    try:
        with engine.connect() as conn, conn.begin():
            meta = profile(conn, staging, args.limit)
    finally:
        engine.dispose()
    build = meta["manifest"]["graph_build_id"]
    out = args.out_dir / f"mentions_{build}.jsonl"
    staging.replace(out)
    meta["mentions_file"] = out.name
    write_json(args.out_dir / f"mentions_{build}.meta.json", meta)
    sys.stdout.write(
        f"build {build}: {meta['references']} references in {meta['denominators']['chunks']} "
        f"chunks -> {out}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
