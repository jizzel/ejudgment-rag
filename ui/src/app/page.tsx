import Link from "next/link";
import { Suspense } from "react";

import { CaseCard } from "@/components/CaseCard";
import { ErrorPanel } from "@/components/ErrorPanel";
import { SearchForm, type SearchFormValues } from "@/components/SearchForm";
import { api } from "@/lib/api";
import { attempt } from "@/lib/errors";
import { redirectIfSignedOut, sessionToken } from "@/lib/session";
import { buildSearchRequest, pageHref, PAGE_SIZE, type Params } from "@/lib/search";
import type { CourtInfo } from "@/lib/types";

async function loadCourts(token: string | undefined): Promise<CourtInfo[] | null> {
  const result = await attempt(api.courts(token));
  return result.ok ? result.value.courts : null; // without courts the form shows a text field
}

function currentPath(params: Params): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string") query.set(key, value);
  }
  const text = query.toString();
  return text ? `/?${text}` : "/";
}

async function SearchPanel({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const values: SearchFormValues = {
    q: params.q as string | undefined,
    court: params.court as string | undefined,
    year_from: params.year_from as string | undefined,
    year_to: params.year_to as string | undefined,
    judge: params.judge as string | undefined,
  };
  const token = await sessionToken();
  const courts = await loadCourts(token);
  return (
    <div className="space-y-6">
      <SearchForm values={values} courts={courts} />
      <Results params={params} token={token} />
    </div>
  );
}

async function Results({ params, token }: { params: Params; token: string | undefined }) {
  const built = buildSearchRequest(params);
  if (!built) return null;
  if (!built.ok) return <ErrorPanel code={built.error.code} detail={built.error.message} />;
  const { request, page } = built;
  const result = await attempt(api.search(request, token));
  if (!result.ok) {
    redirectIfSignedOut(result.error, currentPath(params));
    return <ErrorPanel code={result.error.code} detail={result.error.message} />;
  }
  const response = result.value;
  const info = response.query_info;
  const previous = page > 1 ? pageHref(params, page - 1) : null;
  const next = pageHref(params, page + 1);
  return (
    <section aria-labelledby="results" className="space-y-4">
      <h2 id="results" className="sr-only">Results</h2>
      {info.degraded && (
        <p role="status" className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          Results may be incomplete: {info.degraded_reason}
        </p>
      )}
      {response.cases.length === 0 ? (
        <p className="text-sm">
          No judgments matched. The corpus may not cover this; absence here does not mean
          absence in Ghanaian law.
        </p>
      ) : (
        response.cases.map((item) => (
          <CaseCard key={item.judgment.judgment_id} result={item} query={request.query} />
        ))
      )}
      <nav aria-label="Pages" className="flex justify-between text-sm">
        {previous ? <Link href={previous}>← Previous</Link> : <span />}
        {next && response.cases.length === PAGE_SIZE ? <Link href={next}>Next →</Link> : <span />}
      </nav>
    </section>
  );
}

export default function SearchPage({ searchParams }: PageProps<"/">) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Search Ghanaian judgments</h1>
      <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
        <SearchPanel searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
