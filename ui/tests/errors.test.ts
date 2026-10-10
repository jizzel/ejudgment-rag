import { describe, expect, it, vi } from "vitest";

import { streamQuestion } from "@/lib/chat-stream";
import { ApiError, attempt, errorFromBody, errorMessage } from "@/lib/errors";

describe("error mapping", () => {
  it("keeps the API's stable code and message", () => {
    const error = errorFromBody(429, { error: { code: "budget_exhausted", message: "run spent $1" } });
    expect([error.status, error.code, error.message]).toEqual([429, "budget_exhausted", "run spent $1"]);
    expect(errorFromBody(502, "<html>bad gateway</html>").code).toBe("http_502");
  });

  it("has a readable message for each code the API documents", () => {
    for (const code of [
      "llm_unavailable",
      "verifier_unavailable",
      "budget_exhausted",
      "database_unavailable",
      "api_unreachable",
      "query_empty",
      "invalid_filter",
      "invalid_request",
    ]) {
      expect(errorMessage(code)).not.toBe("Something went wrong.");
    }
    expect(errorMessage("brand_new_code", "from the API")).toBe("from the API");
  });

  it("the browser client reports API errors and an unreachable server", async () => {
    const failing = vi.fn(async () =>
      Response.json({ error: { code: "llm_unavailable", message: "Ollama down" } }, { status: 503 }),
    );
    const ask = (fetcher: typeof fetch) => streamQuestion({ question: "q" }, { fetcher, onProgress: () => {} });
    await expect(ask(failing)).rejects.toMatchObject({
      code: "llm_unavailable",
      status: 503,
    });
    const offline = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const error = await ask(offline).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("api_unreachable");
  });
});

describe("attempt", () => {
  it("turns API errors into values and lets other errors through", async () => {
    expect(await attempt(Promise.resolve(3))).toEqual({ ok: true, value: 3 });
    const failed = await attempt(Promise.reject(new ApiError(404, "passage_not_found", "gone")));
    expect(failed.ok ? null : failed.error.code).toBe("passage_not_found");
    await expect(attempt(Promise.reject(new TypeError("bug")))).rejects.toThrow("bug");
  });
});
