import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ErrorPanel } from "@/components/ErrorPanel";
import { PassageView } from "@/components/PassageView";
import { api } from "@/lib/api";
import { attempt } from "@/lib/errors";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function Passage({
  params,
  searchParams,
}: {
  params: Promise<{ chunkId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { chunkId } = await params;
  const { quote } = await searchParams;
  if (!UUID.test(chunkId)) notFound();
  const result = await attempt(api.passage(chunkId, 2));
  if (!result.ok) {
    if (result.error.status === 404) notFound();
    return <ErrorPanel code={result.error.code} detail={result.error.message} />;
  }
  return (
    <PassageView context={result.value} quote={typeof quote === "string" ? quote : undefined} />
  );
}

export default function PassagePage({ params, searchParams }: PageProps<"/passages/[chunkId]">) {
  return (
    <Suspense fallback={<p className="text-sm text-zinc-500">Loading passage…</p>}>
      <Passage params={params} searchParams={searchParams} />
    </Suspense>
  );
}
