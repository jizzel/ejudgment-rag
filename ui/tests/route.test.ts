import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const cookieJar = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (cookieJar.has(name) ? { name, value: cookieJar.get(name) } : undefined),
  }),
}));

import { POST } from "@/app/api/chat/route";
import { SESSION_COOKIE } from "@/lib/auth";

import { answered, answerStream } from "./fixtures";

const SITE = "http://ui.test";

function post(body: unknown, headers: Record<string, string> = { origin: SITE, host: "ui.test" }) {
  return POST(
    new Request(`${SITE}/api/chat`, {
      method: "POST",
      headers,
      body: typeof body === "string" ? body : JSON.stringify(body),
    }),
  );
}

beforeEach(() => cookieJar.set(SESSION_COOKIE, "token-123"));
afterEach(() => {
  cookieJar.clear();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("chat proxy", () => {
  it("streams the API's answer events with the user's session as a bearer token", async () => {
    vi.stubEnv("EJUDGMENT_API_URL", "http://api.test:9000/");
    const fetchMock = vi.fn(async () => answerStream(answered));
    vi.stubGlobal("fetch", fetchMock);
    const response = await post({ question: "q", filters: { court: "ghasc" } });
    expect(response.status).toBe(200);
    // Event-stream headers: nothing in between may cache, compress or buffer it.
    expect(response.headers.get("content-type")).toBe("text/event-stream; charset=utf-8");
    expect(response.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(await response.text()).toContain(`event: answer\ndata: ${JSON.stringify({ type: "answer", answer: answered })}`);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test:9000/v1/chat/stream");
    expect((init.headers as Record<string, string>).authorization).toBe("Bearer token-123");
    expect(JSON.parse(String(init.body))).toEqual({ question: "q", filters: { court: "ghasc" } });
  });

  it("passes the page's abort on to the API (cancelling the answer there)", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      expect(init.signal?.aborted).toBe(false);
      return answerStream(answered);
    });
    vi.stubGlobal("fetch", fetchMock);
    const abort = new AbortController();
    await POST(
      new Request(`${SITE}/api/chat`, {
        method: "POST",
        headers: { origin: SITE, host: "ui.test" },
        body: JSON.stringify({ question: "q" }),
        signal: abort.signal,
      }),
    );
    const signal = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].signal!;
    abort.abort();
    expect(signal.aborted).toBe(true);
  });

  it("refuses cross-site requests and requests without a session", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const foreign = await post({ question: "q" }, { origin: "https://evil.example", host: "ui.test" });
    expect(foreign.status).toBe(403);
    expect((await foreign.json()).error.code).toBe("forbidden_origin");
    expect((await post({ question: "q" }, { host: "ui.test" })).status).toBe(403); // no Origin
    cookieJar.clear();
    const anonymous = await post({ question: "q" });
    expect(anonymous.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes the API's error code and status through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ error: { code: "unauthenticated", message: "expired" } }, { status: 401 }),
      ),
    );
    const response = await post({ question: "q" });
    expect(response.status).toBe(401);
    expect((await response.json()).error.code).toBe("unauthenticated");
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
