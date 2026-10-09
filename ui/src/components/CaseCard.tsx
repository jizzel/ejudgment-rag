import Link from "next/link";

import type { CaseResult } from "@/lib/types";
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

export function CaseCard({ result, query }: { result: CaseResult; query: string }) {
  return (
    <article className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-start justify-between gap-3">
        <JudgmentHeading judgment={result.judgment} />
        <span className="shrink-0 rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-900 dark:bg-sky-900/40 dark:text-sky-100">
          {MATCH[result.match_type] ?? result.match_type}
        </span>
      </div>
      {result.also_published_as.length > 0 && (
        <p className="mt-1 text-xs text-zinc-500">
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
      <ul className="mt-3 space-y-3">
        {result.passages.map((passage) => (
          <li key={passage.chunk_id} className="border-l-2 border-zinc-200 pl-3 dark:border-zinc-700">
            <p className="line-clamp-6 whitespace-pre-line text-sm leading-relaxed">
              <Highlighted segments={highlightTerms(passage.excerpt, query)} />
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
              <PageBadge
                status={passage.page_reference_status}
                start={passage.page_start}
                end={passage.page_end}
              />
              <Link href={`/passages/${passage.chunk_id}`} className="underline underline-offset-2">
                Read in context
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </article>
  );
}
