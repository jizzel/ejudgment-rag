/** Server-sent events: a pure, incremental parser (text in, messages out). */
import type { ChatStreamEvent } from "./types";

/** Event-stream headers: no caching, and no compression or proxy buffering in between. */
export const STREAM_HEADERS = {
  "content-type": "text/event-stream; charset=utf-8",
  "cache-control": "no-cache, no-transform",
  "x-accel-buffering": "no",
};

export type SseMessage = { event: string; data: string };

/** Feed it text chunks as they arrive; it returns the messages completed so far. A message may
 * span chunks, and one chunk may hold several. Comment lines (":") are ignored. */
export class SseParser {
  private buffer = "";

  push(chunk: string): SseMessage[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const blocks = this.buffer.split("\n\n");
    this.buffer = blocks.pop() ?? "";
    const messages: SseMessage[] = [];
    for (const block of blocks) {
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line === "" || line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "event") event = value;
        else if (field === "data") data.push(value);
      }
      if (data.length > 0) messages.push({ event, data: data.join("\n") });
    }
    return messages;
  }
}

const KNOWN = new Set(["stage", "sources", "answer", "error"]);

/** A chat stream event, or null for anything unknown or malformed (ignored, never guessed). */
export function chatEvent(message: SseMessage): ChatStreamEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(message.data);
  } catch {
    return null;
  }
  const type = (value as { type?: unknown } | null)?.type;
  if (typeof type !== "string" || !KNOWN.has(type) || type !== message.event) return null;
  return value as ChatStreamEvent;
}
