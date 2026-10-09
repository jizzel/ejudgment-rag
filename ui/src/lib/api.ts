import "server-only";

import { ApiError, errorFromBody } from "./errors";
import type {
  ChatRequest,
  ChatResponse,
  CourtsResponse,
  PassageContext,
  SearchRequest,
  SearchResponse,
} from "./types";

/** Server-side only: the browser never learns where the API runs. */
export function apiBase(): string {
  return (process.env.EJUDGMENT_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

export async function callApi<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBase()}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "content-type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(503, "api_unreachable", "The research API is not reachable");
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw errorFromBody(response.status, body);
  }
  return body as T;
}

export const api = {
  search: (request: SearchRequest) =>
    callApi<SearchResponse>("/v1/search", { method: "POST", body: JSON.stringify(request) }),
  chat: (request: ChatRequest) =>
    callApi<ChatResponse>("/v1/chat", { method: "POST", body: JSON.stringify(request) }),
  passage: (chunkId: string, context = 2) =>
    callApi<PassageContext>(
      `/v1/passages/${encodeURIComponent(chunkId)}?context=${context}`,
    ),
  courts: () => callApi<CourtsResponse>("/v1/courts"),
};
