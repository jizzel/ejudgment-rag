import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewEditor } from "@/components/ReviewEditor";
import { SiteNav } from "@/components/UserMenu";
import { errorMessage } from "@/lib/errors";
import { approvalProblems, filterProblems, labelsFrom, toDraft, toggleCase, togglePassage } from "@/lib/review";
import type { JudgmentRef, ReviewDetail, ReviewQuestion, UserInfo } from "@/lib/types";

import { caseResult, judgment, queryInfo } from "./fixtures";

const actions = vi.hoisted(() => ({
  saveQuestion: vi.fn(),
  changeStatus: vi.fn(),
  previewAnswer: vi.fn(),
  findJudgment: vi.fn(),
  createQuestion: vi.fn(),
}));
const refresh = vi.fn();
vi.mock("@/app/review/actions", () => actions);
vi.mock("@/app/actions", () => ({ logout: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push: vi.fn() }) }));
vi.mock("@/app/evidence-actions", () => ({ loadPassage: vi.fn() }));

const URI = judgment.canonical_uri;
const EXCERPT = caseResult.passages[0].excerpt;

const question: ReviewQuestion = {
  id: "issue-04",
  status: "draft",
  version: 3,
  question: "When may a landlord recover possession?",
  category: "issue",
  filters: { court: "ghasc", year_from: 2015 },
  expect_no_answer: false,
  gold_canonical_uris: [],
  gold_passages: [],
  notes: null,
  created_at: "2026-10-09T10:00:00Z",
  updated_at: "2026-10-09T10:00:00Z",
  reviewed_at: null,
  reviewed_by: null,
};

function detail(overrides: Partial<ReviewQuestion> = {}, gold_cases: JudgmentRef[] = []): ReviewDetail {
  return {
    question: { ...question, ...overrides },
    gold_cases,
    history: [{ action: "imported", user: null, created_at: "2026-10-09T10:00:00Z" }],
    candidates: {
      query: question.question,
      cases: [caseResult],
      passages: caseResult.passages,
      query_info: queryInfo,
      attribution: "Source: GhaLII test attribution",
      notice: "Test notice",
    },
  };
}

const approve = () => screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement;
const save = () => screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("approval rule (same as the API)", () => {
  const labels = labelsFrom(question);

  it("needs gold cases or an expected abstention, never both", () => {
    expect(approvalProblems(labels)).toHaveLength(1);
    expect(approvalProblems(toggleCase(labels, URI))).toEqual([]);
    expect(approvalProblems({ ...labels, expect_no_answer: true })).toEqual([]);
    expect(approvalProblems({ ...toggleCase(labels, URI), expect_no_answer: true })).toHaveLength(1);
  });

  it("requires gold passages to belong to gold cases, and real years", () => {
    const withPassage = togglePassage(labels, URI, EXCERPT);
    expect(withPassage.gold_canonical_uris).toEqual([URI]); // marking a passage marks its case
    expect(approvalProblems({ ...withPassage, gold_canonical_uris: [] })).toContain(
      "Every gold passage must come from a gold case.",
    );
    expect(approvalProblems({ ...withPassage, year_to: "20x" })).toHaveLength(1);
  });

  it("builds the API payload: trimmed, filters only when set, passages verbatim", () => {
    let labels2 = togglePassage({ ...labels, question: "  Q?  ", judge: " " }, URI, `  ${EXCERPT}  `);
    labels2 = togglePassage(labels2, URI, "too short"); // under 20 characters: ignored
    expect(toDraft(labels2)).toEqual({
      question: "Q?",
      category: "issue",
      filters: { court: "ghasc", year_from: 2015 },
      expect_no_answer: false,
      gold_canonical_uris: [URI],
      gold_passages: [{ canonical_uri: URI, text: EXCERPT }],
      notes: null,
    });
    // Unmarking a case drops its passages too.
    expect(toggleCase(labels2, URI).gold_passages).toEqual([]);
  });
});

describe("filters survive editing (never silently widened)", () => {
  it("keeps every stored filter, jurisdiction included", () => {
    const stored = { court: "ghasc", jurisdiction: "gh", year_from: 2015, year_to: 2020, judge: "Dotse" };
    expect(toDraft(labelsFrom({ ...question, filters: stored })).filters).toEqual(stored);
  });

  it("refuses malformed or reversed years instead of dropping them", () => {
    const labels = labelsFrom(question);
    for (const bad of [{ year_from: "202" }, { year_to: "20x5" }, { year_from: "2021", year_to: "2019" }]) {
      expect(filterProblems({ ...labels, ...bad })).toHaveLength(1);
      expect(() => toDraft({ ...labels, ...bad })).toThrow();
    }
    expect(filterProblems(labels)).toEqual([]);
  });
});

describe("review editor", () => {
  it("saves an unrelated edit with the jurisdiction filter intact", async () => {
    actions.saveQuestion.mockResolvedValue({ ok: true, data: null });
    render(<ReviewEditor detail={detail({ filters: { court: "ghasc", jurisdiction: "gh" } })} />);
    expect((screen.getByLabelText("Jurisdiction") as HTMLInputElement).value).toBe("gh");
    fireEvent.change(screen.getByLabelText("Notes"), { target: { value: "checked" } });
    fireEvent.click(save());
    await waitFor(() => expect(actions.saveQuestion).toHaveBeenCalled());
    expect(actions.saveQuestion.mock.calls[0][1].filters).toEqual({ court: "ghasc", jurisdiction: "gh" });
  });

  it("does not save a malformed year, and says why", () => {
    render(<ReviewEditor detail={detail()} />);
    fireEvent.change(screen.getByLabelText("From year"), { target: { value: "202" } });
    expect(save().disabled).toBe(true);
    expect(screen.getByRole("alert", { name: "Cannot save" }).textContent).toContain("From year");
    fireEvent.click(save());
    expect(actions.saveQuestion).not.toHaveBeenCalled();
  });

  it("renders judgment text as text and credits GhaLII", () => {
    const { container } = render(<ReviewEditor detail={detail()} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(screen.getByText(/Source: GhaLII test attribution/)).toBeTruthy();
  });

  it("enables Approve only for saved, valid labels", () => {
    const { unmount } = render(<ReviewEditor detail={detail()} />);
    expect(approve().disabled).toBe(true); // no gold case yet
    expect(save().disabled).toBe(true); // nothing changed
    fireEvent.click(screen.getByRole("checkbox", { name: "Gold case" }));
    expect(save().disabled).toBe(false);
    expect(approve().disabled).toBe(true); // unsaved
    unmount();
    render(<ReviewEditor detail={detail({ gold_canonical_uris: [URI] })} />);
    expect(approve().disabled).toBe(false);
  });

  it("does not offer Approve on an approved question", () => {
    render(<ReviewEditor detail={detail({ status: "approved", gold_canonical_uris: [URI] })} />);
    expect(approve().disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Reopen" })).toBeTruthy();
  });

  it("saves the marked labels with the version it was loaded at", async () => {
    actions.saveQuestion.mockResolvedValue({ ok: true, data: null });
    render(<ReviewEditor detail={detail()} />);
    fireEvent.click(screen.getByRole("button", { name: /Mark as gold passage/ }));
    fireEvent.click(save());
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const [id, draft, version] = actions.saveQuestion.mock.calls[0];
    expect([id, version]).toEqual(["issue-04", 3]);
    expect(draft.gold_canonical_uris).toEqual([URI]);
    expect(draft.gold_passages).toEqual([{ canonical_uri: URI, text: EXCERPT.trim() }]);
  });

  it("explains a conflicting save", async () => {
    actions.changeStatus.mockResolvedValue({
      ok: false,
      code: "version_conflict",
      message: "changed by someone else",
    });
    render(<ReviewEditor detail={detail({ gold_canonical_uris: [URI] })} />);
    fireEvent.click(approve());
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(errorMessage("version_conflict"))).toBeTruthy();
    expect(actions.changeStatus).toHaveBeenCalledWith("issue-04", "approve", 3);
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("every judgment the reviewer labels links to the original", () => {
  const elsewhere: JudgmentRef = {
    ...judgment,
    judgment_id: "44444444-4444-5444-8444-444444444444",
    canonical_uri: "/akn/gh/judgment/ghasc/2015/132/eng@2015-06-17",
    citation: "Elsewhere v State [2015] GHASC 132",
    source_url: "https://ghalii.org/akn/gh/judgment/ghasc/2015/132/eng@2015-06-17",
  };
  const ghaliiLinks = () =>
    screen.getAllByRole("link", { name: "Original on GhaLII" }).map((a) => [a.getAttribute("href"), a.getAttribute("rel")]);

  it("shows gold cases outside the candidates with their citation and link", () => {
    const missing = "/akn/gh/judgment/ghasc/1900/999/eng@1900-01-01";
    render(<ReviewEditor detail={detail({ gold_canonical_uris: [elsewhere.canonical_uri, missing] }, [elsewhere])} />);
    expect(screen.getByText(elsewhere.citation)).toBeTruthy();
    expect(ghaliiLinks()).toContainEqual([elsewhere.source_url, "noopener noreferrer"]);
    expect(screen.getByText(missing)).toBeTruthy();
    expect(screen.getByText(/Not an eligible judgment in the corpus/)).toBeTruthy();
  });

  it("links citation lookup results before they are added", async () => {
    actions.findJudgment.mockResolvedValue({
      ok: true,
      data: { cases: [{ ...caseResult, judgment: elsewhere }] },
    });
    render(<ReviewEditor detail={detail()} />);
    fireEvent.change(screen.getByLabelText("Citation"), { target: { value: "[2015] GHASC 132" } });
    fireEvent.click(screen.getByRole("button", { name: "Find" }));
    await screen.findByRole("button", { name: "Add as gold case" });
    expect(ghaliiLinks()).toContainEqual([elsewhere.source_url, "noopener noreferrer"]);
  });
});

describe("review link", () => {
  const user = (role: UserInfo["role"]): UserInfo => ({
    id: "33333333-3333-5333-8333-333333333333",
    email: "x@example.org",
    display_name: "X",
    role,
  });

  it("is shown to reviewers and admins only", () => {
    const { rerender } = render(<SiteNav me={user("researcher")} />);
    expect(screen.queryAllByRole("link", { name: "Review", hidden: true })).toHaveLength(0);
    for (const role of ["reviewer", "admin"] as const) {
      rerender(<SiteNav me={user(role)} />);
      // once in the inline navigation, once in the small-screen menu
      const links = screen.getAllByRole("link", { name: "Review", hidden: true });
      expect(links.map((a) => a.getAttribute("href"))).toEqual(["/review", "/review"]);
    }
  });
});
