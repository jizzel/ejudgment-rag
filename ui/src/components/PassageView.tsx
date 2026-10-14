import Link from "next/link";

import type { PassageContext } from "@/lib/types";

import { EvidencePanel } from "./EvidencePanel";
import { textLink, touchTarget } from "./ui";

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
    // Edge to edge on phones (like the evidence sheet), a card from sm up.
    <div className="-mx-4 -mt-6 border-b border-line bg-surface px-4 py-4 sm:mx-auto sm:mt-0 sm:max-w-3xl sm:rounded-lg sm:border sm:p-5">
      <EvidencePanel
        context={context}
        mark={quote ? { quote } : null}
        level="h2"
        toolbar={
          back ? (
            <Link href={back} className={`${textLink} ${touchTarget} text-sm`}>
              ← Back to results
            </Link>
          ) : undefined
        }
      />
    </div>
  );
}
