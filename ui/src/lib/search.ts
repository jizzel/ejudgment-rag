import { safeNext } from "./auth";
import { ApiError } from "./errors";
import type { SearchRequest } from "./types";

export type Params = Record<string, string | string[] | undefined>;

export const PAGE_SIZE = 10;
/** The API serves at most search_max_depth (150) cases per query. */
export const MAX_DEPTH = 150;

function one(value: string | string[] | undefined): string | undefined {
  const text = (Array.isArray(value) ? value[0] : value)?.trim();
  return text ? text : undefined;
}

/** Query length the API accepts (SearchRequest.query). */
export const MAX_QUERY_LENGTH = 1000;

export type FilterField = "year_from" | "year_to";

/** A filter the user entered that can't be used; shown next to its field. */
export class FilterError extends ApiError {
  constructor(
    readonly field: FilterField,
    message: string,
  ) {
    super(422, "invalid_filter", message);
    this.name = "FilterError";
  }
}

/**
 * A year filter: empty means "no filter"; anything else must be a 4-digit year in the API's
 * range. A malformed value is an error, never dropped (that would silently widen a search).
 */
export function parseYear(field: FilterField, raw: string | undefined): number | null | FilterError {
  const name = field === "year_from" ? "From year" : "To year";
  const text = raw?.trim();
  if (!text) return null;
  const value = /^\d{4}$/.test(text) ? Number(text) : Number.NaN;
  if (!(value >= 1900 && value <= 2100)) {
    return new FilterError(field, `${name} must be a year between 1900 and 2100.`);
  }
  return value;
}

/** Both year filters, checked together (the end year must not be before the start year). */
export function parseYears(
  yearFrom: string | undefined,
  yearTo: string | undefined,
): { year_from: number | null; year_to: number | null } | FilterError {
  const from = parseYear("year_from", yearFrom);
  if (from instanceof FilterError) return from;
  const to = parseYear("year_to", yearTo);
  if (to instanceof FilterError) return to;
  if (from !== null && to !== null && from > to) {
    return new FilterError("year_to", `To year must be ${from} or later.`);
  }
  return { year_from: from, year_to: to };
}

/** Example searches for the starting screen (from the seed gold set's categories). */
export const EXAMPLES = [
  { label: "A citation", q: "[2021] GHACA 29" },
  { label: "A case name", q: "Ntim v Opare" },
  { label: "A legal issue", q: "Who must prove that the signatures on a will were forged?" },
  { label: "A fact pattern", q: "Tenant locked out by the landlord over unpaid rent" },
] as const;

/** The URL of this search with a passage opened beside the results (or closed with null);
 * the query, filters and page are kept. */
export function withPassage(params: Params, chunkId: string | null): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    const text = one(value);
    if (text && key !== "passage") query.set(key, text);
  }
  if (chunkId) query.set("passage", chunkId);
  const text = query.toString();
  return text ? `/?${text}` : "/";
}

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The passage a search URL opens, if it names a well-formed one. */
export function openPassage(params: Params): string | null {
  const id = one(params.passage);
  return id && UUID.test(id) ? id : null;
}

export type BuiltSearch =
  | { ok: true; request: SearchRequest; page: number }
  | { ok: false; error: ApiError };

/**
 * The search request a URL describes; null when there is no query. Invalid filters or an
 * over-long query are errors to show, never quietly dropped or cut.
 */
export function buildSearchRequest(params: Params): BuiltSearch | null {
  const query = one(params.q);
  if (!query) return null;
  if (query.length > MAX_QUERY_LENGTH) {
    return {
      ok: false,
      error: new ApiError(422, "invalid_request", `Queries are limited to ${MAX_QUERY_LENGTH} characters`),
    };
  }
  const years = parseYears(one(params.year_from), one(params.year_to));
  if (years instanceof FilterError) return { ok: false, error: years };
  const requested = Number(one(params.page) ?? "1");
  const page = Number.isInteger(requested) && requested > 0 ? requested : 1;
  const lastPage = Math.floor(MAX_DEPTH / PAGE_SIZE);
  const safePage = Math.min(page, lastPage);
  const mode = one(params.mode);
  return {
    ok: true,
    page: safePage,
    request: {
      query,
      top_k: PAGE_SIZE,
      offset: (safePage - 1) * PAGE_SIZE,
      mode: mode === "lexical" || mode === "dense" ? mode : "hybrid",
      rerank: true,
      filters: {
        court: one(params.court) ?? null,
        ...years,
        judge: one(params.judge) ?? null,
      },
    },
  };
}

/** The URL of another results page, or null beyond the API's depth limit. */
export function pageHref(params: Params, page: number): string | null {
  if (page < 1 || page * PAGE_SIZE > MAX_DEPTH) return null;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    const text = one(value);
    if (text && key !== "page" && key !== "passage") query.set(key, text);
  }
  query.set("page", String(page));
  return `/?${query.toString()}`;
}

/** Where a passage page's "Back to results" goes: a same-site path only (never sign-in). */
export function backTarget(from: string | string[] | undefined): string | null {
  if (typeof from !== "string") return null;
  const target = safeNext(from);
  return target === "/" && from !== "/" ? null : target;
}
