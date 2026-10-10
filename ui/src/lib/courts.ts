import "server-only";

import { api } from "./api";
import { attempt } from "./errors";
import { redirectIfSignedOut } from "./session";
import type { CourtInfo } from "./types";

/**
 * Courts for the filter. A signed-out session (401) goes to sign-in, even on a page that makes
 * no other API call; any other failure falls back to a text field (null).
 */
export async function loadCourts(token: string | undefined, next: string): Promise<CourtInfo[] | null> {
  const result = await attempt(api.courts(token));
  if (result.ok) return result.value.courts;
  redirectIfSignedOut(result.error, next);
  return null;
}
