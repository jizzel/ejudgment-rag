"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createQuestion } from "@/app/review/actions";
import { CATEGORY_LABELS, label } from "@/lib/labels";
import { CATEGORIES } from "@/lib/review";
import type { GoldDraft } from "@/lib/types";

import { ErrorPanel } from "./ErrorPanel";
import { field, primaryButton } from "./ui";


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
            <option key={c} value={c}>
              {label(CATEGORY_LABELS, c)}
            </option>
          ))}
        </select>
      </label>
      {error && <ErrorPanel code={error.code} detail={error.message} />}
      <button
        type="submit"
        disabled={busy}
        className={primaryButton}
      >
        Create draft
      </button>
    </form>
  );
}
