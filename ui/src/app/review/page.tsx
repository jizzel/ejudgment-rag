import Link from "next/link";
import { Suspense } from "react";

import { ErrorPanel } from "@/components/ErrorPanel";
import { api } from "@/lib/api";
import { attempt } from "@/lib/errors";
import { CATEGORIES, STATUSES } from "@/lib/review";
import { redirectIfSignedOut, sessionToken } from "@/lib/session";
import { formatDate } from "@/lib/text";

type Params = Record<string, string | string[] | undefined>;

const field =
  "rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900";

async function Questions({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const query = new URLSearchParams();
  const status = typeof params.status === "string" ? params.status : "";
  const category = typeof params.category === "string" ? params.category : "";
  if (status) query.set("status", status);
  if (category) query.set("category", category);
  const here = query.size ? `/review?${query.toString()}` : "/review";
  const result = await attempt(api.reviewList(await sessionToken(), query));
  if (!result.ok) {
    redirectIfSignedOut(result.error, here);
    return <ErrorPanel code={result.error.code} detail={result.error.message} />;
  }
  const { questions, counts } = result.value;
  const approved = counts.by_status.approved ?? 0;
  const { target } = counts;
  return (
    <div className="space-y-4">
      <p className="text-sm">
        <strong>{approved}</strong> approved of the {target.min}–{target.max} target ·{" "}
        {counts.by_status.draft ?? 0} draft · {counts.by_status.retired ?? 0} retired
      </p>
      <form className="flex flex-wrap items-end gap-3" action="/review">
        <label className="text-sm">
          Status{" "}
          <select name="status" defaultValue={status} className={field}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Category{" "}
          <select name="category" defaultValue={category} className={field}>
            <option value="">All</option>
            {CATEGORIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <button type="submit" className="rounded-md border border-zinc-300 px-3 py-1 text-sm dark:border-zinc-700">
          Filter
        </button>
      </form>
      {questions.length === 0 ? (
        <p className="text-sm">No questions match.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-zinc-500">
            <tr>
              <th className="py-1">Question</th>
              <th>Category</th>
              <th>Status</th>
              <th>Gold</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {questions.map((q) => (
              <tr key={q.id} className="border-t border-zinc-200 align-top dark:border-zinc-800">
                <td className="py-2 pr-3">
                  <Link href={`/review/${encodeURIComponent(q.id)}`} className="underline underline-offset-2">
                    {q.question}
                  </Link>
                  <span className="ml-2 text-xs text-zinc-500">{q.id}</span>
                </td>
                <td className="pr-3">{q.category}</td>
                <td className="pr-3">{q.status}</td>
                <td className="pr-3">
                  {q.gold_cases} cases, {q.gold_passages} passages
                </td>
                <td>{formatDate(q.updated_at.slice(0, 10))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function ReviewPage({ searchParams }: PageProps<"/review">) {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Gold questions</h1>
        <Link href="/review/new" className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900">
          New question
        </Link>
      </div>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        Evaluation questions with the cases and passages a correct answer should find. Only
        approved questions count as lawyer-reviewed in evaluations.
      </p>
      <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
        <Questions searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
