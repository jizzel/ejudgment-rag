import Link from "next/link";

import { logout } from "@/app/actions";
import { canReview } from "@/lib/review";
import { currentUser } from "@/lib/session";
import type { UserInfo } from "@/lib/types";

import { SearchLink } from "./SearchLink";

const navLink = "inline-flex min-h-10 items-center rounded-md px-2 text-sm hover:bg-accent-soft";

function Links({ me }: { me: UserInfo }) {
  return (
    <>
      <SearchLink className={navLink}>Search</SearchLink>
      <Link href="/ask" className={navLink}>
        Ask
      </Link>
      {canReview(me.role) && (
        <Link href="/review" className={navLink}>
          Review
        </Link>
      )}
    </>
  );
}

function SignOut({ me }: { me: UserInfo }) {
  return (
    <form action={logout} className="flex items-center gap-3 text-sm">
      <span className="truncate text-muted">{me.display_name}</span>
      <button type="submit" className="inline-flex min-h-10 items-center rounded-md px-2 underline underline-offset-2">
        Sign out
      </button>
    </form>
  );
}

/** The site navigation: inline from `sm` up; a menu (works without JS) on small screens.
 * The Review link is shown to reviewers and admins only (the API enforces it). Signed out (or
 * before the session is known) there is nothing to navigate to: only the brand shows. */
export function SiteNav({ me }: { me: UserInfo | null }) {
  if (!me) return null;
  return (
    <>
      <nav aria-label="Main" className="hidden flex-1 items-center gap-1 sm:flex">
        <Links me={me} />
        <div className="ml-auto">
          <SignOut me={me} />
        </div>
      </nav>
      <details className="group relative ml-auto sm:hidden">
        <summary aria-label="Menu" className="inline-flex min-h-10 min-w-10 items-center justify-center rounded-md border border-line bg-surface text-lg">
          <span aria-hidden>☰</span>
        </summary>
        <nav
          aria-label="Main"
          className="absolute right-0 z-50 mt-2 flex w-56 flex-col gap-1 rounded-lg border border-line bg-surface p-2 shadow-lg"
        >
          <Links me={me} />
          <div className="mt-1 border-t border-line pt-2">
            <SignOut me={me} />
          </div>
        </nav>
      </details>
    </>
  );
}

export async function UserMenu() {
  return <SiteNav me={await currentUser()} />;
}
