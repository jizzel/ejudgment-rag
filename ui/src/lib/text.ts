/** Pure text helpers. Corpus text is untrusted: these only split strings, never build HTML. */

export type Segment = { text: string; mark: boolean };

const STOPWORDS = new Set(
  "the and for with that this from what when where which who whom how does did can could was were are has have had not into under over about upon its their there than then".split(
    " ",
  ),
);

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Significant words of a search query (3+ characters, no stopwords), longest first. */
export function queryTerms(query: string): string[] {
  const words = query.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) ?? [];
  return [...new Set(words.filter((word) => !STOPWORDS.has(word)))].sort(
    (a, b) => b.length - a.length,
  );
}

function split(text: string, pattern: RegExp | null): Segment[] {
  if (!pattern || !text) return text ? [{ text, mark: false }] : [];
  const segments: Segment[] = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (match[0].length === 0) continue;
    if (start > last) segments.push({ text: text.slice(last, start), mark: false });
    segments.push({ text: match[0], mark: true });
    last = start + match[0].length;
  }
  if (last < text.length) segments.push({ text: text.slice(last), mark: false });
  return segments;
}

/** Marks whole-word (or word-prefix) occurrences of the query's terms. */
export function highlightTerms(text: string, query: string): Segment[] {
  const terms = queryTerms(query);
  if (terms.length === 0) return split(text, null);
  const pattern = new RegExp(`\\b(?:${terms.map(escapeRegExp).join("|")})\\w*`, "giu");
  return split(text, pattern);
}

/** Marks a quote inside a passage, tolerating different whitespace and line breaks. */
export function highlightQuote(text: string, quote: string): Segment[] {
  const words = quote
    .replace(/[“”"‘’']/g, " ")
    .split(/\s+/)
    .map((word) => word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, ""))
    .filter(Boolean);
  if (words.length === 0) return split(text, null);
  const pattern = new RegExp(words.map(escapeRegExp).join("[\\s\\S]{0,3}?\\s*"), "giu");
  return split(text, pattern);
}

/**
 * A page reference for display, only for verified pages. Pages are stored as 0-based
 * physical PDF pages; people read them 1-based.
 */
export function pageLabel(
  status: string,
  start: number | null | undefined,
  end: number | null | undefined,
): string | null {
  if (status !== "verified" || start == null) return null;
  const first = start + 1;
  const last = (end ?? start) + 1;
  return first === last ? `PDF p. ${first}` : `PDF pp. ${first}–${last}`;
}

export function formatDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}
