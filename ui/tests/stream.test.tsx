import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/app/evidence-actions", () => ({ loadPassage: vi.fn() }));

import { AnswerProgress, progressSteps } from "@/components/AnswerProgress";
import { AskForm } from "@/components/AskForm";
import { streamQuestion } from "@/lib/chat-stream";
import { ApiError } from "@/lib/errors";
import { chatEvent, SseParser } from "@/lib/sse";
import type { PassageResult } from "@/lib/types";

import { answered, caseResult, judgment, passageContext, sseResponse } from "./fixtures";

const passage = caseResult.passages[0];
const other: PassageResult = {
  ...passage,
  chunk_id: "77777777-7777-5777-8777-777777777777",
  judgment: { ...judgment, judgment_id: "88888888-8888-5888-8888-888888888888", canonical_uri: "/akn/other", citation: "Other v Case" },
};
const stage = (name: string, claims?: number) => ({ type: "stage", stage: name, ...(claims ? { claims } : {}) });
const sources = { type: "sources", passages: [passage, other] };

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => vi.clearAllMocks());

describe("event-stream parsing", () => {
  it("handles events split across chunks, several per chunk, comments and CRLF", () => {
    const parser = new SseParser();
    expect(parser.push(": keep-alive\r\n\r\nevent: stage\r\nda")).toEqual([]);
    expect(parser.push('ta: {"type":"stage","stage":"searching"}\n\nevent: x\ndata: 1\n\nevent: y\n')).toEqual([
      { event: "stage", data: '{"type":"stage","stage":"searching"}' },
      { event: "x", data: "1" },
    ]);
    expect(parser.push("data: a\ndata: b\n\n")).toEqual([{ event: "y", data: "a\nb" }]);
  });

  it("ignores unknown, malformed or mislabelled events", () => {
    expect(chatEvent({ event: "stage", data: '{"type":"stage","stage":"drafting"}' })).toEqual({ type: "stage", stage: "drafting" });
    expect(chatEvent({ event: "x", data: '{"type":"x"}' })).toBeNull();
    expect(chatEvent({ event: "stage", data: "{not json" })).toBeNull();
    expect(chatEvent({ event: "answer", data: '{"type":"stage"}' })).toBeNull();
  });
});

describe("the stream client", () => {
  const ask = (fetcher: typeof fetch, onProgress = vi.fn(), signal?: AbortSignal) =>
    streamQuestion({ question: "q" }, { fetcher, onProgress, signal });

  it("reports progress in order and resolves with the answer (chunks split anywhere)", async () => {
    const onProgress = vi.fn();
    const events = [stage("searching"), sources, stage("drafting"), stage("checking", 2), { type: "answer", answer: answered }];
    const fetcher = vi.fn(async () => sseResponse(events, { split: true }));
    expect(await ask(fetcher, onProgress)).toEqual(answered);
    expect(onProgress.mock.calls.map(([e]) => e.type === "stage" ? e.stage : e.type)).toEqual([
      "searching",
      "sources",
      "drafting",
      "checking",
    ]);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/chat"); // the question travels in the body, never in a URL
    expect(JSON.parse(String(init.body))).toEqual({ question: "q" });
  });

  it("rejects with an error event's code, and says when the stream breaks off", async () => {
    const failing = vi.fn(async () =>
      sseResponse([stage("searching"), { type: "error", error: { code: "budget_exhausted", message: "spent" } }]),
    );
    await expect(ask(failing)).rejects.toMatchObject({ code: "budget_exhausted", message: "spent" });
    const cut = vi.fn(async () => sseResponse([stage("searching"), stage("drafting")]));
    await expect(ask(cut)).rejects.toMatchObject({ code: "stream_interrupted" });
  });

  it("passes the abort signal on and rejects with the abort, not an error", async () => {
    const abort = new AbortController();
    const fetcher = vi.fn(async (_: string, init: RequestInit) => {
      expect(init.signal).toBe(abort.signal);
      abort.abort();
      throw new DOMException("aborted", "AbortError");
    });
    const error = await ask(fetcher as unknown as typeof fetch, vi.fn(), abort.signal).catch((e: unknown) => e);
    expect(error).not.toBeInstanceOf(ApiError);
    expect((error as DOMException).name).toBe("AbortError");
  });
});

describe("answer progress", () => {
  it("shows the real stages, with what was found", () => {
    const at = (s: "searching" | "drafting" | "checking", claims: number | null = null, passages: PassageResult[] = []) =>
      progressSteps({ stage: s, passages, claims }).map((step) => `${step.state}:${step.label}`);
    expect(at("searching")).toEqual([
      "active:Searching the judgments",
      "pending:Drafting the answer from those passages",
      "pending:Checking each statement against its source",
    ]);
    expect(at("checking", 3, [passage, other, passage])).toEqual([
      "done:Searching the judgments",
      "done:Found 3 passages in 2 judgments",
      "done:Drafting the answer from those passages",
      "active:Checking 3 statements against their sources",
    ]);
  });

  it("lists the passages being read by case; each opens in context", () => {
    const onSelect = vi.fn((_: string, e: { preventDefault: () => void }) => e.preventDefault());
    const { container } = render(
      <AnswerProgress
        progress={{ stage: "drafting", passages: [passage, other], claims: null }}
        question="landlord"
        elapsed={12}
        selected={null}
        onSelect={onSelect}
        onCancel={vi.fn()}
      />,
    );
    expect(container.querySelectorAll("article")).toHaveLength(2);
    expect(container.querySelector("img")).toBeNull(); // corpus text stays text
    expect(screen.getByText("(12 s)")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("link", { name: "Show in context" })[1]);
    expect(onSelect.mock.calls[0][0]).toBe(other.chunk_id);
  });
});

describe("asking with progress", () => {
  /** A stream the test feeds event by event; aborting it errors the read like a real fetch. */
  function liveStream() {
    let push!: (event: object) => void;
    let close!: () => void;
    const encoder = new TextEncoder();
    let signal: AbortSignal | undefined;
    const fetcher = vi.fn(async (_: string, init: RequestInit) => {
      signal = init.signal ?? undefined;
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          push = (event) =>
            controller.enqueue(encoder.encode(`event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`));
          close = () => controller.close();
          signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
        },
      });
      return new Response(body, { headers: { "content-type": "text/event-stream" } });
    });
    vi.stubGlobal("fetch", fetcher);
    return {
      fetcher,
      send: async (event: object) => act(async () => push(event)),
      end: async () => act(async () => close()),
      aborted: () => signal?.aborted === true,
    };
  }

  async function askQuestion() {
    const load = vi.fn(async () => ({ ok: true as const, context: passageContext }));
    const { container } = render(<AskForm courts={null} load={load} />);
    await waitFor(() => expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "When may a landlord evict?" } });
    fireEvent.submit(container.querySelector("form")!);
    return { container, load };
  }

  it("shows each stage as it arrives, then the answer", async () => {
    const stream = liveStream();
    await askQuestion();
    await stream.send(stage("searching"));
    const active = () => document.querySelector('li[aria-current="step"]')?.textContent;
    expect(active()).toContain("Searching the judgments");
    await stream.send(sources);
    await stream.send(stage("drafting"));
    expect(screen.getByText("Found 2 passages in 2 judgments")).toBeTruthy();
    expect(active()).toContain("Drafting the answer");
    await stream.send(stage("checking", 1));
    expect(active()).toContain("Checking 1 statement against its source");
    await stream.send({ type: "answer", answer: answered });
    expect(await screen.findByRole("heading", { name: "Answer" })).toBeTruthy();
    expect(screen.queryByText("Preparing the answer")).toBeNull();
  });

  it("a passage being read opens beside the progress", async () => {
    const stream = liveStream();
    const { load } = await askQuestion();
    await stream.send(sources);
    fireEvent.click(screen.getAllByRole("link", { name: "Show in context" })[0]);
    expect(load).toHaveBeenCalledWith(passage.chunk_id);
    expect(await screen.findByRole("region", { name: "Passage in context" })).toBeTruthy();
  });

  it("Cancel stops the answer, keeps the question and says nothing was answered", async () => {
    const stream = liveStream();
    const { container } = await askQuestion();
    await stream.send(stage("drafting"));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(stream.aborted()).toBe(true);
    expect(screen.getByRole("status").textContent).toContain("Cancelled. Nothing was answered");
    expect(container.querySelector("form")!.hidden).toBe(false);
    expect((screen.getByLabelText("Your question") as HTMLTextAreaElement).value).toBe("When may a landlord evict?");
    // Once the aborted read has settled, the abort is still not reported as an error.
    await act(async () => new Promise((r) => setTimeout(r, 50)));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Cancelled");
  });

  it("shows an error event's message, and an interrupted stream as such", async () => {
    let stream = liveStream();
    await askQuestion();
    await stream.send({ type: "error", error: { code: "llm_unavailable", message: "down" } });
    expect((await screen.findByRole("alert")).textContent).toContain("answer model is not available");
    document.body.innerHTML = "";
    stream = liveStream();
    await askQuestion();
    await stream.send(stage("searching"));
    await stream.end();
    expect((await screen.findByRole("alert")).textContent).toContain("connection was interrupted");
  });

  it("cannot submit before it is hydrated, and never as a GET", () => {
    const html = renderToString(<AskForm courts={null} />);
    const form = new DOMParser().parseFromString(html, "text/html");
    expect(form.querySelector("form")?.getAttribute("method")).toBe("post");
    const button = form.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(within(form.body).getByText("Ask")).toBeTruthy();
  });
});
