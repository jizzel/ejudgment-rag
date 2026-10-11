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
      <span className="rounded bg-accent-soft px-1.5 py-0.5 text-xs font-medium text-ink">
        {label}
      </span>
    );
  }
  return (
    <span
      className="rounded bg-line px-1.5 py-0.5 text-xs text-muted"
      title={UNVERIFIED[status] ?? "No verified page"}
    >
      No verified page
    </span>
  );
}
