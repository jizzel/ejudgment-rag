import Link from "next/link";
import type { MouseEvent } from "react";

import type { ChatResponse } from "@/lib/types";

import { JudgmentHeading } from "./JudgmentHeading";
import { PageBadge } from "./PageBadge";

const ABSTAIN: Record<string, string> = {
  no_results: "No passages in the corpus matched this question.",
  model_abstained: "The passages found do not answer this question.",
  no_supported_claims:
    "No statement could be verified against the cited passages, so none is shown.",
  invalid_model_output: "The answer model returned an unusable answer.",
};

const KIND: Record<string, string> = {
  holding: "Holding",
  obiter: "Obiter",
  fact: "Facts",
  inference: "Inference",
};

export function passageHref(chunkId: string, quote?: string): string {
  return quote
    ? `/passages/${chunkId}?quote=${encodeURIComponent(quote)}`
    : `/passages/${chunkId}`;
}

/** A claim chosen through one of its source markers ([n]) or, with source null, its quote. */
type SelectClaim = (index: number, source: number | null, event: MouseEvent<HTMLAnchorElement>) => void;

/** Notes about the answer and how it was made; folded so the answer comes first. */
function AnswerDetails({ response }: { response: ChatResponse }) {
  const generation = response.generation;
  if (!generation && !response.model_limitations) return null;
  return (
    <details className="group rounded-lg border border-line bg-surface p-3 text-sm">
      <summary className="inline-flex min-h-8 items-center text-accent">
        <span className="mr-1.5 inline-block transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden>
          ›
        </span>
        Answer details
      </summary>
      <div className="mt-2 space-y-3">
        {response.model_limitations && (
          <p>
            <span className="block text-xs font-medium tracking-wide text-muted uppercase">
              Model-written, not verified
            </span>
            {response.model_limitations}
          </p>
        )}
        {generation && (
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs text-muted">
            <dt>Answer model</dt>
            <dd className="[overflow-wrap:anywhere]">
              {generation.provider} {generation.model} ({(generation.latency_ms / 1000).toFixed(1)} s)
            </dd>
            <dt>Checked by</dt>
            <dd className="[overflow-wrap:anywhere]">{generation.support_model}</dd>
            <dt>Prompt</dt>
            <dd>{generation.prompt_version}</dd>
          </dl>
        )}
      </div>
    </details>
  );
}

/**
 * A verified answer, answer first. With `onSelectClaim`, choosing a claim's source marker or
 * quote opens its passage beside the answer (the links still work without JS), and the claim
 * and its sources are marked together.
 */
export function AnswerView({
  response,
  selectedClaim = null,
  selectedSource = null,
  onSelectClaim,
}: {
  response: ChatResponse;
  selectedClaim?: number | null;
  selectedSource?: number | null;
  onSelectClaim?: SelectClaim;
}) {
  const active = selectedClaim === null ? null : response.claims[selectedClaim];
  // A marker selects its own source; the quote link selects all the claim's sources.
  const activeSources = new Set(selectedSource !== null ? [selectedSource] : (active?.source_numbers ?? []));
  const select = (index: number, source: number | null) =>
    onSelectClaim
      ? (event: MouseEvent<HTMLAnchorElement>) => onSelectClaim(index, source, event)
      : undefined;
  return (
    <div className="space-y-6">
      {response.abstained ? (
        <section role="status" className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/40">
          <h2 className="font-semibold">No answer</h2>
          <p className="mt-1">
            {ABSTAIN[response.abstain_reason ?? ""] ?? "No verified answer could be given."}
          </p>
          {response.matched_cases.length > 0 && (
            <div className="mt-3">
              <h3 className="text-sm font-medium">Cases you may want to check</h3>
              <ul className="mt-2 space-y-2">
                {response.matched_cases.map((judgment) => (
                  <li key={judgment.judgment_id}>
                    <JudgmentHeading judgment={judgment} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      ) : (
        <section aria-labelledby="answer" className="space-y-4">
          <h2 id="answer" className="font-serif text-xl font-semibold">Answer</h2>
          {response.claims.map((claim, index) => (
            <div
              key={index}
              aria-current={index === selectedClaim ? "true" : undefined}
              className={`space-y-2 rounded-lg border-l-4 py-1 pl-4 transition-colors motion-reduce:transition-none ${index === selectedClaim ? "border-accent bg-accent-soft/40" : "border-transparent"}`}
            >
              <p className="text-[1.05rem] leading-relaxed">
                <span className="mr-2 rounded bg-accent-soft px-1.5 py-0.5 text-xs font-medium tracking-wide uppercase">
                  {KIND[claim.kind] ?? claim.kind}
                </span>
                {claim.text}
                {claim.source_numbers.map((number) => (
                  <sup key={number} className="ml-0.5">
                    <a
                      href={`#source-${number}`}
                      onClick={select(index, number)}
                      data-claim={index}
                      data-source={number}
                      aria-label={`Source ${number}`}
                      className="inline-flex min-h-6 min-w-6 items-center justify-center font-medium text-accent underline"
                    >
                      [{number}]
                    </a>
                  </sup>
                ))}
              </p>
              <blockquote className="border-l-2 border-line pl-3 text-muted italic">
                “{claim.quote}”
                <span className="ml-2 not-italic">
                  {claim.pinpoint && (
                    <span className="mr-2 rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100">
                      {claim.pinpoint}
                    </span>
                  )}
                  <Link
                    href={passageHref(claim.quote_chunk_id, claim.quote)}
                    onClick={select(index, null)}
                    data-claim={index}
                    data-source="quote"
                    className="text-xs text-accent underline"
                  >
                    See the quote in context
                  </Link>
                </span>
              </blockquote>
            </div>
          ))}
        </section>
      )}

      {response.limitations.length > 0 && (
        <section aria-labelledby="limitations" className="space-y-2 text-sm">
          <h2 id="limitations" className="font-semibold">Limitations</h2>
          <ul className="list-disc space-y-1 pl-5">
            {response.limitations.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </section>
      )}

      {response.sources.length > 0 && (
        <section aria-labelledby="sources" className="space-y-3">
          <h2 id="sources" className="font-semibold">Sources</h2>
          <ol className="space-y-3">
            {response.sources.map((source) => (
              <li
                key={source.number}
                id={`source-${source.number}`}
                aria-current={activeSources.has(source.number) ? "true" : undefined}
                className={`flex gap-3 rounded-lg border bg-surface p-3 transition-colors motion-reduce:transition-none ${activeSources.has(source.number) ? "border-accent" : "border-line"}`}
              >
                <span className="font-semibold">[{source.number}]</span>
                <div className="min-w-0 flex-1 space-y-2">
                  <JudgmentHeading judgment={source.judgment} />
                  <ul className="flex flex-wrap gap-2 text-xs">
                    {source.passages.map((passage) => (
                      <li key={passage.chunk_id} className="flex items-center gap-1">
                        <PageBadge status={passage.page_reference_status} start={passage.page_start} end={passage.page_end} />
                        <Link href={passageHref(passage.chunk_id)} className="text-accent underline">
                          Read passage
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      <AnswerDetails response={response} />
    </div>
  );
}
