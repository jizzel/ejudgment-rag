/** sessionStorage key for the last search URL (so "Search" returns to it). */
export const LAST_SEARCH_KEY = "ej:last-search";

/** A stored search URL, if it is one of this site's search pages. */
export function lastSearch(stored: string | null): string {
  return stored && (stored === "/" || stored.startsWith("/?")) ? stored : "/";
}
