import { describe, expect, it } from "vitest";

import { buildSearchRequest, MAX_DEPTH, pageHref, PAGE_SIZE, parseYears } from "@/lib/search";

describe("search URLs", () => {
  it("builds the API request from the URL", () => {
    const built = buildSearchRequest({
      q: "  adverse possession ",
      court: "ghasc",
      year_from: "2015",
      year_to: " 2020 ",
      page: "3",
      mode: "dense",
    });
    expect(built).toMatchObject({
      ok: true,
      page: 3,
      request: {
        query: "adverse possession",
        top_k: PAGE_SIZE,
        offset: 20,
        mode: "dense",
        filters: { court: "ghasc", year_from: 2015, year_to: 2020, judge: null },
      },
    });
  });

  it("needs a query, and stays within the API's depth", () => {
    expect(buildSearchRequest({ q: "  " })).toBeNull();
    const deep = buildSearchRequest({ q: "x", page: "999" });
    expect(deep?.ok && deep.request.offset).toBe(MAX_DEPTH - PAGE_SIZE);
    const odd = buildSearchRequest({ q: "x", page: "-2", mode: "evil" });
    expect(odd).toMatchObject({ ok: true, request: { offset: 0, mode: "hybrid" } });
    expect(pageHref({ q: "x" }, MAX_DEPTH / PAGE_SIZE + 1)).toBeNull();
    expect(pageHref({ q: "a b", court: "ghasc", page: "1" }, 2)).toBe("/?q=a+b&court=ghasc&page=2");
  });

  it.each([
    [{ year_to: "20x5" }, "To year must be a year"],
    [{ year_from: "15" }, "From year must be a year"],
    [{ year_from: "2015.5" }, "From year must be a year"],
    [{ year_to: "1800" }, "To year must be a year"],
    [{ year_from: "2020", year_to: "2010" }, "To year must be 2020 or later."],
  ])("rejects malformed year filters %o instead of widening the search", (years, message) => {
    const built = buildSearchRequest({ q: "lease", ...years });
    expect(built?.ok).toBe(false);
    expect(built && !built.ok && built.error.code).toBe("invalid_filter");
    expect(built && !built.ok && built.error.message).toContain(message);
  });

  it("treats empty year fields as no filter", () => {
    expect(parseYears("", "  ")).toEqual({ year_from: null, year_to: null });
    expect(parseYears(undefined, "1999")).toEqual({ year_from: null, year_to: 1999 });
  });

  it("rejects an over-long query instead of cutting it", () => {
    const built = buildSearchRequest({ q: "a".repeat(1001) });
    expect(built && !built.ok && built.error.code).toBe("invalid_request");
    expect(buildSearchRequest({ q: "a".repeat(1000) })?.ok).toBe(true);
  });
});

describe("research continuity", () => {
  it("opens and closes a passage without losing the query, filters or page", async () => {
    const { withPassage, openPassage } = await import("@/lib/search");
    const params = { q: "a b", court: "ghasc", year_from: "2015", page: "2", passage: "old" };
    const id = "22222222-2222-5222-8222-222222222222";
    expect(withPassage(params, id)).toBe(`/?q=a+b&court=ghasc&year_from=2015&page=2&passage=${id}`);
    expect(withPassage(params, null)).toBe("/?q=a+b&court=ghasc&year_from=2015&page=2");
    expect(pageHref({ ...params, passage: id }, 3)).not.toContain("passage");
    expect(openPassage({ passage: id })).toBe(id);
    expect(openPassage({ passage: "../etc" })).toBeNull();
  });

  it("goes back only to a same-site page", async () => {
    const { backTarget } = await import("@/lib/search");
    expect(backTarget("/?q=lease&court=ghasc")).toBe("/?q=lease&court=ghasc");
    expect(backTarget("/")).toBe("/");
    for (const unsafe of ["https://evil.example/", "//evil.example", "/login?next=/", undefined, ["/"]]) {
      expect(backTarget(unsafe)).toBeNull();
    }
  });

  it("names the field a year error belongs to", async () => {
    const { FilterError } = await import("@/lib/search");
    const reversed = parseYears("2020", "2010");
    expect(reversed).toBeInstanceOf(FilterError);
    expect(reversed instanceof FilterError && reversed.field).toBe("year_to");
    const malformed = parseYears("15", undefined);
    expect(malformed instanceof FilterError && malformed.field).toBe("year_from");
  });

  it("returns to the last search only when it is a search page", async () => {
    const { lastSearch } = await import("@/lib/last-search");
    expect(lastSearch("/?q=lease&passage=x")).toBe("/?q=lease&passage=x");
    for (const other of [null, "", "/review", "https://evil.example/?q=x", "//evil"]) {
      expect(lastSearch(other)).toBe("/");
    }
  });
});
