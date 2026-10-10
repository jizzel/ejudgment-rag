import type { ChatResponse } from "./types";

/** What an answer's evidence panel shows: a claim, optionally through one of its sources. */
export type ClaimSelection = {
  claim: number;
  source: number | null; // the clicked [n]; null for the claim's quote link
  chunkId: string;
  quote: string | null; // marked only when the passage is the one the quote comes from
};

/**
 * The passage to open for a claim. The quote link (source null) and a marker whose source holds
 * the quoted passage open that passage with the quote marked. Another source's marker opens
 * that source's first passage sent to the model, unmarked (the quote is not in it).
 */
export function resolveClaimSource(
  response: ChatResponse,
  claim: number,
  source: number | null,
): ClaimSelection | null {
  const item = response.claims[claim];
  if (!item) return null;
  const quoted = { claim, source, chunkId: item.quote_chunk_id, quote: item.quote };
  if (source === null) return quoted;
  const entry = response.sources.find((s) => s.number === source);
  if (!entry || entry.passages.some((p) => p.chunk_id === item.quote_chunk_id)) return quoted;
  const first = entry.passages[0];
  return first ? { claim, source, chunkId: first.chunk_id, quote: null } : quoted;
}
