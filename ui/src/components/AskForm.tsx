"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";

import { loadPassage, type PassageResult } from "@/app/evidence-actions";
import { ApiError, errorFromBody } from "@/lib/errors";
import { resolveClaimSource, type ClaimSelection } from "@/lib/evidence";
import { FilterError, parseYears } from "@/lib/search";
import type { ChatResponse, CourtInfo } from "@/lib/types";

import { AnswerView, passageHref } from "./AnswerView";
import { ErrorPanel } from "./ErrorPanel";
import { EvidenceColumn, type Evidence } from "./EvidenceColumn";
import { YearField, type FieldErrors } from "./SearchForm";
import { isPlainClick } from "./SearchWorkspace";
import { field, primaryButton, quietButton } from "./ui";

type State =
  | { kind: "idle" }
  | { kind: "loading"; started: number }
  | { kind: "done"; response: ChatResponse }
  | { kind: "error"; error: ApiError };

type Asked = { question: string; filters: string[] };

export async function postQuestion(
  body: Record<string, unknown>,
  fetcher: typeof fetch = fetch,
): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetcher("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(503, "api_unreachable", "The research UI server is not reachable");
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw errorFromBody(response.status, data);
  return data as ChatResponse;
}

function wide(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(min-width: 1024px)").matches === true;
}

function Elapsed({ started }: { started: number }) {
  const [now, setNow] = useState(started);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <>{Math.max(0, Math.round((now - started) / 1000))} s</>;
}

/**
 * Ask a question; the answer comes first, beside the evidence. After an answer the question
 * folds into a compact header ("Edit question" reopens the form with its values), and choosing
 * a claim's source opens the quoted passage, with the quote marked, beside the answer.
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
  const router = useRouter();
  // Each selection, close or new question takes a new number; a passage that arrives for an
  // older one is dropped, so the panel always matches the selected claim and source.
  const request = useRef(0);
  const answerArea = useRef<HTMLDivElement>(null);
  const opener = useRef<string | null>(null); // the link that opened the evidence

  const show = useCallback(
    async (response: ChatResponse, claim: number, source: number | null) => {
      const target = resolveClaimSource(response, claim, source);
      if (!target) return;
      const ticket = ++request.current;
      setSelection(target);
      setEvidence({ kind: "loading", chunkId: target.chunkId });
      const result = await load(target.chunkId);
      if (ticket !== request.current) return;
      if (result.ok) setEvidence({ kind: "shown", chunkId: target.chunkId, context: result.context });
      else if (result.status === 401) router.push("/login?next=%2Fask");
      else setEvidence({ kind: "error", chunkId: target.chunkId, code: result.code, message: result.message });
    },
    [load, router],
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
    setState({ kind: "loading", started: Date.now() });
    try {
      const response = await postQuestion({ question, filters });
      setState({ kind: "done", response });
      // Beside the answer on wide screens; on small ones the evidence would cover the answer.
      if (!response.abstained && response.claims.length > 0 && wide()) void show(response, 0, null);
    } catch (error) {
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

  function selectClaim(index: number, source: number | null, event: MouseEvent<HTMLAnchorElement>) {
    if (!isPlainClick(event) || state.kind !== "done") return;
    event.preventDefault();
    opener.current = `[data-claim="${index}"][data-source="${source ?? "quote"}"]`;
    void show(state.response, index, source);
  }

  const closeEvidence = useCallback(() => {
    request.current++;
    setSelection(null);
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

      <form onSubmit={onSubmit} hidden={!editing} className="max-w-3xl space-y-3">
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
          <button type="submit" disabled={loading} className={primaryButton}>
            {loading ? "Answering…" : "Ask"}
          </button>
          {asked && (
            <button type="button" className={quietButton} onClick={() => setEditing(false)}>
              Cancel
            </button>
          )}
        </div>
      </form>

      <div aria-live="polite">
        {state.kind === "loading" && (
          <p className="max-w-3xl rounded-lg border border-line bg-surface p-4 text-sm text-muted">
            Finding passages, drafting and checking the answer against them…{" "}
            <Elapsed started={state.started} />
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
                mark={selection?.quote ? { quote: selection.quote } : null}
                pageHref={selection ? passageHref(selection.chunkId, selection.quote ?? undefined) : null}
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
