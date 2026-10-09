import { Suspense } from "react";

import { AskForm } from "@/components/AskForm";
import { api } from "@/lib/api";
import { attempt } from "@/lib/errors";

async function AskWithCourts() {
  const result = await attempt(api.courts());
  return <AskForm courts={result.ok ? result.value.courts : null} />;
}

export default function AskPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Ask a question</h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Answers are built only from statements that quote a retrieved judgment and are checked
          against it. Where the judgments found do not answer the question, you get the cases to
          check instead of an answer.
        </p>
      </div>
      <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
        <AskWithCourts />
      </Suspense>
    </div>
  );
}
