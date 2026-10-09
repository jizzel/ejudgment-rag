import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/chat/route";

import { answered } from "./fixtures";

function post(body: unknown) {
  return POST(
    new Request("http://ui.test/api/chat", {
      method: "POST",
      body: typeof body === "string" ? body : JSON.stringify(body),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("chat proxy", () => {
  it("forwards the question to the configured API and returns its answer", async () => {
    vi.stubEnv("EJUDGMENT_API_URL", "http://api.test:9000/");
    const fetchMock = vi.fn(async () => Response.json(answered));
    vi.stubGlobal("fetch", fetchMock);
    const response = await post({ question: "q", filters: { court: "ghasc" } });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(answered);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test:9000/v1/chat");
    expect(JSON.parse(String(init.body))).toEqual({ question: "q", filters: { court: "ghasc" } });
  });

  it("passes the API's error code and status through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ error: { code: "budget_exhausted", message: "limit" } }, { status: 429 }),
      ),
    );
    const response = await post({ question: "q" });
    expect(response.status).toBe(429);
    expect((await response.json()).error.code).toBe("budget_exhausted");
  });

  it("reports an unreachable API and rejects a bad body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("connect ECONNREFUSED");
      }),
    );
    const down = await post({ question: "q" });
    expect(down.status).toBe(503);
    expect((await down.json()).error.code).toBe("api_unreachable");
    expect((await post("not json")).status).toBe(422);
  });
});
