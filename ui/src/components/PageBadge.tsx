import { pageLabel } from "@/lib/text";

const UNVERIFIED: Record<string, string> = {
  unknown: "No page numbers (text without page mapping)",
  pending: "Pages not verified",
};

/** A pinpoint only for verified pages; otherwise say why there is none. */
export function PageBadge({
  status,
  start,
  end,
}: {
  status: string;
  start?: number | null;
  end?: number | null;
}) {
  const label = pageLabel(status, start, end);
  if (label) {
    return (
      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100">
        {label}
      </span>
    );
  }
  return (
    <span
      className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
      title={UNVERIFIED[status] ?? "No verified page"}
    >
      No verified page
    </span>
  );
}
