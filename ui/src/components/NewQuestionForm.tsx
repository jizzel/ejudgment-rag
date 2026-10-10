"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createQuestion } from "@/app/review/actions";
import { CATEGORIES } from "@/lib/review";
import type { GoldDraft } from "@/lib/types";

import { ErrorPanel } from "./ErrorPanel";

const field =
  "w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900";

export function NewQuestionForm() {
  const router = useRouter();
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const draft: GoldDraft = {
      question: String(form.get("question") ?? "").trim(),
      category: String(form.get("category")) as GoldDraft["category"],
      expect_no_answer: false,
    };
    setBusy(true);
    const result = await createQuestion(draft);
    setBusy(false);
    if (result.ok) router.push(`/review/${encodeURIComponent(result.data.id)}`);
    else setError(result);
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <label className="block text-sm">
        Question
        <textarea name="question" required maxLength={1000} rows={3} className={field} />
      </label>
      <label className="block text-sm">
        Category
        <select name="category" defaultValue="issue" className={field}>
          {CATEGORIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </label>
      {error && <ErrorPanel code={error.code} detail={error.message} />}
      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-zinc-900 px-4 py-2 text-sm text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
      >
        Create draft
      </button>
    </form>
  );
}
