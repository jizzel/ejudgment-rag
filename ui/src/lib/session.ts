import "server-only";

import { cookies } from "next/headers";
import { cache } from "react";
import { redirect } from "next/navigation";

import { api } from "./api";
import { loginHref, SESSION_COOKIE } from "./auth";
import { attempt } from "./errors";
import type { ApiError } from "./errors";

/** The signed-in user's session token from the HttpOnly cookie, if any. */
export async function sessionToken(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

/** Sends the user to sign in when the API says the session is missing or over. */
export function redirectIfSignedOut(error: ApiError, next: string): void {
  if (error.status === 401) redirect(loginHref(next));
}

/** The signed-in user (once per request), or null when signed out or the API is down. */
export const currentUser = cache(async () => {
  const token = await sessionToken();
  if (!token) return null;
  const me = await attempt(api.me(token));
  return me.ok ? me.value : null;
});
