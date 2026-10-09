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
    [{ year_from: "2020", year_to: "2010" }, "must not be after"],
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
