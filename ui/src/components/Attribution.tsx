import { ATTRIBUTION, GHALII_URL, NOTICE } from "@/lib/notices";

/** GhaLII credit and the research notice; shown with all corpus content. */
export function Attribution({ attribution = ATTRIBUTION, notice = NOTICE }: { attribution?: string; notice?: string }) {
  return (
    <div className="space-y-1 text-xs text-zinc-600 dark:text-zinc-400">
      <p>
        {attribution}{" "}
        <a href={GHALII_URL} target="_blank" rel="noopener noreferrer" className="underline">
          ghalii.org
        </a>
      </p>
      <p>{notice}</p>
    </div>
  );
}
