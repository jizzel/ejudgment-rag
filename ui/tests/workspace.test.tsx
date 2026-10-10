import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/app/evidence-actions", () => ({ loadPassage: vi.fn() }));

import { AskForm } from "@/components/AskForm";
import { CaseCard } from "@/components/CaseCard";
import { SearchForm } from "@/components/SearchForm";
import { SearchLink } from "@/components/SearchLink";
import { SearchWorkspace } from "@/components/SearchWorkspace";
import { LAST_SEARCH_KEY } from "@/lib/last-search";
import type { PassageResult } from "@/app/evidence-actions";
import type { CaseResult, SearchResponse } from "@/lib/types";

import { answered, answerStream, caseResult, passageContext, queryInfo } from "./fixtures";

const ID = caseResult.passages[0].chunk_id;
const params = { q: "landlord", court: "ghasc", page: "2" };

function threePassages(): CaseResult {
  const [first] = caseResult.passages;
  return {
    ...caseResult,
    passages: [
      first,
      { ...first, chunk_id: "44444444-4444-5444-8444-444444444444", excerpt: "Second matching passage." },
      { ...first, chunk_id: "55555555-5555-5555-8555-555555555555", excerpt: "Third matching passage." },
    ],
  };
}

const response: SearchResponse = {
  query: "landlord",
  passages: caseResult.passages,
  cases: [caseResult],
  query_info: queryInfo,
  attribution: "Source: GhaLII test attribution",
  notice: "Test notice",
};

/** A wide (desktop) or narrow (phone) screen for matchMedia, and a dialog that can be modal. */
function stubScreen(isWide: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("min-width") ? isWide : !isWide,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

let replaceState: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  vi.clearAllMocks();
  // jsdom has no modal dialogs: showModal just opens it (the real one also makes the page inert).
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  });
  replaceState = vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
});
afterEach(() => {
  replaceState.mockRestore();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("compact results", () => {
  it("shows one excerpt per case and folds the other matches", () => {
    render(<CaseCard result={threePassages()} query="landlord" hrefFor={(id) => `/?passage=${id}`} />);
    const more = screen.getByText("2 more matching passages").closest("details")!;
    expect(more.open).toBe(false);
    expect(within(more).getByText("Second matching passage.")).toBeTruthy();
    expect(more.textContent).not.toContain("entitled to recover");
  });

  it("opens the folded matches when one of them is the selected passage", () => {
    const { rerender } = render(
      <CaseCard
        result={threePassages()}
        query="landlord"
        hrefFor={(id) => `/?passage=${id}`}
        selected="55555555-5555-5555-8555-555555555555"
      />,
    );
    const more = screen.getByText("2 more matching passages").closest("details")!;
    expect(more.open).toBe(true);
    // Closing the passage leaves the fold open (its link gets the focus back).
    rerender(<CaseCard result={threePassages()} query="landlord" hrefFor={(id) => `/?passage=${id}`} selected={null} />);
    expect(more.open).toBe(true);
  });
});

describe("evidence beside the results", () => {
  it("opens a passage without searching again and records it in the URL", async () => {
    const load = vi.fn(async () => ({ ok: true as const, context: passageContext }));
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    vi.stubGlobal("scrollY", 1400);
    render(<SearchWorkspace response={response} params={params} load={load} />);
    expect(screen.getByText(/Choose “Show in context”/)).toBeTruthy();
    // The link's navigation (a server render that would search again) is cancelled.
    expect(fireEvent.click(screen.getByRole("link", { name: "Show in context" }))).toBe(false);
    expect(load).toHaveBeenCalledWith(ID);
    expect(replaceState).toHaveBeenLastCalledWith(null, "", `/?q=landlord&court=ghasc&page=2&passage=${ID}`);
    const panel = await screen.findByRole("region", { name: "Passage in context" });
    expect(within(panel).getByText(passageContext.judgment.citation)).toBeTruthy();
    // The case, its passage and the panel are marked together.
    expect(screen.getByRole("link", { name: "Shown in context" })).toBeTruthy();
    expect(document.querySelector('article[aria-current="true"]')).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "Open as a page" }).getAttribute("href")).toBe(
      `/passages/${ID}?from=${encodeURIComponent("/?q=landlord&court=ghasc&page=2")}`,
    );
    // Closing removes only the passage from the URL, and returns to the link that opened it.
    fireEvent.click(within(panel).getByRole("button", { name: "← Back to results" }));
    expect(replaceState).toHaveBeenLastCalledWith(null, "", "/?q=landlord&court=ghasc&page=2");
    expect(screen.queryByRole("region", { name: "Passage in context" })).toBeNull();
    await waitFor(() => expect(document.activeElement?.getAttribute("data-chunk")).toBe(ID));
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 1400 });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("starts with the passage a shared URL names, and remembers the search for the nav link", () => {
    render(
      <SearchWorkspace
        response={response}
        params={{ ...params, passage: ID }}
        initial={{ kind: "shown", chunkId: ID, context: passageContext }}
      />,
    );
    expect(screen.getByRole("region", { name: "Passage in context" })).toBeTruthy();
    expect(sessionStorage.getItem(LAST_SEARCH_KEY)).toBe(`/?q=landlord&court=ghasc&page=2&passage=${ID}`);
  });

  it("sends an ended session to sign in, coming back to the same passage", async () => {
    const navigate = vi.fn();
    const load = vi.fn(async () => ({ ok: false as const, status: 401, code: "unauthenticated", message: "x" }));
    render(<SearchWorkspace response={response} params={params} load={load} navigate={navigate} />);
    fireEvent.click(screen.getByRole("link", { name: "Show in context" }));
    await waitFor(() => expect(navigate).toHaveBeenCalled());
    expect(navigate.mock.calls[0][0]).toBe(
      `/login?next=${encodeURIComponent(`/?q=landlord&court=ghasc&page=2&passage=${ID}`)}`,
    );
  });

  it("leaves modified clicks (new tab) to the browser", () => {
    const load = vi.fn();
    render(<SearchWorkspace response={response} params={params} load={load} />);
    fireEvent.click(screen.getByRole("link", { name: "Show in context" }), { metaKey: true });
    expect(load).not.toHaveBeenCalled();
  });

  it("the Search link returns to the last search", () => {
    sessionStorage.setItem(LAST_SEARCH_KEY, "/?q=lease&passage=x");
    render(<SearchLink>Search</SearchLink>);
    fireEvent.click(screen.getByRole("link", { name: "Search" }));
    expect(push).toHaveBeenCalledWith("/?q=lease&passage=x");
  });
});

describe("search form", () => {
  it("shows a year error beside its field, keeps the value and opens the filters", () => {
    render(<SearchForm values={{ q: "lease", year_to: "20x5" }} courts={null} errors={{ year_to: "To year must be a year between 1900 and 2100." }} />);
    const input = screen.getByLabelText("To year") as HTMLInputElement;
    expect(input.value).toBe("20x5");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(input.getAttribute("aria-describedby")!)?.textContent).toContain("To year must be");
    expect(input.closest("details")!.open).toBe(true);
  });

  it("opens the filters for an error even when the value was emptied", () => {
    render(<SearchForm values={{ q: "lease" }} courts={null} errors={{ year_from: "From year must be a year between 1900 and 2100." }} />);
    expect((screen.getByLabelText("From year") as HTMLInputElement).closest("details")!.open).toBe(true);
  });

  it("keeps unused filters folded", () => {
    render(<SearchForm values={{ q: "lease" }} courts={null} />);
    expect((screen.getByLabelText("To year") as HTMLInputElement).closest("details")!.open).toBe(false);
  });
});

describe("answer beside its evidence", () => {
  function wide(matches: boolean) {
    stubScreen(matches);
  }

  async function ask(load: (chunkId: string) => Promise<PassageResult>) {
    vi.stubGlobal("fetch", vi.fn(async () => answerStream(answered)));
    const { container } = render(<AskForm courts={null} load={load} />);
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "Who may evict?" } });
    fireEvent.change(screen.getByLabelText("Judge"), { target: { value: "Dotse" } });
    fireEvent.submit(container.querySelector("form")!);
    await screen.findByRole("heading", { name: "Answer" });
    return container;
  }

  it("folds the question into a header, and opens the first claim's passage with its quote", async () => {
    wide(true);
    const load = vi.fn(async () => ({ ok: true as const, context: passageContext }));
    const container = await ask(load);
    expect(container.querySelector("form")!.hidden).toBe(true);
    expect(screen.getByText("Who may evict?")).toBeTruthy();
    expect(screen.getByText("Judge: Dotse")).toBeTruthy();
    expect(load).toHaveBeenCalledWith(answered.claims[0].quote_chunk_id);
    const panel = await screen.findByRole("region", { name: "Passage in context" });
    expect(panel.querySelector("mark")?.textContent).toBe("entitled to\nrecover possession");
    // Edit question brings the form back with what was asked.
    fireEvent.click(screen.getByRole("button", { name: "Edit question" }));
    expect(container.querySelector("form")!.hidden).toBe(false);
    expect((screen.getByLabelText("Your question") as HTMLTextAreaElement).value).toBe("Who may evict?");
  });

  it("on small screens leaves the answer in view until a source is chosen", async () => {
    wide(false);
    const load = vi.fn(async () => ({ ok: true as const, context: passageContext }));
    await ask(load);
    expect(load).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("link", { name: "Source 1" }));
    expect(load).toHaveBeenCalledWith(answered.claims[0].quote_chunk_id);
    expect(await screen.findByRole("button", { name: "← Back to the answer" })).toBeTruthy();
  });
});

/** A load() whose answers the test releases one by one, in any order. */
function controlledLoad() {
  const pending = new Map<string, (value: PassageResult) => void>();
  const load = vi.fn(
    (chunkId: string) => new Promise<PassageResult>((resolve) => pending.set(chunkId, resolve)),
  );
  const answer = async (chunkId: string, context = passageContext) => {
    pending.get(chunkId)!({ ok: true, context: { ...context, passage: { ...context.passage, chunk_id: chunkId } } });
    await new Promise((r) => setTimeout(r, 0));
  };
  return { load, answer };
}

describe("late passage responses", () => {
  const B = "44444444-4444-5444-8444-444444444444";
  const twoPassages: SearchResponse = { ...response, cases: [threePassages()] };

  it("a passage arriving after the panel was closed does not reopen it", async () => {
    const { load, answer } = controlledLoad();
    render(<SearchWorkspace response={response} params={params} load={load} />);
    fireEvent.click(screen.getByRole("link", { name: "Show in context" }));
    fireEvent.click(screen.getByRole("button", { name: "Close the passage" }));
    await answer(ID);
    expect(screen.queryByRole("region", { name: "Passage in context" })).toBeNull();
    expect(replaceState).toHaveBeenLastCalledWith(null, "", "/?q=landlord&court=ghasc&page=2");
  });

  it("an older selection's passage does not replace the newer one", async () => {
    const { load, answer } = controlledLoad();
    render(<SearchWorkspace response={twoPassages} params={params} load={load} />);
    fireEvent.click(screen.getAllByRole("link", { name: "Show in context" })[0]); // A
    fireEvent.click(document.querySelector(`a[data-chunk="${B}"]`)!); // B (inside the fold)
    await answer(B, { ...passageContext, judgment: { ...passageContext.judgment, citation: "Case B" } });
    await answer(ID, { ...passageContext, judgment: { ...passageContext.judgment, citation: "Case A" } });
    const panel = screen.getByRole("region", { name: "Passage in context" });
    expect(within(panel).getByText("Case B")).toBeTruthy();
    expect(within(panel).queryByText("Case A")).toBeNull();
  });

  it("in an answer, the panel always matches the selected claim", async () => {
    stubScreen(true);
    const second = { ...answered.claims[0], text: "Second claim.", quote: "second quote", quote_chunk_id: B };
    const twoClaims = { ...answered, claims: [answered.claims[0], second] };
    vi.stubGlobal("fetch", vi.fn(async () => answerStream(twoClaims)));
    const { load, answer } = controlledLoad();
    const { container } = render(<AskForm courts={null} load={load} />);
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "Who may evict?" } });
    fireEvent.submit(container.querySelector("form")!);
    await screen.findByRole("heading", { name: "Answer" }); // claim 1 starts loading
    fireEvent.click(screen.getAllByRole("link", { name: "See the quote in context" })[1]); // claim 2
    await answer(B, { ...passageContext, judgment: { ...passageContext.judgment, citation: "Claim two's case" } });
    await answer(ID, { ...passageContext, judgment: { ...passageContext.judgment, citation: "Claim one's case" } });
    const panel = screen.getByRole("region", { name: "Passage in context" });
    expect(within(panel).getByText("Claim two's case")).toBeTruthy();
    expect(screen.getByText("Second claim.").closest("[aria-current]")?.getAttribute("aria-current")).toBe("true");
  });
});

describe("a claim citing several sources", () => {
  const OTHER = "66666666-6666-5666-8666-666666666666";
  const multi = {
    ...answered,
    claims: [{ ...answered.claims[0], source_numbers: [1, 2] }],
    sources: [
      answered.sources[0],
      {
        ...answered.sources[0],
        number: 2,
        judgment: { ...answered.sources[0].judgment, judgment_id: OTHER, citation: "Second v Source" },
        passages: [{ ...answered.sources[0].passages[0], chunk_id: OTHER, excerpt: "Other case." }],
      },
    ],
  };

  it("each marker opens its own source; only the quoted passage gets the quote marked", async () => {
    const { resolveClaimSource } = await import("@/lib/evidence");
    expect(resolveClaimSource(multi, 0, 2)).toEqual({ claim: 0, source: 2, chunkId: OTHER, quote: null });
    const quoted = { claim: 0, chunkId: ID, quote: answered.claims[0].quote };
    expect(resolveClaimSource(multi, 0, 1)).toEqual({ ...quoted, source: 1 });
    expect(resolveClaimSource(multi, 0, null)).toEqual({ ...quoted, source: null });
    expect(resolveClaimSource(multi, 5, 1)).toBeNull();
  });

  it("clicking [2] loads source 2 and marks only that source", async () => {
    stubScreen(true);
    vi.stubGlobal("fetch", vi.fn(async () => answerStream(multi)));
    const load = vi.fn(async (chunkId: string) => ({
      ok: true as const,
      context: { ...passageContext, passage: { ...passageContext.passage, chunk_id: chunkId } },
    }));
    const { container } = render(<AskForm courts={null} load={load} />);
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "Who may evict?" } });
    fireEvent.submit(container.querySelector("form")!);
    await screen.findByRole("heading", { name: "Answer" });
    fireEvent.click(screen.getByRole("link", { name: "Source 2" }));
    await waitFor(() => expect(load).toHaveBeenLastCalledWith(OTHER));
    expect(document.getElementById("source-2")?.getAttribute("aria-current")).toBe("true");
    expect(document.getElementById("source-1")?.getAttribute("aria-current")).toBeNull();
    const panel = await screen.findByRole("region", { name: "Passage in context" });
    await waitFor(() => expect(panel.querySelector("mark")).toBeNull()); // the quote is not in source 2
  });
});

describe("the evidence sheet on small screens", () => {
  beforeEach(() => stubScreen(false));

  it("is a modal dialog (focus moves in, the page behind is inert) and Escape closes it", async () => {
    const load = vi.fn(async () => ({ ok: true as const, context: passageContext }));
    render(<SearchWorkspace response={response} params={params} load={load} />);
    expect(document.querySelector("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: "Show in context" }));
    const sheet = await waitFor(() => document.querySelector("dialog")!);
    expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();
    expect(sheet.getAttribute("aria-label")).toBe("Passage in context");
    // Escape (the dialog's cancel event) closes through the workspace and refocuses the link.
    fireEvent(sheet, new Event("cancel", { cancelable: true }));
    expect(document.querySelector("dialog")).toBeNull();
    await waitFor(() => expect(document.activeElement?.getAttribute("data-chunk")).toBe(ID));
  });

  it("in an answer, closing returns focus to the source marker that opened it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => answerStream(answered)));
    const load = vi.fn(async () => ({ ok: true as const, context: passageContext }));
    const { container } = render(<AskForm courts={null} load={load} />);
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "Who may evict?" } });
    fireEvent.submit(container.querySelector("form")!);
    await screen.findByRole("heading", { name: "Answer" });
    const marker = screen.getByRole("link", { name: "Source 1" });
    fireEvent.click(marker);
    const sheet = await waitFor(() => {
      const dialog = document.querySelector("dialog");
      expect(dialog?.querySelector('[aria-label="Selected passage"]')).toBeTruthy();
      return dialog!;
    });
    const back = within(sheet).getByRole("button", { name: "← Back to the answer" });
    fireEvent.click(back);
    await waitFor(() => expect(document.activeElement).toBe(marker));
  });
});

it("keeps the sheet's controls mounted while the passage loads (focus stays in the sheet)", async () => {
  stubScreen(false);
  const { load, answer } = controlledLoad();
  render(<SearchWorkspace response={response} params={params} load={load} />);
  fireEvent.click(screen.getByRole("link", { name: "Show in context" }));
  const back = await waitFor(() => within(document.querySelector("dialog")!).getByRole("button", { name: "← Back to results" }));
  back.focus();
  await answer(ID);
  expect(document.querySelector('dialog [aria-label="Selected passage"]')).toBeTruthy();
  expect(back.isConnected).toBe(true);
  expect(document.activeElement).toBe(back);
});

describe("restoring a shared passage", () => {
  const empty: SearchResponse = { ...response, cases: [], passages: [] };

  it("maps the server's result to the panel's starting state", async () => {
    const { restoredEvidence } = await import("@/lib/evidence");
    const { ApiError } = await import("@/lib/errors");
    expect(restoredEvidence(null, null)).toEqual({ kind: "none" });
    expect(restoredEvidence(ID, { ok: true, value: passageContext })).toEqual({
      kind: "shown",
      chunkId: ID,
      context: passageContext,
    });
    const gone = new ApiError(404, "passage_not_found", "No such passage");
    expect(restoredEvidence(ID, { ok: false, error: gone })).toEqual({
      kind: "error",
      chunkId: ID,
      code: "passage_not_found",
      message: "No such passage",
    });
  });

  it("opens the passage even when the search now finds nothing", () => {
    render(
      <SearchWorkspace
        response={empty}
        params={{ ...params, passage: ID }}
        initial={{ kind: "shown", chunkId: ID, context: passageContext }}
      />,
    );
    expect(screen.getByText(/No judgments matched/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Passage in context" })).toBeTruthy();
  });

  it.each([
    ["passage_not_found", "That passage is not available."],
    ["database_unavailable", "The judgment database is not reachable right now."],
  ])("says why a shared passage (%s) could not be shown, and closing clears it", (code, text) => {
    render(
      <SearchWorkspace
        response={response}
        params={{ ...params, passage: ID }}
        initial={{ kind: "error", chunkId: ID, code, message: "detail" }}
      />,
    );
    const panel = screen.getByRole("region", { name: "Passage in context" });
    expect(within(panel).getByRole("alert").textContent).toContain(text);
    expect(screen.queryByText(/Choose “Show in context”/)).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "Close the passage" }));
    expect(replaceState).toHaveBeenLastCalledWith(null, "", "/?q=landlord&court=ghasc&page=2");
    expect(screen.getByText(/Choose “Show in context”/)).toBeTruthy();
  });
});
