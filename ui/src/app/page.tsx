import Link from "next/link";
import { Suspense } from "react";

import { ErrorPanel } from "@/components/ErrorPanel";
import { ResultsSkeleton, SearchFormSkeleton } from "@/components/ResultsSkeleton";
import { SearchForm, type FieldErrors, type SearchFormValues } from "@/components/SearchForm";
import { SearchWorkspace } from "@/components/SearchWorkspace";
import { textLink } from "@/components/ui";
import { api } from "@/lib/api";
import { loadCourts } from "@/lib/courts";
import { attempt } from "@/lib/errors";
import { restoredEvidence } from "@/lib/evidence";
import {
  buildSearchRequest,
  EXAMPLES,
  FilterError,
  openPassage,
  pageHref,
  PAGE_SIZE,
  withPassage,
  type Params,
} from "@/lib/search";
import { redirectIfSignedOut, sessionToken } from "@/lib/session";
import type { SearchRequest } from "@/lib/types";

function text(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value : undefined;
}

async function Search({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const values: SearchFormValues = {
    q: text(params.q),
    court: text(params.court),
    year_from: text(params.year_from),
    year_to: text(params.year_to),
    judge: text(params.judge),
  };
  const token = await sessionToken();
  const courts = await loadCourts(token, withPassage(params, null));
  const built = buildSearchRequest(params);
  const errors: FieldErrors =
    built && !built.ok && built.error instanceof FilterError ? { [built.error.field]: built.error.message } : {};

  if (!built) {
    return (
      <div className="mx-auto max-w-3xl space-y-8 pt-6 sm:pt-12">
        <div className="space-y-2">
          <h1 className="font-serif text-3xl font-semibold sm:text-4xl">Search Ghanaian judgments</h1>
          <p className="text-muted">
            Find judgments by citation, case name, words or a legal question, and read each
            passage in its judgment.
          </p>
        </div>
        <SearchForm values={values} courts={courts} errors={errors} />
        <div>
          <h2 className="text-sm font-medium text-muted">Try</h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <li key={example.q}>
                <Link
                  href={`/?q=${encodeURIComponent(example.q)}`}
                  className="inline-flex min-h-9 items-center rounded-full border border-line bg-surface px-3 text-sm hover:border-accent"
                >
                  <span className="mr-1.5 text-muted">{example.label}:</span>
                  {example.q}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="sr-only">Search results</h1>
        <SearchForm values={values} courts={courts} errors={errors} />
      </div>
      {built.ok ? (
        <Suspense key={JSON.stringify(built.request)} fallback={<ResultsSkeleton />}>
          <Results params={params} request={built.request} page={built.page} token={token} />
        </Suspense>
      ) : (
        !(built.error instanceof FilterError) && <ErrorPanel code={built.error.code} detail={built.error.message} />
      )}
    </div>
  );
}

async function Results({
  params,
  request,
  page,
  token,
}: {
  params: Params;
  request: SearchRequest;
  page: number;
  token: string | undefined;
}) {
  const chunkId = openPassage(params);
  const [result, passage] = await Promise.all([
    attempt(api.search(request, token)),
    chunkId ? attempt(api.passage(chunkId, token, 2)) : Promise.resolve(null),
  ]);
  if (!result.ok) {
    redirectIfSignedOut(result.error, withPassage(params, chunkId));
    return <ErrorPanel code={result.error.code} detail={result.error.message} />;
  }
  if (passage && !passage.ok) redirectIfSignedOut(passage.error, withPassage(params, chunkId));
  const response = result.value;
  const info = response.query_info;
  const previous = page > 1 ? pageHref(params, page - 1) : null;
  const next = pageHref(params, page + 1);
  return (
    <div className="space-y-4">
      {info.degraded && (
        <p role="status" className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          Results may be incomplete: {info.degraded_reason}
        </p>
      )}
      {/* Always rendered: a shared passage opens even if the search now finds nothing. */}
      <SearchWorkspace response={response} params={params} initial={restoredEvidence(chunkId, passage)} />
      <nav aria-label="Pages" className="flex max-w-3xl justify-between text-sm">
        {previous ? <Link href={previous} className={`${textLink} inline-flex min-h-8 items-center`}>← Previous</Link> : <span />}
        {next && response.cases.length === PAGE_SIZE ? <Link href={next} className={`${textLink} inline-flex min-h-8 items-center`}>Next →</Link> : <span />}
      </nav>
    </div>
  );
}

export default function SearchPage({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<SearchFormSkeleton />}>
      <Search searchParams={searchParams} />
    </Suspense>
  );
}
