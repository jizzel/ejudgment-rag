"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";

import { changeStatus, findJudgment, previewAnswer, saveQuestion } from "@/app/review/actions";
import {
  approvalProblems,
  CATEGORIES,
  filterProblems,
  labelsFrom,
  type Labels,
  MIN_PASSAGE_CHARS,
  sameLabels,
  toDraft,
  toggleCase,
  togglePassage,
} from "@/lib/review";
import type { ChatResponse, JudgmentRef, ReviewDetail } from "@/lib/types";

import { AnswerView } from "./AnswerView";
import { Attribution } from "./Attribution";
import { ErrorPanel } from "./ErrorPanel";
import { JudgmentHeading } from "./JudgmentHeading";

type Problem = { code: string; message: string };

const field =
  "w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900";
const button =
  "rounded-md border border-zinc-300 px-3 py-1.5 text-sm disabled:opacity-40 dark:border-zinc-700";
const primary =
  "rounded-md bg-zinc-900 px-3 py-1.5 text-sm text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900";

/** The selected text if it lies inside `element` and is long enough to be a gold passage. */
export function selectionWithin(element: HTMLElement | null): string | null {
  const selection = typeof window === "undefined" ? null : window.getSelection();
  if (!element || !selection || selection.isCollapsed) return null;
  const { anchorNode, focusNode } = selection;
  if (!anchorNode || !focusNode || !element.contains(anchorNode) || !element.contains(focusNode)) {
    return null;
  }
  const text = selection.toString().trim();
  return text.length >= MIN_PASSAGE_CHARS ? text : null;
}

function Passage({
  uri,
  text,
  labels,
  onToggle,
}: {
  uri: string;
  text: string;
  labels: Labels;
  onToggle: (uri: string, text: string) => void;
}) {
  const ref = useRef<HTMLParagraphElement>(null);
  const marked = labels.gold_passages.some((p) => p.canonical_uri === uri && p.text === text.trim());
  return (
    <li className={`border-l-2 pl-3 ${marked ? "border-emerald-500" : "border-zinc-200 dark:border-zinc-700"}`}>
      <p ref={ref} className="whitespace-pre-line text-sm leading-relaxed">
        {text}
      </p>
      <div className="mt-1 flex gap-2 text-xs">
        <button
          type="button"
          className="underline underline-offset-2"
          // Keep the text selection when the button is pressed.
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onToggle(uri, selectionWithin(ref.current) ?? text)}
        >
          {marked ? "Unmark gold passage" : "Mark as gold passage (or the selected part)"}
        </button>
      </div>
    </li>
  );
}

export function ReviewEditor({ detail }: { detail: ReviewDetail }) {
  const router = useRouter();
  const { question, candidates, history } = detail;
  const saved = labelsFrom(question);
  const [labels, setLabels] = useState<Labels>(saved);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [running, setBusy] = useState<string | null>(null);
  // Reloading the question (and its candidate search) after a change takes a few seconds.
  const [refreshing, startRefresh] = useTransition();
  const busy = running ?? (refreshing ? "refresh" : null);
  const [preview, setPreview] = useState<ChatResponse | null>(null);
  const [lookup, setLookup] = useState("");
  const [found, setFound] = useState<JudgmentRef[] | null>(null);

  // Citations for display: candidates, cases found by citation; otherwise the URI itself.
  const names = new Map<string, string>();
  for (const item of candidates.cases) {
    for (const ref of [item.judgment, ...item.also_published_as]) names.set(ref.canonical_uri, ref.citation);
  }
  for (const ref of found ?? []) names.set(ref.canonical_uri, ref.citation);

  const dirty = !sameLabels(labels, saved);
  const problems = approvalProblems(labels);
  const unsavable = filterProblems(labels);
  const retired = question.status === "retired";
  const set = (patch: Partial<Labels>) => setLabels((current) => ({ ...current, ...patch }));

  async function act(name: string, call: () => Promise<{ ok: boolean } & Partial<Problem>>) {
    setBusy(name);
    setProblem(null);
    const result = await call();
    setBusy(null);
    if (result.ok) startRefresh(() => router.refresh());
    else setProblem({ code: result.code ?? "error", message: result.message ?? "" });
  }

  async function runPreview() {
    setBusy("preview");
    setProblem(null);
    const result = await previewAnswer(question.id);
    setBusy(null);
    if (result.ok) setPreview(result.data);
    else setProblem(result);
  }

  async function runLookup() {
    if (!lookup.trim()) return;
    setBusy("lookup");
    const result = await findJudgment(lookup.trim());
    setBusy(null);
    if (result.ok) setFound(result.data.cases.map((c) => c.judgment));
    else setProblem(result);
  }

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{question.id}</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Status: <strong>{question.status}</strong> · version {question.version}
          {question.reviewed_by && ` · approved by ${question.reviewed_by}`}
        </p>
      </header>

      <section aria-labelledby="labels" className="space-y-3">
        <h2 id="labels" className="font-semibold">Question and labels</h2>
        <label className="block text-sm">
          Question
          <textarea
            value={labels.question}
            onChange={(e) => set({ question: e.target.value })}
            maxLength={1000}
            rows={3}
            disabled={retired}
            className={field}
          />
        </label>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-6">
          <label className="text-sm sm:col-span-2">
            Category
            <select
              value={labels.category}
              onChange={(e) => set({ category: e.target.value as Labels["category"] })}
              disabled={retired}
              className={field}
            >
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Court
            <input value={labels.court} onChange={(e) => set({ court: e.target.value })} disabled={retired} className={field} />
          </label>
          <label className="text-sm">
            Jurisdiction
            <input value={labels.jurisdiction} onChange={(e) => set({ jurisdiction: e.target.value })} disabled={retired} className={field} />
          </label>
          <label className="text-sm">
            From year
            <input value={labels.year_from} onChange={(e) => set({ year_from: e.target.value })} disabled={retired} inputMode="numeric" className={field} />
          </label>
          <label className="text-sm">
            To year
            <input value={labels.year_to} onChange={(e) => set({ year_to: e.target.value })} disabled={retired} inputMode="numeric" className={field} />
          </label>
        </div>
        <label className="block text-sm">
          Judge
          <input value={labels.judge} onChange={(e) => set({ judge: e.target.value })} disabled={retired} className={field} />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={labels.expect_no_answer}
            onChange={(e) => set({ expect_no_answer: e.target.checked })}
            disabled={retired}
          />
          The system should give no answer (the corpus does not answer this question)
        </label>
        <label className="block text-sm">
          Notes
          <textarea value={labels.notes} onChange={(e) => set({ notes: e.target.value })} maxLength={5000} rows={2} disabled={retired} className={field} />
        </label>
      </section>

      <section aria-labelledby="gold" className="space-y-2">
        <h2 id="gold" className="font-semibold">Gold cases and passages</h2>
        {labels.gold_canonical_uris.length === 0 ? (
          <p className="text-sm text-zinc-500">No gold case marked yet.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {labels.gold_canonical_uris.map((uri) => (
              <li key={uri}>
                <span className="font-medium">{names.get(uri) ?? uri}</span>{" "}
                <button type="button" disabled={retired} className="text-xs underline" onClick={() => setLabels(toggleCase(labels, uri))}>
                  remove
                </button>
                <ul className="mt-1 space-y-1 pl-4">
                  {labels.gold_passages
                    .filter((p) => p.canonical_uri === uri)
                    .map((p) => (
                      <li key={p.text} className="border-l-2 border-emerald-500 pl-2 text-xs">
                        <span className="line-clamp-3 whitespace-pre-line">{p.text}</span>
                        <button type="button" disabled={retired} className="underline" onClick={() => setLabels(togglePassage(labels, uri, p.text))}>
                          remove passage
                        </button>
                      </li>
                    ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <input
            value={lookup}
            onChange={(e) => setLookup(e.target.value)}
            placeholder="Add a case by citation, e.g. [2021] GHASC 1"
            aria-label="Citation"
            className={field}
          />
          <button type="button" className={button} disabled={retired || busy !== null} onClick={runLookup}>
            Find
          </button>
        </div>
        {found && (
          <ul className="space-y-1 text-sm">
            {found.length === 0 && <li>No judgment found for that citation.</li>}
            {found.map((ref) => (
              <li key={ref.canonical_uri} className="flex items-center gap-2">
                <button
                  type="button"
                  className="text-xs underline"
                  disabled={retired || labels.gold_canonical_uris.includes(ref.canonical_uri)}
                  onClick={() => setLabels(toggleCase(labels, ref.canonical_uri))}
                >
                  Add as gold case
                </button>
                <span>{ref.citation}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {problem && <ErrorPanel code={problem.code} detail={problem.message} />}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={primary} disabled={retired || !dirty || unsavable.length > 0 || busy !== null} onClick={() => act("save", () => saveQuestion(question.id, toDraft(labels), question.version))}>
          Save
        </button>
        <button
          type="button"
          className={primary}
          disabled={question.status !== "draft" || dirty || problems.length > 0 || busy !== null}
          onClick={() => act("approve", () => changeStatus(question.id, "approve", question.version))}
        >
          Approve
        </button>
        {question.status !== "draft" && (
          <button type="button" className={button} disabled={busy !== null} onClick={() => act("reopen", () => changeStatus(question.id, "reopen", question.version))}>
            Reopen
          </button>
        )}
        {!retired && (
          <button type="button" className={button} disabled={busy !== null} onClick={() => act("retire", () => changeStatus(question.id, "retire", question.version))}>
            Retire
          </button>
        )}
        <button type="button" className={button} disabled={busy !== null} onClick={runPreview}>
          {busy === "preview" ? "Answering…" : "Preview answer"}
        </button>
        {busy && busy !== "preview" && <span className="text-sm text-zinc-500">Working…</span>}
      </div>
      {unsavable.length > 0 && (
        <ul role="alert" aria-label="Cannot save" className="list-disc pl-5 text-sm text-red-700 dark:text-red-300">
          {unsavable.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      {dirty && <p className="text-sm text-amber-700 dark:text-amber-300">Unsaved changes: save before approving. Preview and candidates use the saved question.</p>}
      {!dirty && question.status === "draft" && problems.length > 0 && (
        <ul aria-label="Before approving" className="list-disc pl-5 text-sm text-amber-700 dark:text-amber-300">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}

      {preview && (
        <section aria-labelledby="preview" className="space-y-2 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <h2 id="preview" className="font-semibold">What the system answers now</h2>
          <AnswerView response={preview} />
        </section>
      )}

      <section aria-labelledby="candidates" className="space-y-4">
        <h2 id="candidates" className="font-semibold">What search finds now</h2>
        {candidates.cases.length === 0 && <p className="text-sm">Search finds nothing for this question.</p>}
        {candidates.cases.map((item) => {
          const uri = item.judgment.canonical_uri;
          const gold = labels.gold_canonical_uris.includes(uri);
          return (
            <article key={uri} className={`rounded-lg border p-4 ${gold ? "border-emerald-500" : "border-zinc-200 dark:border-zinc-800"}`}>
              <div className="flex items-start justify-between gap-3">
                <JudgmentHeading judgment={item.judgment} />
                <label className="flex shrink-0 items-center gap-1 text-sm">
                  <input type="checkbox" checked={gold} disabled={retired} onChange={() => setLabels(toggleCase(labels, uri))} />
                  Gold case
                </label>
              </div>
              <ul className="mt-3 space-y-3">
                {item.passages.map((passage) => (
                  <Passage
                    key={passage.chunk_id}
                    uri={uri}
                    text={passage.excerpt}
                    labels={labels}
                    onToggle={(u, t) => !retired && setLabels(togglePassage(labels, u, t))}
                  />
                ))}
              </ul>
            </article>
          );
        })}
        <Attribution attribution={candidates.attribution} notice={candidates.notice} />
      </section>

      <section aria-labelledby="history" className="space-y-1 text-sm">
        <h2 id="history" className="font-semibold">History</h2>
        <ul className="space-y-0.5 text-zinc-600 dark:text-zinc-400">
          {history.map((entry) => (
            <li key={`${entry.created_at}-${entry.action}`}>
              {new Date(entry.created_at).toLocaleString("en-GB")}: {entry.action}
              {entry.user && ` by ${entry.user}`}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
