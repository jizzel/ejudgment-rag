import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { callApi } from "@/lib/api";
import { isSameOrigin, loginHref, safeNext, sessionCookieOptions } from "@/lib/auth";
import { proxy } from "@/proxy";

describe("post-login destinations stay on this site", () => {
  it.each([
    ["/ask", "/ask"],
    ["/?q=lease&court=ghasc", "/?q=lease&court=ghasc"],
    ["//evil.example/path", "/"],
    ["/\\evil.example", "/"],
    ["https://evil.example", "/"],
    ["javascript:alert(1)", "/"],
    ["/login?next=/ask", "/"],
    ["/ok\nSet-Cookie: x", "/"],
    [undefined, "/"],
  ])("%s -> %s", (next, expected) => {
    expect(safeNext(next)).toBe(expected);
  });

  it("builds the sign-in link", () => {
    expect(loginHref("/ask")).toBe("/login?next=%2Fask");
    expect(loginHref("//evil.example")).toBe("/login");
  });
});

describe("session cookie", () => {
  it("is HttpOnly, SameSite=Lax and Secure unless explicitly local", () => {
    const expires = new Date("2030-01-01T00:00:00Z");
    expect(sessionCookieOptions(expires, false)).toEqual({
      httpOnly: true,
      sameSite: "lax",
      secure: true,
      path: "/",
      expires,
    });
    expect(sessionCookieOptions(expires, true).secure).toBe(false);
  });
});

describe("same-origin check", () => {
  const request = (headers: Record<string, string>) =>
    new Request("http://ui.test/api/chat", { method: "POST", headers });

  it("accepts this site's own pages only", () => {
    expect(isSameOrigin(request({ origin: "http://ui.test", host: "ui.test" }))).toBe(true);
    expect(
      isSameOrigin(
        request({
          origin: "https://research.example.org",
          host: "ui:3000",
          "x-forwarded-host": "research.example.org",
          "x-forwarded-proto": "https",
        }),
      ),
    ).toBe(true);
    expect(isSameOrigin(request({ origin: "http://evil.test", host: "ui.test" }))).toBe(false);
    expect(isSameOrigin(request({ origin: "https://ui.test", host: "ui.test" }))).toBe(false);
    expect(isSameOrigin(request({ host: "ui.test" }))).toBe(false);
  });
});

describe("proxy (optimistic sign-in check)", () => {
  it("sends visitors without a session to sign in, keeping where they were going", () => {
    const response = proxy(new NextRequest("http://ui.test/passages/abc?quote=x"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://ui.test/login?next=%2Fpassages%2Fabc%3Fquote%3Dx",
    );
  });

  it("answers the chat proxy with 401 instead of a redirect", async () => {
    const response = proxy(new NextRequest("http://ui.test/api/chat", { method: "POST" }));
    expect(response.status).toBe(401);
    expect((await response.json()).error.code).toBe("unauthenticated");
  });

  it("lets requests with a session cookie through (the API decides if it is valid)", () => {
    const request = new NextRequest("http://ui.test/ask", { headers: { cookie: "ej_session=abc" } });
    expect(proxy(request).headers.get("x-middleware-next")).toBe("1");
  });
});

describe("API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the session as a bearer token, and nothing without one", async () => {
    const fetchMock = vi.fn(async () => Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await callApi("/v1/courts", undefined, "tok");
    await callApi("/v1/courts");
    const headers = fetchMock.mock.calls.map(
      (call) => ((call as unknown as [string, RequestInit])[1].headers as Record<string, string>).authorization,
    );
    expect(headers).toEqual(["Bearer tok", undefined]);
  });
});
