"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, errorFromBody } from "@/lib/errors";
import { parseYears } from "@/lib/search";
import type { ChatResponse, CourtInfo } from "@/lib/types";

import { AnswerView } from "./AnswerView";
import { ErrorPanel } from "./ErrorPanel";

type State =
  | { kind: "idle" }
  | { kind: "loading"; started: number }
  | { kind: "done"; response: ChatResponse }
  | { kind: "error"; error: ApiError };

const field =
  "w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900";

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

function Elapsed({ started }: { started: number }) {
  const [now, setNow] = useState(started);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <>{Math.max(0, Math.round((now - started) / 1000))} s</>;
}

export function AskForm({ courts }: { courts: CourtInfo[] | null }) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const router = useRouter();

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => {
      const raw = String(form.get(name) ?? "").trim();
      return raw === "" ? undefined : raw;
    };
    const years = parseYears(value("year_from"), value("year_to"));
    if (years instanceof ApiError) {
      setState({ kind: "error", error: years }); // never ask with a filter silently dropped
      return;
    }
    const filters = { court: value("court"), ...years, judge: value("judge") };
    setState({ kind: "loading", started: Date.now() });
    try {
      const response = await postQuestion({ question: value("question") ?? "", filters });
      setState({ kind: "done", response });
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

  const loading = state.kind === "loading";
  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Your question</span>
          <textarea
            name="question"
            rows={3}
            maxLength={1000}
            required
            placeholder="e.g. When can a court set aside a judgment obtained by fraud?"
            className={field}
          />
        </label>
        <fieldset className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <legend className="sr-only">Filters</legend>
          <label className="block text-sm">
            <span className="mb-1 block text-zinc-600 dark:text-zinc-400">Court</span>
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
          <label className="block text-sm">
            <span className="mb-1 block text-zinc-600 dark:text-zinc-400">From year</span>
            <input type="number" name="year_from" min={1900} max={2100} className={field} />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-zinc-600 dark:text-zinc-400">To year</span>
            <input type="number" name="year_to" min={1900} max={2100} className={field} />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-zinc-600 dark:text-zinc-400">Judge</span>
            <input name="judge" minLength={2} maxLength={100} className={field} />
          </label>
        </fieldset>
        <button
          type="submit"
          disabled={loading}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {loading ? "Answering…" : "Ask"}
        </button>
      </form>

      <div aria-live="polite">
        {state.kind === "loading" && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Finding passages, drafting and checking the answer against them…{" "}
            <Elapsed started={state.started} />
          </p>
        )}
        {state.kind === "error" && <ErrorPanel code={state.error.code} detail={state.error.message} />}
        {state.kind === "done" && <AnswerView response={state.response} />}
      </div>
    </div>
  );
}
