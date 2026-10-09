import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnswerView } from "@/components/AnswerView";
import { Attribution } from "@/components/Attribution";
import { CaseCard } from "@/components/CaseCard";
import { PageBadge } from "@/components/PageBadge";
import { PassageView } from "@/components/PassageView";
import { ATTRIBUTION, NOTICE } from "@/lib/notices";

import { abstained, answered, caseResult, passageContext } from "./fixtures";

describe("page badge", () => {
  it("shows a pinpoint only for verified pages", () => {
    const { rerender } = render(<PageBadge status="verified" start={0} end={1} />);
    expect(screen.getByText("PDF pp. 1–2")).toBeTruthy();
    rerender(<PageBadge status="pending" start={0} end={1} />);
    expect(screen.queryByText(/PDF/)).toBeNull();
    expect(screen.getByText("No verified page")).toBeTruthy();
  });
});

describe("search result", () => {
  it("renders untrusted text as text, highlights terms and links the source", () => {
    const { container } = render(<CaseCard result={caseResult} query="landlord possession" />);
    expect(container.querySelector("img")).toBeNull(); // no HTML injection
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    expect([...container.querySelectorAll("mark")].map((m) => m.textContent)).toEqual([
      "landlord",
      "possession",
    ]);
    const ghalii = screen.getByRole("link", { name: "Original on GhaLII" });
    expect(ghalii.getAttribute("href")).toBe(caseResult.judgment.source_url);
    expect(ghalii.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getByText("PDF pp. 5–6")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Read in context" }).getAttribute("href")).toBe(
      `/passages/${caseResult.passages[0].chunk_id}`,
    );
  });
});

describe("answer", () => {
  it("links each claim to its numbered source and its quote in context", () => {
    render(<AnswerView response={answered} />);
    const marker = screen.getByRole("link", { name: "Source 1" });
    expect(marker.getAttribute("href")).toBe("#source-1");
    expect(document.getElementById("source-1")?.textContent).toContain(answered.sources[0].judgment.citation);
    const quote = screen.getByRole("link", { name: "See the quote in context" });
    expect(quote.getAttribute("href")).toBe(
      "/passages/22222222-2222-5222-8222-222222222222?quote=entitled%20to%20recover%20possession",
    );
    expect(screen.getByText("PDF pages 5-6")).toBeTruthy(); // the server's pinpoint
    expect(screen.getByText("Holding")).toBeTruthy();
    expect(screen.getByText("Model-written, not verified")).toBeTruthy();
    expect(screen.getByText(answered.attribution)).toBeTruthy();
  });

  it("shows no pinpoint the server did not give", () => {
    const unpaged = { ...answered, claims: [{ ...answered.claims[0], pinpoint: null }] };
    render(<AnswerView response={unpaged} />);
    expect(screen.queryByText(/PDF pages/)).toBeNull();
  });

  it("an abstention says why and lists cases to check", () => {
    render(<AnswerView response={abstained} />);
    const panel = screen.getByRole("status");
    expect(within(panel).getByText("No answer")).toBeTruthy();
    expect(within(panel).getByText("The passages found do not answer this question.")).toBeTruthy();
    expect(within(panel).getByText(abstained.matched_cases[0].citation)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Answer" })).toBeNull();
  });
});

describe("passage viewer", () => {
  it("shows the passage in context with the quote marked and attribution", () => {
    const { container } = render(
      <PassageView context={passageContext} quote="entitled to recover possession" />,
    );
    expect(container.querySelector("mark")?.textContent).toBe("entitled to\nrecover possession");
    expect(screen.getByText("The facts are these.")).toBeTruthy();
    expect(container.querySelector('[aria-current="true"]')?.textContent).toContain("Passage 4");
    expect(screen.getByText(passageContext.attribution)).toBeTruthy();
    expect(screen.getAllByText("No verified page").length).toBe(2);
  });
});

it("the site-wide attribution is the API's own and credits GhaLII", () => {
  render(<Attribution />);
  expect(ATTRIBUTION).toContain("GhaLII");
  expect(ATTRIBUTION).toContain("CC BY-NC 4.0");
  expect(screen.getByText(NOTICE)).toBeTruthy();
});
