import Link from "next/link";

import type { PassageContext } from "@/lib/types";

import { EvidencePanel } from "./EvidencePanel";
import { textLink } from "./ui";

/** The standalone passage page: the evidence panel, with a way back to the search it came
 * from (only a same-site path, already checked with safeNext). */
export function PassageView({
  context,
  quote,
  back = null,
}: {
  context: PassageContext;
  quote?: string;
  back?: string | null;
}) {
  return (
    <div className="mx-auto max-w-3xl rounded-lg border border-line bg-surface p-5">
      <EvidencePanel
        context={context}
        mark={quote ? { quote } : null}
        level="h2"
        toolbar={
          back ? (
            <Link href={back} className={`${textLink} text-sm`}>
              ← Back to results
            </Link>
          ) : undefined
        }
      />
    </div>
  );
}
