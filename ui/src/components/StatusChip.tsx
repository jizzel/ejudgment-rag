import { STATUS_LABELS, label } from "@/lib/labels";

const STYLE: Record<string, string> = {
  draft: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100",
  approved: "bg-accent-soft text-ink",
  retired: "bg-line text-muted",
};

/** A gold question's status, readable and colour-coded. */
export function StatusChip({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${STYLE[status] ?? "bg-line text-ink"}`}>
      {label(STATUS_LABELS, status)}
    </span>
  );
}
