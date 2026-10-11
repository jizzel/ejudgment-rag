import Link from "next/link";
import { Suspense } from "react";

import { ErrorPanel } from "@/components/ErrorPanel";
import { ReviewProgress } from "@/components/ReviewProgress";
import { StatusChip } from "@/components/StatusChip";
import { field, primaryButton, quietButton, textLink } from "@/components/ui";
import { api } from "@/lib/api";
import { attempt } from "@/lib/errors";
import { CATEGORY_LABELS, label, STATUS_LABELS } from "@/lib/labels";
import { CATEGORIES, STATUSES } from "@/lib/review";
import { redirectIfSignedOut, sessionToken } from "@/lib/session";
import { formatDate } from "@/lib/text";

type Params = Record<string, string | string[] | undefined>;

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

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
  return (
    <div className="space-y-4">
      <ReviewProgress counts={counts} />
      <form className="flex flex-wrap items-end gap-3" action="/review">
        <label className="text-sm">
          <span className="mb-1 block text-muted">Status</span>
          <select name="status" defaultValue={status} className={field}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {label(STATUS_LABELS, s)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Category</span>
          <select name="category" defaultValue={category} className={field}>
            <option value="">All</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {label(CATEGORY_LABELS, c)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className={quietButton}>
          Filter
        </button>
      </form>
      {questions.length === 0 ? (
        <p className="text-sm">No questions match.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line bg-surface px-4">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <thead className="text-xs text-muted">
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
              <tr key={q.id} className="border-t border-line align-top">
                <td className="py-2 pr-3">
                  <Link href={`/review/${encodeURIComponent(q.id)}`} className={textLink}>
                    {q.question}
                  </Link>
                  <span className="ml-2 text-xs text-muted">{q.id}</span>
                </td>
                <td className="pr-3">{label(CATEGORY_LABELS, q.category)}</td>
                <td className="pr-3">
                  <StatusChip status={q.status} />
                </td>
                <td className="pr-3 whitespace-nowrap">
                  {count(q.gold_cases, "case")} · {count(q.gold_passages, "passage")}
                </td>
                <td className="whitespace-nowrap">{formatDate(q.updated_at.slice(0, 10))}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}

export default function ReviewPage({ searchParams }: PageProps<"/review">) {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="font-serif text-3xl font-semibold">Gold questions</h1>
        <Link href="/review/new" className={primaryButton}>
          New question
        </Link>
      </div>
      <p className="text-sm text-muted">
        Evaluation questions with the cases and passages a correct answer should find. Only
        approved questions count as lawyer-reviewed in evaluations.
      </p>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <Questions searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
