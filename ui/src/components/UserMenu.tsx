import Link from "next/link";

import { logout } from "@/app/actions";
import { canReview } from "@/lib/review";
import { currentUser } from "@/lib/session";
import type { UserInfo } from "@/lib/types";

/** The review link (reviewers and admins only), the signed-in user and a sign-out button. */
export function UserMenuView({ me }: { me: UserInfo }) {
  return (
    <>
      {canReview(me.role) && (
        <Link href="/review" className="text-sm hover:underline">
          Review
        </Link>
      )}
      <form action={logout} className="ml-auto flex items-center gap-3 text-sm">
        <span className="text-zinc-600 dark:text-zinc-400">{me.display_name}</span>
        <button type="submit" className="underline underline-offset-2">
          Sign out
        </button>
      </form>
    </>
  );
}

/** Nothing when signed out. */
export async function UserMenu() {
  const me = await currentUser();
  return me ? <UserMenuView me={me} /> : null;
}
