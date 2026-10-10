"use client";

import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";

import { loadPassage, type PassageResult } from "@/app/evidence-actions";
import { loginHref } from "@/lib/auth";
import { LAST_SEARCH_KEY } from "@/lib/last-search";
import { withPassage, type Params } from "@/lib/search";
import type { SearchResponse } from "@/lib/types";

import { CaseCard } from "./CaseCard";
import { EvidenceColumn, type Evidence } from "./EvidenceColumn";

export function isPlainClick(event: MouseEvent): boolean {
  return !(event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0);
}

/**
 * Results with the evidence panel beside them. Opening a passage loads it through a server
 * action and records it in the URL with replaceState, so the results are not searched again
 * and the list (with its scroll position) stays as it was.
 */
export function SearchWorkspace({
  response,
  params,
  initial = { kind: "none" },
  load = loadPassage,
  navigate = (href: string) => window.location.assign(href),
}: {
  response: SearchResponse;
  params: Params;
  initial?: Evidence;
  load?: (chunkId: string) => Promise<PassageResult>;
  navigate?: (href: string) => void;
}) {
  const [evidence, setEvidence] = useState<Evidence>(initial);
  const results = useRef<HTMLElement>(null);
  const opener = useRef<string | null>(null); // the passage whose link opened the evidence
  // Where the list was when the evidence opened (a full-screen sheet on phones), and whether
  // to go back there and to the opening link once it closes.
  const listScroll = useRef(0);
  const restore = useRef(false);
  // Each selection or close takes a new number; a passage that arrives for an older one is
  // dropped (it must not reopen a closed panel or replace a newer selection).
  const request = useRef(0);
  const selected = evidence.kind === "none" ? null : evidence.chunkId;
  const here = withPassage(params, selected);

  useEffect(() => {
    try {
      sessionStorage.setItem(LAST_SEARCH_KEY, here);
    } catch {
      // storage unavailable (private mode): the Search link then starts a new search
    }
  }, [here]);

  useEffect(() => {
    if (!restore.current || selected !== null) return;
    restore.current = false;
    window.scrollTo?.({ top: listScroll.current });
    const id = opener.current;
    // After Next.js has applied the URL change (it moves focus when it does).
    const timer = setTimeout(() => {
      const link = id ? results.current?.querySelector<HTMLElement>(`a[data-chunk="${id}"]`) : null;
      link?.focus({ preventScroll: true });
    }, 50);
    return () => clearTimeout(timer);
  }, [selected]);

  async function select(chunkId: string, event: MouseEvent<HTMLAnchorElement>) {
    if (!isPlainClick(event)) return; // a new tab gets the URL
    event.preventDefault();
    opener.current = chunkId;
    if (selected === null) listScroll.current = window.scrollY;
    if (chunkId === selected && evidence.kind === "shown") return;
    const ticket = ++request.current;
    setEvidence({ kind: "loading", chunkId });
    window.history.replaceState(null, "", withPassage(params, chunkId));
    const result = await load(chunkId);
    if (ticket !== request.current) return;
    if (result.ok) {
      setEvidence({ kind: "shown", chunkId, context: result.context });
    } else if (result.status === 401) {
      navigate(loginHref(withPassage(params, chunkId)));
    } else {
      setEvidence({ kind: "error", chunkId, code: result.code, message: result.message });
    }
  }

  const close = useCallback(() => {
    request.current++;
    setEvidence({ kind: "none" });
    restore.current = true;
    window.history.replaceState(null, "", withPassage(params, null));
  }, [params]);

  return (
    <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-6">
      <section ref={results} aria-labelledby="results" className="min-w-0 space-y-4">
        <h2 id="results" className="sr-only">Results</h2>
        {response.cases.length === 0 && (
          <p className="max-w-3xl">
            No judgments matched. The corpus may not cover this; absence here does not mean
            absence in Ghanaian law.
          </p>
        )}
        {response.cases.map((item) => (
          <CaseCard
            key={item.judgment.judgment_id}
            result={item}
            query={response.query}
            hrefFor={(chunkId) => withPassage(params, chunkId)}
            selected={selected}
            onSelect={select}
          />
        ))}
      </section>
      <EvidenceColumn
        evidence={evidence}
        mark={{ terms: response.query }}
        pageHref={selected ? `/passages/${selected}?from=${encodeURIComponent(withPassage(params, null))}` : null}
        onClose={close}
        empty="Choose “Show in context” on a passage to read it here, in its judgment."
      />
    </div>
  );
}
