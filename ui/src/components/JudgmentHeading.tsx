import type { JudgmentRef } from "@/lib/types";
import { formatDate } from "@/lib/text";

/** Citation (serif), court and date, with a link to the original on GhaLII. */
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
    <div className="min-w-0">
      <Heading className="font-serif text-lg leading-snug font-semibold [overflow-wrap:anywhere]">
        {judgment.citation}
      </Heading>
      <p className="mt-0.5 text-sm text-muted">
        {[judgment.court_name, date].filter(Boolean).join(" · ")}
        {" · "}
        <a
          href={judgment.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent underline decoration-dotted underline-offset-2 hover:decoration-solid"
        >
          Original on GhaLII
        </a>
      </p>
    </div>
  );
}
