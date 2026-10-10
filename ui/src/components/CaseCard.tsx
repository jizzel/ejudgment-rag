import type { MouseEvent } from "react";

import type { CaseResult, PassageResult } from "@/lib/types";
import { highlightTerms } from "@/lib/text";

import { Highlighted } from "./Highlighted";
import { JudgmentHeading } from "./JudgmentHeading";
import { PageBadge } from "./PageBadge";

const MATCH: Record<string, string> = {
  citation: "Exact citation",
  case_name: "Case name",
  lexical: "Keyword",
  dense: "Meaning",
  hybrid: "Keyword + meaning",
};

type Select = (chunkId: string, event: MouseEvent<HTMLAnchorElement>) => void;

function Excerpt({
  passage,
  query,
  href,
  selected,
  onSelect,
  clamp,
}: {
  passage: PassageResult;
  query: string;
  href: string;
  selected: boolean;
  onSelect?: Select;
  clamp: boolean;
}) {
  return (
    <div
      aria-current={selected ? "true" : undefined}
      className={`border-l-2 pl-3 transition-colors motion-reduce:transition-none ${selected ? "border-accent" : "border-line"}`}
    >
      <p className={`reading ${clamp ? "line-clamp-6" : ""}`}>
        <Highlighted segments={highlightTerms(passage.excerpt, query)} />
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <PageBadge status={passage.page_reference_status} start={passage.page_start} end={passage.page_end} />
        <a
          href={href}
          onClick={onSelect ? (event) => onSelect(passage.chunk_id, event) : undefined}
          data-chunk={passage.chunk_id}
          className="inline-flex min-h-6 items-center font-medium text-accent underline underline-offset-2"
        >
          {selected ? "Shown in context" : "Show in context"}
        </a>
      </div>
    </div>
  );
}

/** One case: its best passage at reading size; further matches folded underneath. */
export function CaseCard({
  result,
  query,
  hrefFor,
  selected = null,
  onSelect,
}: {
  result: CaseResult;
  query: string;
  hrefFor: (chunkId: string) => string;
  selected?: string | null;
  onSelect?: Select;
}) {
  const [best, ...more] = result.passages;
  const isSelected = result.passages.some((p) => p.chunk_id === selected);
  const excerpt = (passage: PassageResult, clamp: boolean) => (
    <Excerpt
      key={passage.chunk_id}
      passage={passage}
      query={query}
      href={hrefFor(passage.chunk_id)}
      selected={passage.chunk_id === selected}
      onSelect={onSelect}
      clamp={clamp}
    />
  );
  return (
    <article
      aria-current={isSelected ? "true" : undefined}
      className={`rounded-lg border bg-surface p-4 transition-shadow motion-reduce:transition-none ${isSelected ? "border-accent shadow-[0_0_0_1px_var(--accent)]" : "border-line"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <JudgmentHeading judgment={result.judgment} />
        <span className="shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-xs text-ink">
          {MATCH[result.match_type] ?? result.match_type}
        </span>
      </div>
      {result.also_published_as.length > 0 && (
        <p className="mt-1 text-xs text-muted">
          Also published as:{" "}
          {result.also_published_as.map((ref, index) => (
            <span key={ref.judgment_id}>
              {index > 0 && "; "}
              <a href={ref.source_url} target="_blank" rel="noopener noreferrer" className="underline">
                {ref.citation}
              </a>
            </span>
          ))}
        </p>
      )}
      {best && <div className="mt-3">{excerpt(best, true)}</div>}
      {more.length > 0 && (
        <details
          className="group mt-3"
          // Opened for a selected passage, but never closed by us: the reader keeps their place.
          ref={(element) => {
            if (element && more.some((p) => p.chunk_id === selected)) element.open = true;
          }}
        >
          <summary className="inline-flex min-h-8 items-center text-sm text-accent">
            <span className="mr-1.5 inline-block transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden>
              ›
            </span>
            {more.length} more matching {more.length === 1 ? "passage" : "passages"}
          </summary>
          <div className="mt-2 space-y-3">{more.map((p) => excerpt(p, false))}</div>
        </details>
      )}
    </article>
  );
}
