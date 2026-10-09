import Link from "next/link";

import type { ChatResponse } from "@/lib/types";

import { Attribution } from "./Attribution";
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

function Limitations({ response }: { response: ChatResponse }) {
  if (response.limitations.length === 0 && !response.model_limitations) return null;
  return (
    <section aria-labelledby="limitations" className="space-y-2 text-sm">
      <h2 id="limitations" className="font-semibold">Limitations</h2>
      {response.limitations.length > 0 && (
        <ul className="list-disc space-y-1 pl-5">
          {response.limitations.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
      {response.model_limitations && (
        <p className="rounded-md bg-zinc-50 p-3 dark:bg-zinc-900">
          <span className="block text-xs font-medium uppercase tracking-wide text-zinc-500">
            Model-written, not verified
          </span>
          {response.model_limitations}
        </p>
      )}
    </section>
  );
}

export function AnswerView({ response }: { response: ChatResponse }) {
  const generation = response.generation;
  return (
    <div className="space-y-6">
      {response.abstained ? (
        <section role="status" className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/40">
          <h2 className="font-semibold">No answer</h2>
          <p className="mt-1 text-sm">
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
          <h2 id="answer" className="font-semibold">Answer</h2>
          {response.claims.map((claim, index) => (
            <div key={index} className="space-y-2">
              <p className="leading-relaxed">
                <span className="mr-2 rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                  {KIND[claim.kind] ?? claim.kind}
                </span>
                {claim.text}
                {claim.source_numbers.map((number) => (
                  <sup key={number} className="ml-0.5">
                    <a href={`#source-${number}`} aria-label={`Source ${number}`} className="font-medium text-sky-700 underline dark:text-sky-300">
                      [{number}]
                    </a>
                  </sup>
                ))}
              </p>
              <blockquote className="border-l-2 border-zinc-300 pl-3 text-sm italic text-zinc-700 dark:border-zinc-600 dark:text-zinc-300">
                “{claim.quote}”
                <span className="ml-2 not-italic">
                  {claim.pinpoint && (
                    <span className="mr-2 rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100">
                      {claim.pinpoint}
                    </span>
                  )}
                  <Link href={passageHref(claim.quote_chunk_id, claim.quote)} className="text-xs underline">
                    See the quote in context
                  </Link>
                </span>
              </blockquote>
            </div>
          ))}
        </section>
      )}

      {response.sources.length > 0 && (
        <section aria-labelledby="sources" className="space-y-3">
          <h2 id="sources" className="font-semibold">Sources</h2>
          <ol className="space-y-3">
            {response.sources.map((source) => (
              <li key={source.number} id={`source-${source.number}`} className="flex gap-3 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                <span className="font-semibold">[{source.number}]</span>
                <div className="min-w-0 flex-1 space-y-2">
                  <JudgmentHeading judgment={source.judgment} />
                  <ul className="flex flex-wrap gap-2 text-xs">
                    {source.passages.map((passage) => (
                      <li key={passage.chunk_id} className="flex items-center gap-1">
                        <PageBadge status={passage.page_reference_status} start={passage.page_start} end={passage.page_end} />
                        <Link href={passageHref(passage.chunk_id)} className="underline">
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

      <Limitations response={response} />

      {generation && (
        <p className="text-xs text-zinc-500">
          Answered by {generation.provider} {generation.model} in{" "}
          {(generation.latency_ms / 1000).toFixed(1)} s · checked by {generation.support_model} ·
          prompt {generation.prompt_version}
        </p>
      )}
      <Attribution attribution={response.attribution} notice={response.notice} />
    </div>
  );
}
