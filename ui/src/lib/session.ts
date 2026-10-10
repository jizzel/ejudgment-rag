import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { loginHref, SESSION_COOKIE } from "./auth";
import type { ApiError } from "./errors";

/** The signed-in user's session token from the HttpOnly cookie, if any. */
export async function sessionToken(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

/** Sends the user to sign in when the API says the session is missing or over. */
export function redirectIfSignedOut(error: ApiError, next: string): void {
  if (error.status === 401) redirect(loginHref(next));
}
