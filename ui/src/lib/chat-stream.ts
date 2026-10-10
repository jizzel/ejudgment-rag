/** Asks the UI server's chat proxy and reads its event stream (browser side). */
import { ApiError, errorFromBody } from "./errors";
import { chatEvent, SseParser } from "./sse";
import type { ChatResponse, ChatSourcesEvent, ChatStageEvent } from "./types";

export type ChatProgress = ChatStageEvent | ChatSourcesEvent;

/**
 * Posts the question (in the body, never the URL) and reports each progress event; resolves
 * with the answer. Rejects with the server's ApiError (an `error` event or an HTTP error),
 * `stream_interrupted` if the stream ends without an answer, or the AbortError of `signal`
 * when the reader cancels.
 */
export async function streamQuestion(
  body: Record<string, unknown>,
  {
    signal,
    onProgress,
    fetcher = fetch,
  }: { signal?: AbortSignal; onProgress: (event: ChatProgress) => void; fetcher?: typeof fetch },
): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetcher("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(503, "api_unreachable", "The research UI server is not reachable");
  }
  if (!response.ok || !response.body) {
    const data: unknown = await response.json().catch(() => null);
    throw errorFromBody(response.status, data);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      const messages = parser.push(done ? decoder.decode() : decoder.decode(value, { stream: true }));
      for (const message of messages) {
        const event = chatEvent(message);
        if (!event) continue;
        if (event.type === "answer") return event.answer;
        if (event.type === "error") throw new ApiError(502, event.error.code, event.error.message);
        onProgress(event);
      }
      if (done) break;
    }
  } catch (error) {
    if (signal?.aborted || error instanceof ApiError) throw error;
    throw new ApiError(502, "stream_interrupted", String(error));
  } finally {
    reader.releaseLock();
  }
  throw new ApiError(502, "stream_interrupted", "The answer stream ended without an answer");
}
