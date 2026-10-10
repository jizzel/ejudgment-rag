import { cookies } from "next/headers";

import { callApi } from "@/lib/api";
import { isSameOrigin, SESSION_COOKIE } from "@/lib/auth";
import { ApiError } from "@/lib/errors";
import type { ChatResponse } from "@/lib/types";

function error(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status });
}

/** Proxies the browser's question to the API with the user's session (server-side; the API
 * URL and the token never reach page scripts). */
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
  try {
    const response = await callApi<ChatResponse>(
      "/v1/chat",
      { method: "POST", body: JSON.stringify(body) },
      token,
    );
    return Response.json(response);
  } catch (caught) {
    if (caught instanceof ApiError) return error(caught.status, caught.code, caught.message);
    throw caught;
  }
}
