import type { ContextPassage, PassageContext } from "@/lib/types";
import { highlightQuote } from "@/lib/text";

import { Attribution } from "./Attribution";
import { Highlighted } from "./Highlighted";
import { JudgmentHeading } from "./JudgmentHeading";
import { PageBadge } from "./PageBadge";

function Passage({ passage, quote, focus }: { passage: ContextPassage; quote?: string; focus?: boolean }) {
  return (
    <section
      aria-current={focus ? "true" : undefined}
      className={
        focus
          ? "rounded-lg border-2 border-sky-400 p-4 dark:border-sky-600"
          : "rounded-lg border border-zinc-200 p-4 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400"
      }
    >
      <div className="mb-2 flex items-center gap-2 text-xs">
        <span className="text-zinc-500">Passage {passage.ordinal + 1}</span>
        <PageBadge status={passage.page_reference_status} start={passage.page_start} end={passage.page_end} />
      </div>
      <p className="whitespace-pre-line text-sm leading-relaxed">
        {quote ? (
          <Highlighted segments={highlightQuote(passage.excerpt, quote)} />
        ) : (
          passage.excerpt
        )}
      </p>
    </section>
  );
}

export function PassageView({ context, quote }: { context: PassageContext; quote?: string }) {
  return (
    <article className="space-y-4">
      <JudgmentHeading judgment={context.judgment} level="h2" />
      {context.before.map((passage) => (
        <Passage key={passage.chunk_id} passage={passage} />
      ))}
      <Passage passage={context.passage} quote={quote} focus />
      {context.after.map((passage) => (
        <Passage key={passage.chunk_id} passage={passage} />
      ))}
      <Attribution attribution={context.attribution} notice={context.notice} />
    </article>
  );
}
