import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { Attribution } from "@/components/Attribution";
import { SiteNav, UserMenu } from "@/components/UserMenu";

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
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2">
            <Link href="/" className="shrink-0 font-serif text-lg font-semibold whitespace-nowrap">
              <span aria-hidden>E-Judgment</span>
              <span className="sr-only">E-Judgment research</span>
            </Link>
            <Suspense fallback={<SiteNav me={null} />}>
              <UserMenu />
            </Suspense>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-line">
          <div className="mx-auto max-w-7xl px-4 py-4">
            <Attribution />
          </div>
        </footer>
      </body>
    </html>
  );
}
