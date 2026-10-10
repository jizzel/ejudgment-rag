import Link from "next/link";
import { Suspense } from "react";

import { ErrorPanel } from "@/components/ErrorPanel";
import { ReviewEditor } from "@/components/ReviewEditor";
import { api } from "@/lib/api";
import { attempt } from "@/lib/errors";
import { redirectIfSignedOut, sessionToken } from "@/lib/session";

async function Question({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await attempt(api.reviewDetail(await sessionToken(), id));
  if (!result.ok) {
    redirectIfSignedOut(result.error, `/review/${encodeURIComponent(id)}`);
    return <ErrorPanel code={result.error.code} detail={result.error.message} />;
  }
  const detail = result.value;
  // Remounts after every saved change, so the editor starts from the stored version.
  return <ReviewEditor key={`${detail.question.id}@${detail.question.version}`} detail={detail} />;
}

export default function ReviewQuestionPage({ params }: PageProps<"/review/[id]">) {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link href="/review" className="text-sm underline underline-offset-2">
        ← All questions
      </Link>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <Question params={params} />
      </Suspense>
    </div>
  );
}
