import type { Attempt } from "./errors";
import type { ChatResponse, PassageContext } from "./types";

/** What an evidence panel shows. */
export type Evidence =
  | { kind: "none" }
  | { kind: "loading"; chunkId: string }
  | { kind: "shown"; chunkId: string; context: PassageContext }
  | { kind: "error"; chunkId: string; code: string; message: string };

/**
 * The panel's starting state for a search URL: the passage it names, or why that passage
 * could not be shown (a stale or unavailable shared link is said so, never shown as no
 * selection). Plain data, so the server can hand it to the client workspace.
 */
export function restoredEvidence(chunkId: string | null, result: Attempt<PassageContext> | null): Evidence {
  if (!chunkId || !result) return { kind: "none" };
  if (result.ok) return { kind: "shown", chunkId, context: result.value };
  return { kind: "error", chunkId, code: result.error.code, message: result.error.message };
}

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
