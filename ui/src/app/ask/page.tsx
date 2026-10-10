import { Suspense } from "react";

import { AskForm } from "@/components/AskForm";
import { loadCourts } from "@/lib/courts";
import { sessionToken } from "@/lib/session";

async function AskWithCourts() {
  return <AskForm courts={await loadCourts(await sessionToken(), "/ask")} />;
}

export default function AskPage() {
  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="font-serif text-3xl font-semibold">Ask a question</h1>
        <p className="mt-1 text-sm text-muted">
          Answers are built only from statements that quote a retrieved judgment and are checked
          against it. Where the judgments found do not answer the question, you get the cases to
          check instead of an answer.
        </p>
      </div>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <AskWithCourts />
      </Suspense>
    </div>
  );
}
