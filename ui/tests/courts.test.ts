import { afterEach, describe, expect, it, vi } from "vitest";

const courts = vi.fn();
vi.mock("@/lib/api", () => ({ api: { courts: (...args: unknown[]) => courts(...args) } }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`NEXT_REDIRECT ${url}`);
  },
}));

import { loadCourts } from "@/lib/courts";
import { ApiError } from "@/lib/errors";

afterEach(() => courts.mockReset());

describe("court list for the filters", () => {
  it("returns the courts", async () => {
    courts.mockResolvedValue({ courts: [{ court_code: "ghasc", court_name: "Supreme Court", judgments: 3 }] });
    expect(await loadCourts("tok", "/")).toHaveLength(1);
    expect(courts).toHaveBeenCalledWith("tok");
  });

  it("sends an ended session to sign in, even on a page with no other API call", async () => {
    courts.mockRejectedValue(new ApiError(401, "unauthenticated", "expired"));
    await expect(loadCourts("old", "/?court=ghasc")).rejects.toThrow(
      "NEXT_REDIRECT /login?next=%2F%3Fcourt%3Dghasc",
    );
  });

  it("falls back to a text field when the API fails for another reason", async () => {
    courts.mockRejectedValue(new ApiError(503, "database_unavailable", "down"));
    expect(await loadCourts("tok", "/")).toBeNull();
  });
});
