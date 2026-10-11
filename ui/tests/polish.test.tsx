import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/actions", () => ({ logout: vi.fn(), login: vi.fn() }));

import { LoginForm } from "@/components/LoginForm";
import { ReviewProgress } from "@/components/ReviewProgress";
import { StatusChip } from "@/components/StatusChip";
import { SiteNav } from "@/components/UserMenu";
import { ACTION_LABELS, CATEGORY_LABELS, label, STATUS_LABELS } from "@/lib/labels";
import openapi from "@/lib/openapi.json";

describe("readable labels", () => {
  const schemas = openapi.components.schemas as unknown as Record<string, { enum?: string[]; properties?: Record<string, { enum?: string[] }> }>;

  it.each([
    ["category", schemas.GoldDraft.properties!.category.enum!, CATEGORY_LABELS],
    ["status", schemas.GoldStatus.enum!, STATUS_LABELS],
    ["history action", schemas.GoldAction.enum!, ACTION_LABELS],
  ])("every %s the API can return has a readable label", (_, values, labels) => {
    expect(values.length).toBeGreaterThan(0);
    for (const value of values) {
      const text = (labels as Record<string, string>)[value];
      expect(text, `no label for ${value}`).toBeTruthy();
      expect(text).not.toContain("_");
    }
  });

  it("falls back to the value itself", () => {
    expect(label(CATEGORY_LABELS, "fact_pattern")).toBe("Fact pattern");
    expect(label(CATEGORY_LABELS, "brand_new")).toBe("brand_new");
  });
});

describe("review progress", () => {
  it("shows approved questions against the target, and per category", () => {
    render(
      <ReviewProgress
        counts={{
          by_status: { draft: 18, approved: 7, retired: 1 },
          approved_by_category: { fact_pattern: 2, out_of_corpus: 5 },
          target: { min: 40, max: 80 },
        }}
      />,
    );
    const meter = screen.getByRole("meter", { name: "Approved questions" });
    expect([meter.getAttribute("aria-valuenow"), meter.getAttribute("aria-valuemin"), meter.getAttribute("aria-valuemax")]).toEqual(["7", "0", "80"]);
    expect(meter.getAttribute("aria-valuetext")).toBe("7 approved; the target is 40 to 80");
    const chips = within(screen.getByRole("list", { name: "Approved by category" }));
    expect(chips.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Fact pattern: 2",
      "Outside the corpus: 5",
    ]);
    expect(screen.getByText(/18 draft · 1 retired/)).toBeTruthy();
  });

  it("keeps the meter's value within its range when the target is passed", () => {
    render(
      <ReviewProgress
        counts={{
          by_status: { draft: 0, approved: 120, retired: 0 },
          approved_by_category: {},
          target: { min: 50, max: 100 },
        }}
      />,
    );
    const meter = screen.getByRole("meter", { name: "Approved questions" });
    const [now, max] = [Number(meter.getAttribute("aria-valuenow")), Number(meter.getAttribute("aria-valuemax"))];
    expect([now, max]).toEqual([120, 120]);
    expect(now).toBeLessThanOrEqual(max);
    expect(meter.getAttribute("aria-valuetext")).toBe("120 approved; the target is 50 to 100");
    expect(screen.getByTestId("meter-fill").style.width).toBe("100%");
  });

  it("a status chip reads as words", () => {
    render(<StatusChip status="approved" />);
    expect(screen.getByText("Approved")).toBeTruthy();
  });
});

describe("signed out", () => {
  it("the header offers nothing to navigate to", () => {
    const { container } = render(<SiteNav me={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("the sign-in form is labelled and full width", () => {
    render(<LoginForm action={vi.fn()} next="/" />);
    const form = screen.getByRole("form", { name: "Sign in" });
    expect(within(form).getByRole("button", { name: "Sign in" }).className).toContain("w-full");
  });
});
