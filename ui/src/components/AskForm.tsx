"use client";

import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type MouseEvent,
} from "react";

import { loadPassage, type PassageResult } from "@/app/evidence-actions";
import { streamQuestion, type ChatProgress } from "@/lib/chat-stream";
import { ApiError } from "@/lib/errors";
import { resolveClaimSource, type ClaimSelection } from "@/lib/evidence";
import { FilterError, parseYears } from "@/lib/search";
import type { ChatResponse, CourtInfo } from "@/lib/types";

import { AnswerProgress, type Progress } from "./AnswerProgress";
import { AnswerView, passageHref } from "./AnswerView";
import { ErrorPanel } from "./ErrorPanel";
import { EvidenceColumn, type Evidence } from "./EvidenceColumn";
import type { Mark } from "./EvidencePanel";
import { YearField, type FieldErrors } from "./SearchForm";
import { isPlainClick } from "./SearchWorkspace";
import { field, primaryButton, quietButton } from "./ui";

type State =
  | { kind: "idle" }
  | { kind: "loading"; started: number; progress: Progress }
  | { kind: "done"; response: ChatResponse }
  | { kind: "cancelled" }
  | { kind: "error"; error: ApiError };

type Asked = { question: string; filters: string[] };

const noSubscribe = () => () => {};

/** False in the server's HTML and until React has hydrated; then true. */
function useHydrated(): boolean {
  return useSyncExternalStore(
    noSubscribe,
    () => true,
    () => false,
  );
}

function advance(progress: Progress, event: ChatProgress): Progress {
  if (event.type === "sources") return { ...progress, passages: event.passages };
  return { ...progress, stage: event.stage, claims: event.claims ?? progress.claims };
}

function wide(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(min-width: 1024px)").matches === true;
}

function useElapsed(started: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (started === null) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [started]);
  return started === null ? 0 : Math.max(0, Math.round((now - started) / 1000));
}

/**
 * Ask a question; the answer comes first, beside the evidence. While it is prepared the page
 * shows the server's real progress and the passages being read, and Cancel stops it (in the
 * API too). After an answer the question folds into a compact header ("Edit question" reopens
 * the form with its values), and choosing a claim's source opens the quoted passage, with the
 * quote marked, beside the answer. The form never submits before it is hydrated, so the
 * question cannot end up in a URL.
 */
export function AskForm({
  courts,
  load = loadPassage,
}: {
  courts: CourtInfo[] | null;
  load?: (chunkId: string) => Promise<PassageResult>;
}) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [asked, setAsked] = useState<Asked | null>(null);
  const [editing, setEditing] = useState(true);
  const [selection, setSelection] = useState<ClaimSelection | null>(null);
  const [evidence, setEvidence] = useState<Evidence>({ kind: "none" });
  const [mark, setMark] = useState<Mark>(null);
  const router = useRouter();
  const hydrated = useHydrated();
  const controller = useRef<AbortController | null>(null);
  const elapsed = useElapsed(state.kind === "loading" ? state.started : null);

  useEffect(() => () => controller.current?.abort(), []); // leaving the page stops the answer
  // Each selection, close or new question takes a new number; a passage that arrives for an
  // older one is dropped, so the panel always matches the selected claim and source.
  const request = useRef(0);
  const answerArea = useRef<HTMLDivElement>(null);
  const opener = useRef<string | null>(null); // the link that opened the evidence

  const open = useCallback(
    async (chunkId: string, how: Mark, claim: ClaimSelection | null) => {
      const ticket = ++request.current;
      setSelection(claim);
      setMark(how);
      setEvidence({ kind: "loading", chunkId });
      const result = await load(chunkId);
      if (ticket !== request.current) return;
      if (result.ok) setEvidence({ kind: "shown", chunkId, context: result.context });
      else if (result.status === 401) router.push("/login?next=%2Fask");
      else setEvidence({ kind: "error", chunkId, code: result.code, message: result.message });
    },
    [load, router],
  );

  const show = useCallback(
    async (response: ChatResponse, claim: number, source: number | null) => {
      const target = resolveClaimSource(response, claim, source);
      if (target) await open(target.chunkId, target.quote ? { quote: target.quote } : null, target);
    },
    [open],
  );

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => {
      const raw = String(form.get(name) ?? "").trim();
      return raw === "" ? undefined : raw;
    };
    const years = parseYears(value("year_from"), value("year_to"));
    if (years instanceof FilterError) {
      setErrors({ [years.field]: years.message }); // never ask with a filter silently dropped
      return;
    }
    setErrors({});
    const filters = { court: value("court"), ...years, judge: value("judge") };
    const question = value("question") ?? "";
    setAsked({
      question,
      filters: [
        filters.court && `Court: ${filters.court}`,
        (filters.year_from || filters.year_to) && `Years: ${filters.year_from ?? "…"}–${filters.year_to ?? "…"}`,
        filters.judge && `Judge: ${filters.judge}`,
      ].filter((item): item is string => Boolean(item)),
    });
    setEditing(false);
    request.current++;
    setSelection(null);
    setEvidence({ kind: "none" });
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setState({
      kind: "loading",
      started: Date.now(),
      progress: { stage: "searching", passages: [], claims: null },
    });
    try {
      const response = await streamQuestion(
        { question, filters },
        {
          signal: abort.signal,
          onProgress: (event) =>
            setState((current) =>
              current.kind === "loading" ? { ...current, progress: advance(current.progress, event) } : current,
            ),
        },
      );
      if (abort.signal.aborted) return;
      setState({ kind: "done", response });
      // Beside the answer on wide screens; on small ones the evidence would cover the answer.
      if (!response.abstained && response.claims.length > 0 && wide()) void show(response, 0, null);
    } catch (error) {
      if (abort.signal.aborted) return; // cancelled: cancel() has already updated the page
      if (error instanceof ApiError && error.status === 401) {
        router.push("/login?next=%2Fask"); // the session ended: sign in again
        return;
      }
      setState({
        kind: "error",
        error: error instanceof ApiError ? error : new ApiError(500, "unknown", String(error)),
      });
    }
  }

  function cancel() {
    controller.current?.abort();
    controller.current = null;
    request.current++;
    setEvidence({ kind: "none" });
    setState({ kind: "cancelled" });
    setEditing(true); // the question is still in the form
  }

  function selectConsidered(chunkId: string, event: MouseEvent<HTMLAnchorElement>) {
    if (!isPlainClick(event) || state.kind !== "loading" || !asked) return;
    event.preventDefault();
    opener.current = `[data-chunk="${chunkId}"]`;
    void open(chunkId, { terms: asked.question }, null);
  }

  function selectClaim(index: number, source: number | null, event: MouseEvent<HTMLAnchorElement>) {
    if (!isPlainClick(event) || state.kind !== "done") return;
    event.preventDefault();
    opener.current = `[data-claim="${index}"][data-source="${source ?? "quote"}"]`;
    void show(state.response, index, source);
  }

  const closeEvidence = useCallback(() => {
    request.current++;
    setSelection(null);
    setMark(null);
    setEvidence({ kind: "none" });
    const selector = opener.current;
    setTimeout(() => {
      if (selector) answerArea.current?.querySelector<HTMLElement>(selector)?.focus({ preventScroll: true });
    }, 50);
  }, []);

  const loading = state.kind === "loading";
  const answer = state.kind === "done" ? state.response : null;

  return (
    <div className="space-y-6">
      {asked && !editing && (
        <div className="flex max-w-3xl flex-wrap items-start justify-between gap-3 rounded-lg border border-line bg-surface p-4">
          <div className="min-w-0">
            <p className="text-xs font-medium tracking-wide text-muted uppercase">Your question</p>
            <p className="font-serif text-lg [overflow-wrap:anywhere]">{asked.question}</p>
            {asked.filters.length > 0 && (
              <p className="mt-1 text-xs text-muted">{asked.filters.join(" · ")}</p>
            )}
          </div>
          <button type="button" className={quietButton} disabled={loading} onClick={() => setEditing(true)}>
            Edit question
          </button>
        </div>
      )}

      <form method="post" onSubmit={onSubmit} hidden={!editing} className="max-w-3xl space-y-3">
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Your question</span>
          <textarea
            name="question"
            rows={3}
            maxLength={1000}
            required
            placeholder="e.g. When can a court set aside a judgment obtained by fraud?"
            className="w-full rounded-lg border border-line bg-surface px-4 py-3 text-base"
          />
        </label>
        <details className="group" open={Object.keys(errors).length > 0 || undefined}>
          <summary className="inline-flex min-h-8 items-center text-sm text-accent">
            <span className="mr-1.5 inline-block transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden>
              ›
            </span>
            Filters
          </summary>
          <fieldset className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <legend className="sr-only">Filters</legend>
            <label className="block text-sm">
              <span className="mb-1 block text-muted">Court</span>
              {courts ? (
                <select name="court" defaultValue="" className={field}>
                  <option value="">All courts</option>
                  {courts.map((court) => (
                    <option key={court.court_code} value={court.court_code}>
                      {court.court_name ?? court.court_code}
                    </option>
                  ))}
                </select>
              ) : (
                <input name="court" placeholder="e.g. ghasc" className={field} />
              )}
            </label>
            <YearField name="year_from" label="From year" error={errors.year_from} />
            <YearField name="year_to" label="To year" error={errors.year_to} />
            <label className="block text-sm">
              <span className="mb-1 block text-muted">Judge</span>
              <input name="judge" minLength={2} maxLength={100} className={field} />
            </label>
          </fieldset>
        </details>
        <div className="flex items-center gap-3">
          {/* Disabled until hydrated: a disabled default button also blocks Enter-submission. */}
          <button type="submit" disabled={loading || !hydrated} className={primaryButton}>
            {loading ? "Answering…" : "Ask"}
          </button>
          {asked && state.kind !== "cancelled" && (
            <button type="button" className={quietButton} onClick={() => setEditing(false)}>
              Keep the current answer
            </button>
          )}
        </div>
      </form>

      <div>
        {state.kind === "loading" && (
          <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-6">
            <div ref={answerArea} className="min-w-0">
              <AnswerProgress
                progress={state.progress}
                question={asked?.question ?? ""}
                elapsed={elapsed}
                selected={evidence.kind === "none" ? null : evidence.chunkId}
                onSelect={selectConsidered}
                onCancel={cancel}
              />
            </div>
            <EvidenceColumn
              evidence={evidence}
              mark={mark}
              pageHref={evidence.kind === "none" ? null : passageHref(evidence.chunkId)}
              onClose={closeEvidence}
              empty="The passages the answer is drawn from appear on the left as they are found; choose one to read it here."
              backLabel="← Back"
            />
          </div>
        )}
        {state.kind === "cancelled" && (
          <p role="status" className="max-w-3xl rounded-lg border border-line bg-surface p-4 text-sm">
            Cancelled. Nothing was answered; your question is still in the form.
          </p>
        )}
        {state.kind === "error" && <ErrorPanel code={state.error.code} detail={state.error.message} />}
        {answer && (
          <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-6">
            <div ref={answerArea} className="min-w-0">
              <AnswerView
                response={answer}
                selectedClaim={selection?.claim ?? null}
                selectedSource={selection?.source ?? null}
                onSelectClaim={selectClaim}
              />
            </div>
            {!answer.abstained && (
              <EvidenceColumn
                evidence={evidence}
                mark={mark}
                pageHref={evidence.kind === "none" ? null : passageHref(evidence.chunkId, selection?.quote ?? undefined)}
                onClose={closeEvidence}
                empty="Choose a source marker or quote to read the passage here."
                backLabel="← Back to the answer"
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
