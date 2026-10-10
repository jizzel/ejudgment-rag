import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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
    const hrefFor = (id: string) => `/?q=landlord&passage=${id}`;
    const { container } = render(<CaseCard result={caseResult} query="landlord possession" hrefFor={hrefFor} />);
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
    expect(screen.getByRole("link", { name: "Show in context" }).getAttribute("href")).toBe(
      `/?q=landlord&passage=${caseResult.passages[0].chunk_id}`,
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
    // Model notes and provenance are folded into "Answer details", after the answer.
    const details = screen.getByText("Answer details").closest("details")!;
    expect(details.open).toBe(false);
    expect(within(details).getByText("Model-written, not verified")).toBeTruthy();
    expect(within(details).getByText(/gemma4:latest/)).toBeTruthy();
    // Attribution is the site footer's (not repeated here); every source links its original.
    expect(screen.queryByText(answered.attribution)).toBeNull();
    const source = document.getElementById("source-1")!;
    expect(within(source).getByRole("link", { name: "Original on GhaLII" }).getAttribute("href")).toBe(
      answered.sources[0].judgment.source_url,
    );
  });

  it("marks the selected claim and its sources together, and reports a selection", () => {
    const onSelect = vi.fn((_: number, __: number | null, event: { preventDefault: () => void }) =>
      event.preventDefault(),
    );
    render(<AnswerView response={answered} selectedClaim={0} onSelectClaim={onSelect} />);
    const claim = screen.getByText(answered.claims[0].text).closest("[aria-current]");
    expect(claim?.getAttribute("aria-current")).toBe("true");
    expect(document.getElementById("source-1")?.getAttribute("aria-current")).toBe("true");
    fireEvent.click(screen.getByRole("link", { name: "Source 1" }));
    fireEvent.click(screen.getByRole("link", { name: "See the quote in context" }));
    // A marker passes its own source number; the quote link passes none.
    expect(onSelect.mock.calls.map(([index, source]) => [index, source])).toEqual([[0, 1], [0, null]]);
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
    expect(screen.queryByRole("link", { name: "← Back to results" })).toBeNull();
  });

  it("leads with the selected passage; neighbouring text is folded until asked for", () => {
    const { container } = render(<PassageView context={passageContext} back="/?q=lease&court=ghasc" />);
    const earlier = screen.getByText(/Show earlier text/).closest("details")!;
    expect(earlier.open).toBe(false);
    expect(within(earlier).getByText("The facts are these.")).toBeTruthy();
    const selected = container.querySelector('[aria-current="true"]')!;
    expect(selected.textContent).toContain("recover possession");
    expect(earlier.contains(selected)).toBe(false);
    expect(screen.queryByText(/Show later text/)).toBeNull(); // no later passages
    expect(screen.getAllByRole("link", { name: "Original on GhaLII" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "← Back to results" }).getAttribute("href")).toBe(
      "/?q=lease&court=ghasc",
    );
  });
});

it("the site-wide attribution is the API's own and credits GhaLII", () => {
  render(<Attribution />);
  expect(ATTRIBUTION).toContain("GhaLII");
  expect(ATTRIBUTION).toContain("CC BY-NC 4.0");
  expect(screen.getByText(NOTICE)).toBeTruthy();
});
