import { callApi } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { ChatResponse } from "@/lib/types";

/** Proxies the browser's question to the API (server-side; the API URL stays private). */
export async function POST(request: Request): Promise<Response> {
  const body: unknown = await request.json().catch(() => null);
  if (body === null || typeof body !== "object") {
    return Response.json(
      { error: { code: "invalid_request", message: "Expected a JSON body" } },
      { status: 422 },
    );
  }
  try {
    const response = await callApi<ChatResponse>("/v1/chat", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return Response.json(response);
  } catch (error) {
    if (error instanceof ApiError) {
      return Response.json(
        { error: { code: error.code, message: error.message } },
        { status: error.status },
      );
    }
    throw error;
  }
}
