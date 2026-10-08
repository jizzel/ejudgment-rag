"""Stable hashes and deterministic IDs, so repeated imports produce identical rows."""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

# Fixed namespace for uuid5 IDs. Never change it: every stored ID derives from it.
ID_NAMESPACE = uuid.UUID("6f1c9a52-6a5e-4c55-9a0b-2f3d0b8f4e21")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def stable_json_hash(payload: Any) -> str:
    """SHA-256 of canonical JSON (sorted keys, no whitespace variance)."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_text(encoded)


def stable_id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(ID_NAMESPACE, "\x1f".join(parts))
