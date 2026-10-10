import { NextResponse, type NextRequest } from "next/server";

import { loginHref, SESSION_COOKIE } from "@/lib/auth";

/**
 * Optimistic check only: without a session cookie, pages go to /login and the chat proxy
 * answers 401. Whether a session is valid is decided by the API on every call.
 */
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const { pathname, search } = request.nextUrl;
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { error: { code: "unauthenticated", message: "Sign in to continue" } },
      { status: 401 },
    );
  }
  return NextResponse.redirect(new URL(loginHref(`${pathname}${search}`), request.url));
}

export const config = {
  // Everything except the sign-in page, Next's own assets and the favicon.
  matcher: ["/((?!login|_next/static|_next/image|favicon.ico).*)"],
};
