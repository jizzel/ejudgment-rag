import { logout } from "@/app/actions";
import { api } from "@/lib/api";
import { attempt } from "@/lib/errors";
import { sessionToken } from "@/lib/session";

/** The signed-in user and a sign-out button (nothing when signed out). */
export async function UserMenu() {
  const token = await sessionToken();
  if (!token) return null;
  const me = await attempt(api.me(token));
  if (!me.ok) return null;
  return (
    <form action={logout} className="ml-auto flex items-center gap-3 text-sm">
      <span className="text-zinc-600 dark:text-zinc-400">{me.value.display_name}</span>
      <button type="submit" className="underline underline-offset-2">
        Sign out
      </button>
    </form>
  );
}
