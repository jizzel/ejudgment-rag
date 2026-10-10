"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { safeNext, SESSION_COOKIE, sessionCookieOptions } from "@/lib/auth";
import { ApiError } from "@/lib/errors";

export type LoginState = { error?: string; email?: string };

/** Signs in through the API and keeps the session token in an HttpOnly cookie. */
export async function login(_previous: LoginState, form: FormData): Promise<LoginState> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (!email || !password) return { error: "invalid_credentials", email };
  let expires: Date;
  try {
    const session = await api.login(email, password);
    expires = new Date(session.expires_at);
    (await cookies()).set(SESSION_COOKIE, session.token, sessionCookieOptions(expires));
  } catch (caught) {
    if (caught instanceof ApiError) return { error: caught.code, email };
    throw caught;
  }
  redirect(safeNext(String(form.get("next") ?? "/")));
}

/** Ends the session at the API (best effort) and removes the cookie. */
export async function logout(): Promise<void> {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;
  if (token) {
    await api.logout(token).catch(() => undefined); // an already-ended session is fine
  }
  store.delete(SESSION_COOKIE);
  redirect("/login");
}
