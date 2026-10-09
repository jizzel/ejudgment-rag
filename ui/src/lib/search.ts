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

/**
 * A year filter: empty means "no filter"; anything else must be a 4-digit year in the API's
 * range. A malformed value is an error, never dropped (that would silently widen a search).
 */
export function parseYear(name: string, raw: string | undefined): number | null | ApiError {
  const text = raw?.trim();
  if (!text) return null;
  const value = /^\d{4}$/.test(text) ? Number(text) : Number.NaN;
  if (!(value >= 1900 && value <= 2100)) {
    return new ApiError(422, "invalid_filter", `${name} must be a year between 1900 and 2100`);
  }
  return value;
}

/** Both year filters, checked together (from must not be after to). */
export function parseYears(
  yearFrom: string | undefined,
  yearTo: string | undefined,
): { year_from: number | null; year_to: number | null } | ApiError {
  const from = parseYear("From year", yearFrom);
  if (from instanceof ApiError) return from;
  const to = parseYear("To year", yearTo);
  if (to instanceof ApiError) return to;
  if (from !== null && to !== null && from > to) {
    return new ApiError(422, "invalid_filter", "From year must not be after To year");
  }
  return { year_from: from, year_to: to };
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
  if (years instanceof ApiError) return { ok: false, error: years };
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
    if (text && key !== "page") query.set(key, text);
  }
  query.set("page", String(page));
  return `/?${query.toString()}`;
}
