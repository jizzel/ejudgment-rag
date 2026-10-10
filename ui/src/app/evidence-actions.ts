"use server";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { UUID } from "@/lib/search";
import { sessionToken } from "@/lib/session";
import type { PassageContext } from "@/lib/types";

export type PassageResult =
  | { ok: true; context: PassageContext }
  | { ok: false; status: number; code: string; message: string };

/** A passage with its neighbours, for the evidence panel (the API call stays server-side). */
export async function loadPassage(chunkId: string): Promise<PassageResult> {
  if (!UUID.test(chunkId)) {
    return { ok: false, status: 404, code: "passage_not_found", message: "No such passage" };
  }
  try {
    return { ok: true, context: await api.passage(chunkId, await sessionToken(), 2) };
  } catch (error) {
    if (error instanceof ApiError) {
      return { ok: false, status: error.status, code: error.code, message: error.message };
    }
    throw error;
  }
}
