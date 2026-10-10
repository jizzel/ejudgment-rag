import type { ReactNode } from "react";

import { highlightQuote, highlightTerms } from "@/lib/text";
import type { ContextPassage, PassageContext } from "@/lib/types";

import { Highlighted } from "./Highlighted";
import { JudgmentHeading } from "./JudgmentHeading";
import { PageBadge } from "./PageBadge";

/** What to mark in the passage: a verified quote (answers) or the query's terms (search). */
export type Mark = { quote: string } | { terms: string } | null;

function segments(text: string, mark: Mark) {
  if (mark && "quote" in mark) return highlightQuote(text, mark.quote);
  if (mark && "terms" in mark) return highlightTerms(text, mark.terms);
  return [{ text, mark: false }];
}

function Neighbours({ label, passages }: { label: string; passages: ContextPassage[] }) {
  if (passages.length === 0) return null;
  return (
    <details className="group rounded-md border border-dashed border-line">
      <summary className="flex min-h-10 items-center px-3 text-sm text-accent">
        <span className="mr-2 inline-block transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden>
          ›
        </span>
        {label} ({passages.length} {passages.length === 1 ? "passage" : "passages"})
      </summary>
      <div className="space-y-3 px-3 pb-3">
        {passages.map((passage) => (
          <div key={passage.chunk_id} className="text-muted">
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
              <span>Passage {passage.ordinal + 1}</span>
              <PageBadge status={passage.page_reference_status} start={passage.page_start} end={passage.page_end} />
            </div>
            <p className="reading">{passage.excerpt}</p>
          </div>
        ))}
      </div>
    </details>
  );
}

/**
 * A passage read in its judgment: the case (with its GhaLII link), the selected passage first
 * and in full, and the neighbouring text on demand (already loaded, so no request). Text only.
 */
export function EvidencePanel({
  context,
  mark,
  toolbar,
  level = "h2",
}: {
  context: PassageContext;
  mark: Mark;
  toolbar?: ReactNode;
  level?: "h2" | "h3";
}) {
  const { passage } = context;
  return (
    <article aria-label="Evidence" className="space-y-4">
      {toolbar}
      <JudgmentHeading judgment={context.judgment} level={level} />
      <Neighbours label="Show earlier text" passages={context.before} />
      <section aria-current="true" aria-label="Selected passage" className="rounded-lg border-l-4 border-accent bg-accent-soft/40 py-3 pr-3 pl-4">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted">Passage {passage.ordinal + 1}</span>
          <PageBadge status={passage.page_reference_status} start={passage.page_start} end={passage.page_end} />
        </div>
        <p className="reading">
          <Highlighted segments={segments(passage.excerpt, mark)} />
        </p>
      </section>
      <Neighbours label="Show later text" passages={context.after} />
      <p className="text-xs text-muted">{context.attribution}</p>
    </article>
  );
}
