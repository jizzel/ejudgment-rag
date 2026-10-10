import type { Segment } from "@/lib/text";

/** Renders text segments; marked ones become <mark>. Text only, never HTML. */
export function Highlighted({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((segment, index) =>
        segment.mark ? (
          <mark key={index} className="rounded-sm bg-mark px-0.5 text-inherit">
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  );
}
