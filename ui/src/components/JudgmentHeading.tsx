import type { JudgmentRef } from "@/lib/types";
import { formatDate } from "@/lib/text";

/** Citation, court and date, with a link to the original on GhaLII. */
export function JudgmentHeading({
  judgment,
  level = "h3",
}: {
  judgment: JudgmentRef;
  level?: "h2" | "h3";
}) {
  const Heading = level;
  const date = formatDate(judgment.judgment_date);
  return (
    <div>
      <Heading className="font-semibold leading-snug">{judgment.citation}</Heading>
      <p className="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">
        {[judgment.court_name, date].filter(Boolean).join(" · ")}
        {" · "}
        <a
          href={judgment.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="underline decoration-dotted underline-offset-2 hover:text-zinc-900 dark:hover:text-zinc-100"
        >
          Original on GhaLII
        </a>
      </p>
    </div>
  );
}
