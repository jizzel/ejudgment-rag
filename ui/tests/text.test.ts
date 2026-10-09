import { describe, expect, it } from "vitest";

import { formatDate, highlightQuote, highlightTerms, pageLabel, queryTerms } from "@/lib/text";

const marked = (segments: { text: string; mark: boolean }[]) =>
  segments.filter((s) => s.mark).map((s) => s.text);

describe("highlighting", () => {
  it("marks the query's significant words, whole-word, any case", () => {
    expect(queryTerms("What is the law on Adverse possession?")).toEqual([
      "possession",
      "adverse",
      "law",
    ]);
    const segments = highlightTerms("Possession was adverse; repossession is not.", "adverse possession");
    expect(marked(segments)).toEqual(["Possession", "adverse"]);
    expect(segments.map((s) => s.text).join("")).toBe("Possession was adverse; repossession is not.");
  });

  it("is safe with regex characters and keeps markup as plain text", () => {
    const text = "Section 118(1)(b) applies <script>alert(1)</script>";
    expect(() => highlightTerms(text, "(1)(b) [ ++ $")).not.toThrow();
    const segments = highlightTerms(text, "script section");
    expect(segments.map((s) => s.text).join("")).toBe(text);
    expect(marked(segments)).toEqual(["Section", "script", "script"]);
  });

  it("finds a quote across line breaks and typographic quotes", () => {
    const text = "The landlord was entitled to\nrecover possession of the premises.";
    expect(marked(highlightQuote(text, "“entitled to recover possession”"))).toEqual([
      "entitled to\nrecover possession",
    ]);
    expect(marked(highlightQuote(text, "not in the passage at all"))).toEqual([]);
  });
});

describe("page labels", () => {
  it("only for verified pages, shown 1-based", () => {
    expect(pageLabel("verified", 0, 0)).toBe("PDF p. 1");
    expect(pageLabel("verified", 4, 6)).toBe("PDF pp. 5–7");
    expect(pageLabel("pending", 4, 6)).toBeNull();
    expect(pageLabel("unknown", null, null)).toBeNull();
  });
});

it("formats dates without time-zone drift", () => {
  expect(formatDate("2020-02-07")).toBe("7 February 2020");
  expect(formatDate(null)).toBeNull();
});
