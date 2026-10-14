import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnswerProgress } from "@/components/AnswerProgress";
import { AnswerView } from "@/components/AnswerView";
import { CaseCard } from "@/components/CaseCard";
import { PassageView } from "@/components/PassageView";
import { SearchForm } from "@/components/SearchForm";
import { touchTarget } from "@/components/ui";

import { answered, caseResult, passageContext } from "./fixtures";

// jsdom has no layout, so these check the structure and classes the phone layout relies on
// (checked by eye at 320 and 360 px in Chrome).

const COARSE = "pointer-coarse:min-h-11";

describe("phone layout", () => {
  it("makes small links 44 px tall on touch screens", () => {
    expect(touchTarget).toContain(COARSE);
    const { unmount } = render(<CaseCard result={caseResult} query="lease" hrefFor={(id) => `/?passage=${id}`} />);
    expect(screen.getAllByRole("link", { name: "Show in context" })[0].className).toContain(COARSE);
    unmount();

    render(<AnswerView response={answered} />);
    expect(screen.getAllByRole("link", { name: "See the quote in context" })[0].className).toContain(COARSE);
    expect(screen.getAllByRole("link", { name: "Read passage" })[0].className).toContain(COARSE);
    // Claim markers sit inside a line of text: an invisible ::after enlarges them instead,
    // on touch screens only (with a mouse it would cover the neighbouring lines).
    const marker = screen.getAllByRole("link", { name: /^Source \d/ })[0].className.split(/\s+/);
    expect(marker).toContain("pointer-coarse:after:-inset-y-2.5");
    expect(marker.filter((c) => c.includes("after:") && !c.startsWith("pointer-coarse:after:"))).toEqual([]);
  });

  it("gives the back link on the passage page a touch-sized target", () => {
    render(<PassageView context={passageContext} back="/?q=lease" />);
    expect(screen.getByRole("link", { name: "← Back to results" }).className).toContain(COARSE);
  });

  it("puts the match badge under the citation on phones, beside it from sm up", () => {
    const { container } = render(<CaseCard result={caseResult} query="lease" hrefFor={(id) => `/?passage=${id}`} />);
    const header = container.querySelector("h3")!.parentElement!.parentElement!;
    expect(header.className).toMatch(/(^| )flex-col( |$)/);
    expect(header.className).toContain("sm:flex-row");
  });

  it("gives court and judge the full width on phones; the years share a row", () => {
    render(<SearchForm values={{ q: "lease" }} courts={null} errors={{}} />);
    for (const name of ["Court", "Judge"]) {
      expect(screen.getByLabelText(name).closest("label")!.className).toContain("col-span-2 ");
    }
    expect(screen.getByLabelText("From year").closest("label")!.className).not.toContain("col-span-2");
  });

  it("keeps a wrapped progress step clear of its marker", () => {
    render(
      <AnswerProgress
        progress={{ stage: "drafting", passages: [], claims: null }}
        question="lease"
        elapsed={3}
        selected={null}
        onSelect={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const step = screen.getByText(/Checking each statement/).closest("li")!;
    expect(step.className).toContain("flex");
    const [marker, label] = Array.from(step.children);
    expect(marker.getAttribute("aria-hidden")).toBe("true");
    expect(marker.className).toContain("shrink-0");
    expect(label.textContent).toContain("Checking each statement");
  });
});
