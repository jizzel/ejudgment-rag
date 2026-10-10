"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { MouseEvent, ReactNode } from "react";

import { LAST_SEARCH_KEY, lastSearch } from "@/lib/last-search";

/** "Search" returns to the last search of this tab (query, filters, open passage), if any. */
export function SearchLink({ className, children }: { className?: string; children: ReactNode }) {
  const router = useRouter();
  function onClick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    let stored: string | null = null;
    try {
      stored = sessionStorage.getItem(LAST_SEARCH_KEY);
    } catch {
      return; // no storage: a plain link to a new search
    }
    const target = lastSearch(stored);
    if (target === "/") return;
    event.preventDefault();
    router.push(target);
  }
  return (
    <Link href="/" onClick={onClick} className={className}>
      {children}
    </Link>
  );
}
