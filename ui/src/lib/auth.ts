/** Pure sign-in helpers (no Next.js request context), shared by pages, actions and proxy. */

export const SESSION_COOKIE = "ej_session";

/**
 * A post-login destination that stays on this site: a single leading "/" and no scheme,
 * protocol-relative ("//host") or backslash tricks. Anything else goes to "/".
 */
export function safeNext(next: string | null | undefined): string {
  if (!next || typeof next !== "string") return "/";
  if (!next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  if (/[\u0000-\u001f]/.test(next)) return "/";
  if (next === "/login" || next.startsWith("/login?") || next.startsWith("/login/")) return "/";
  return next;
}

export function loginHref(next: string): string {
  const target = safeNext(next);
  return target === "/" ? "/login" : `/login?next=${encodeURIComponent(target)}`;
}

/**
 * Cookie settings for the session token. HttpOnly (scripts cannot read it), SameSite=Lax
 * (not sent on cross-site POSTs), Secure unless UI_INSECURE_COOKIES=1 (plain-http local use).
 */
export function sessionCookieOptions(expires: Date, insecure = process.env.UI_INSECURE_COOKIES === "1") {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: !insecure,
    path: "/",
    expires,
  };
}

/**
 * Whether a state-changing request comes from this site's own pages: its Origin must equal
 * the request's own origin. Requests without an Origin header are refused.
 */
export function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!host) return false;
  const proto =
    request.headers.get("x-forwarded-proto") ?? new URL(request.url).protocol.replace(":", "");
  return origin === `${proto}://${host}`;
}
