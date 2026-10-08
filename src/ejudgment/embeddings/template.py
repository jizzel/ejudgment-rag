"""The exact text sent to the embedding model for a chunk (template ``ctx-v1``).

Case, court and year context is prepended so passages carry where they come from; the
chunk text itself is never altered or cut. If context + content would exceed the model's
input limit, the context is shortened token by token instead.
"""

from dataclasses import dataclass
from datetime import date

from ejudgment.ingestion.hashing import sha256_text
from ejudgment.ingestion.tokenizer import Tokenizer

TEMPLATE_VERSION = "ctx-v1"
# [CLS] and [SEP] for BERT-style encoders.
SPECIAL_TOKENS = 2


@dataclass(frozen=True)
class EmbeddingInput:
    text: str
    input_hash: str


def context_prefix(
    title: str | None, court_name: str | None, judgment_date: date | None, section: str | None
) -> str:
    parts = [part for part in (title, court_name) if part]
    if judgment_date is not None:
        parts.append(str(judgment_date.year))
    header = " | ".join(parts)
    return "\n".join(part for part in (header, section) if part)


def build_input(
    content: str,
    *,
    title: str | None,
    court_name: str | None,
    judgment_date: date | None,
    section: str | None,
    tokenizer: Tokenizer,
    max_tokens: int,
) -> EmbeddingInput:
    prefix = context_prefix(title, court_name, judgment_date, section)
    content_tokens, prefix_tokens = tokenizer.count([content, prefix])
    budget = max_tokens - SPECIAL_TOKENS - content_tokens
    if content_tokens + SPECIAL_TOKENS > max_tokens:
        raise ValueError(f"chunk has {content_tokens} tokens; the model accepts {max_tokens}")
    if prefix and prefix_tokens + 1 > budget:  # +1 for the separator
        offsets = tokenizer.offsets(prefix)
        keep = max(budget - 1, 0)
        prefix = prefix[: offsets[keep - 1][1]].rstrip() if keep else ""
    text = f"{prefix}\n\n{content}" if prefix else content
    return EmbeddingInput(text=text, input_hash=sha256_text(f"{TEMPLATE_VERSION}\x1f{text}"))
