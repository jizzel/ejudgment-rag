import { CATEGORY_LABELS, label } from "@/lib/labels";
import type { ReviewList } from "@/lib/types";

/** Review progress: approved questions against the 50–100 target, and per category. */
export function ReviewProgress({ counts }: { counts: ReviewList["counts"] }) {
  const approved = counts.by_status.approved ?? 0;
  const { min, max } = counts.target;
  const percent = Math.min(100, Math.round((approved / max) * 100));
  const goal = Math.round((min / max) * 100);
  const byCategory = Object.entries(counts.approved_by_category);
  return (
    <section aria-label="Review progress" className="space-y-3 rounded-lg border border-line bg-surface p-4">
      <p className="text-sm">
        <strong className="font-serif text-2xl">{approved}</strong> approved of the {min}–{max}{" "}
        target · {counts.by_status.draft ?? 0} draft · {counts.by_status.retired ?? 0} retired
      </p>
      <div
        role="meter"
        aria-label="Approved questions"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={approved}
        aria-valuetext={`${approved} approved; the target is ${min} to ${max}`}
        className="relative h-2 rounded-full bg-line"
      >
        <div className="h-2 rounded-full bg-accent" style={{ width: `${percent}%` }} />
        {/* The minimum target, marked on the bar. */}
        <div aria-hidden className="absolute -top-1 h-4 w-0.5 bg-ink/60" style={{ left: `${goal}%` }} />
      </div>
      <div aria-hidden className="relative h-4 text-xs text-muted">
        <span className="absolute -translate-x-1/2" style={{ left: `${goal}%` }}>
          {min} minimum
        </span>
        <span className="absolute right-0">{max}</span>
      </div>
      {byCategory.length > 0 && (
        <ul aria-label="Approved by category" className="flex flex-wrap gap-2 text-xs">
          {byCategory.map(([category, count]) => (
            <li key={category} className="rounded-full bg-accent-soft px-2 py-0.5">
              {label(CATEGORY_LABELS, category)}: {count}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
