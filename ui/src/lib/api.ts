import "server-only";

import { ApiError, errorFromBody } from "./errors";
import type {
  ChatRequest,
  ChatResponse,
  CourtsResponse,
  LoginResponse,
  PassageContext,
  ReviewDetail,
  ReviewList,
  SearchRequest,
  SearchResponse,
  UserInfo,
} from "./types";

/** Server-side only: the browser never learns where the API runs. */
export function apiBase(): string {
  return (process.env.EJUDGMENT_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

/** Calls the API with the user's session token (sent as a bearer token, server-side only). */
export async function callApi<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBase()}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        "content-type": "application/json",
        ...(token ? { authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(503, "api_unreachable", "The research API is not reachable");
  }
  if (response.status === 204) return null as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw errorFromBody(response.status, body);
  }
  return body as T;
}

export const api = {
  search: (request: SearchRequest, token?: string) =>
    callApi<SearchResponse>("/v1/search", { method: "POST", body: JSON.stringify(request) }, token),
  chat: (request: ChatRequest, token?: string) =>
    callApi<ChatResponse>("/v1/chat", { method: "POST", body: JSON.stringify(request) }, token),
  passage: (chunkId: string, token?: string, context = 2) =>
    callApi<PassageContext>(
      `/v1/passages/${encodeURIComponent(chunkId)}?context=${context}`,
      undefined,
      token,
    ),
  courts: (token?: string) => callApi<CourtsResponse>("/v1/courts", undefined, token),
  login: (email: string, password: string) =>
    callApi<LoginResponse>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: (token: string) => callApi<null>("/v1/auth/logout", { method: "POST" }, token),
  me: (token: string) => callApi<UserInfo>("/v1/auth/me", undefined, token),
  reviewList: (token: string | undefined, params: URLSearchParams) =>
    callApi<ReviewList>(`/v1/review/questions?${params.toString()}`, undefined, token),
  reviewDetail: (token: string | undefined, questionId: string) =>
    callApi<ReviewDetail>(`/v1/review/questions/${encodeURIComponent(questionId)}`, undefined, token),
};
