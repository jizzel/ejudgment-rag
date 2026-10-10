import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ErrorPanel } from "@/components/ErrorPanel";
import { PassageView } from "@/components/PassageView";
import { api } from "@/lib/api";
import { attempt } from "@/lib/errors";
import { redirectIfSignedOut, sessionToken } from "@/lib/session";
import { backTarget, UUID } from "@/lib/search";

async function Passage({
  params,
  searchParams,
}: {
  params: Promise<{ chunkId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { chunkId } = await params;
  const { quote, from } = await searchParams;
  if (!UUID.test(chunkId)) notFound();
  const result = await attempt(api.passage(chunkId, await sessionToken(), 2));
  if (!result.ok) {
    const here = `/passages/${chunkId}${typeof quote === "string" ? `?quote=${encodeURIComponent(quote)}` : ""}`;
    redirectIfSignedOut(result.error, here);
    if (result.error.status === 404) notFound();
    return <ErrorPanel code={result.error.code} detail={result.error.message} />;
  }
  return (
    <PassageView
      context={result.value}
      quote={typeof quote === "string" ? quote : undefined}
      back={backTarget(from)}
    />
  );
}

export default function PassagePage({ params, searchParams }: PageProps<"/passages/[chunkId]">) {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading passage…</p>}>
      <Passage params={params} searchParams={searchParams} />
    </Suspense>
  );
}
