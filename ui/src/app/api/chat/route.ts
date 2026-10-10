import { cookies } from "next/headers";

import { apiBase } from "@/lib/api";
import { isSameOrigin, SESSION_COOKIE } from "@/lib/auth";
import { errorFromBody } from "@/lib/errors";
import { STREAM_HEADERS } from "@/lib/sse";

function error(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status });
}

/**
 * Proxies the browser's question to the API's answer stream with the user's session
 * (server-side; the API URL and the token never reach page scripts). The browser's abort
 * signal is passed on, so cancelling in the page cancels the answer in the API.
 */
export async function POST(request: Request): Promise<Response> {
  // SameSite=Lax already keeps the cookie off cross-site POSTs; also refuse foreign origins.
  if (!isSameOrigin(request)) {
    return error(403, "forbidden_origin", "Cross-site requests are not accepted");
  }
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return error(401, "unauthenticated", "Sign in to continue");
  const body: unknown = await request.json().catch(() => null);
  if (body === null || typeof body !== "object") {
    return error(422, "invalid_request", "Expected a JSON body");
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase()}/v1/chat/stream`, {
      method: "POST",
      cache: "no-store",
      headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
      signal: request.signal,
    });
  } catch {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    return error(503, "api_unreachable", "The research API is not reachable");
  }
  if (!upstream.ok || !upstream.body) {
    const data: unknown = await upstream.json().catch(() => null);
    const failure = errorFromBody(upstream.status, data);
    return error(failure.status, failure.code, failure.message);
  }
  return new Response(upstream.body, { status: 200, headers: STREAM_HEADERS });
}
