import type { Metadata } from "next";
import Link from "next/link";

import { Suspense } from "react";

import { Attribution } from "@/components/Attribution";
import { UserMenu } from "@/components/UserMenu";

import "./globals.css";

export const metadata: Metadata = {
  title: "E-Judgment research",
  description:
    "Search and source-grounded answers over Ghanaian judgments from GhaLII (CC BY-NC 4.0).",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <header className="border-b border-zinc-200 dark:border-zinc-800">
          <nav aria-label="Main" className="mx-auto flex max-w-4xl items-center gap-6 px-4 py-3">
            <Link href="/" className="font-semibold">
              E-Judgment research
            </Link>
            <Link href="/" className="text-sm hover:underline">
              Search
            </Link>
            <Link href="/ask" className="text-sm hover:underline">
              Ask
            </Link>
            <Suspense fallback={null}>
              <UserMenu />
            </Suspense>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-zinc-200 dark:border-zinc-800">
          <div className="mx-auto max-w-4xl px-4 py-4">
            <Attribution />
          </div>
        </footer>
      </body>
    </html>
  );
}
