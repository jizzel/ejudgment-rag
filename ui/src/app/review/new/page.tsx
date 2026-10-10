import Link from "next/link";

import { NewQuestionForm } from "@/components/NewQuestionForm";

export default function NewReviewQuestionPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link href="/review" className="text-sm underline underline-offset-2">
        ← All questions
      </Link>
      <h1 className="text-2xl font-semibold">New gold question</h1>
      <p className="text-sm text-muted">
        Write the question as a lawyer would ask it. After creating it you can mark the cases
        and passages a correct answer should rely on.
      </p>
      <NewQuestionForm />
    </div>
  );
}
