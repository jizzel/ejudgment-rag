import type { MouseEvent } from "react";

import { highlightTerms } from "@/lib/text";
import type { ChatStage, PassageResult } from "@/lib/types";

import { Highlighted } from "./Highlighted";
import { JudgmentHeading } from "./JudgmentHeading";
import { quietButton } from "./ui";

export type Progress = {
  stage: ChatStage;
  passages: PassageResult[];
  claims: number | null;
};

type Step = { label: string; state: "done" | "active" | "pending" };

const ORDER: ChatStage[] = ["searching", "drafting", "checking"];

/** The steps of an answer so far, from the server's stage events. */
export function progressSteps(progress: Progress): Step[] {
  const at = ORDER.indexOf(progress.stage);
  const state = (index: number): Step["state"] => (index < at ? "done" : index === at ? "active" : "pending");
  const cases = new Set(progress.passages.map((p) => p.judgment.canonical_uri)).size;
  const passages = progress.passages.length;
  return [
    { label: "Searching the judgments", state: state(0) },
    ...(passages > 0
      ? [
          {
            label: `Found ${passages} ${passages === 1 ? "passage" : "passages"} in ${cases} ${cases === 1 ? "judgment" : "judgments"}`,
            state: "done" as const,
          },
        ]
      : []),
    { label: "Drafting the answer from those passages", state: state(1) },
    {
      label:
        progress.claims === null
          ? "Checking each statement against its source"
          : progress.claims === 1
            ? "Checking 1 statement against its source"
            : `Checking ${progress.claims} statements against their sources`,
      state: state(2),
    },
  ];
}

const MARK: Record<Step["state"], string> = { done: "✓", active: "…", pending: "" };

/**
 * Progress while an answer is prepared: the real stages, the passages the model is reading
 * (each can be read in context), and a way to stop.
 */
export function AnswerProgress({
  progress,
  question,
  elapsed,
  selected,
  onSelect,
  onCancel,
}: {
  progress: Progress;
  question: string;
  elapsed: number;
  selected: string | null;
  onSelect: (chunkId: string, event: MouseEvent<HTMLAnchorElement>) => void;
  onCancel: () => void;
}) {
  const steps = progressSteps(progress);
  const current = steps.find((step) => step.state === "active") ?? steps[steps.length - 1];
  const byCase = new Map<string, PassageResult[]>();
  for (const passage of progress.passages) {
    const list = byCase.get(passage.judgment.canonical_uri) ?? [];
    list.push(passage);
    byCase.set(passage.judgment.canonical_uri, list);
  }
  return (
    <section aria-labelledby="progress" className="space-y-5">
      <div className="rounded-lg border border-line bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="progress" className="font-semibold">
            Preparing the answer <span className="font-normal text-muted">({elapsed} s)</span>
          </h2>
          <button type="button" onClick={onCancel} className={quietButton}>
            Cancel
          </button>
        </div>
        {/* Announce stage changes only, not the ticking clock. */}
        <p className="sr-only" aria-live="polite">
          {current.label}
        </p>
        <ol className="mt-3 space-y-1.5 text-sm">
          {steps.map((step) => (
            <li
              key={step.label}
              aria-current={step.state === "active" ? "step" : undefined}
              className={step.state === "pending" ? "text-muted" : step.state === "active" ? "font-medium" : ""}
            >
              <span aria-hidden className="mr-2 inline-block w-4 text-accent">
                {MARK[step.state]}
              </span>
              {step.label}
              {step.state === "active" && "…"}
            </li>
          ))}
        </ol>
      </div>
      {byCase.size > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-muted">The passages being read</h3>
          {[...byCase.values()].map((passages) => (
            <article key={passages[0].judgment.canonical_uri} className="rounded-lg border border-line bg-surface p-4">
              <JudgmentHeading judgment={passages[0].judgment} />
              <ul className="mt-2 space-y-2">
                {passages.map((passage) => (
                  <li
                    key={passage.chunk_id}
                    aria-current={passage.chunk_id === selected ? "true" : undefined}
                    className={`border-l-2 pl-3 ${passage.chunk_id === selected ? "border-accent" : "border-line"}`}
                  >
                    <p className="line-clamp-3 text-sm leading-relaxed whitespace-pre-line">
                      <Highlighted segments={highlightTerms(passage.excerpt, question)} />
                    </p>
                    <a
                      href={`/passages/${passage.chunk_id}`}
                      data-chunk={passage.chunk_id}
                      onClick={(event) => onSelect(passage.chunk_id, event)}
                      className="inline-flex min-h-6 items-center text-xs font-medium text-accent underline underline-offset-2"
                    >
                      Show in context
                    </a>
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
