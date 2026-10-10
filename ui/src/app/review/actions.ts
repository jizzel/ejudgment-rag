"use server";

import { callApi } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { sessionToken } from "@/lib/session";
import type { ChatResponse, GoldDraft, SearchResponse } from "@/lib/types";

export type ActionResult<T> = { ok: true; data: T } | { ok: false; code: string; message: string };

async function run<T>(path: string, init?: RequestInit): Promise<ActionResult<T>> {
  try {
    return { ok: true, data: await callApi<T>(path, init, await sessionToken()) };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, code: error.code, message: error.message };
    throw error;
  }
}

const id = (questionId: string) => encodeURIComponent(questionId);

export async function createQuestion(draft: GoldDraft) {
  return run<{ id: string }>("/v1/review/questions", { method: "POST", body: JSON.stringify(draft) });
}

export async function saveQuestion(questionId: string, draft: GoldDraft, version: number) {
  return run<null>(`/v1/review/questions/${id(questionId)}`, {
    method: "PUT",
    body: JSON.stringify({ ...draft, version }),
  });
}

export async function changeStatus(
  questionId: string,
  action: "approve" | "reopen" | "retire",
  version: number,
) {
  return run<null>(`/v1/review/questions/${id(questionId)}/${action}`, {
    method: "POST",
    body: JSON.stringify({ version }),
  });
}

export async function previewAnswer(questionId: string) {
  return run<ChatResponse>(`/v1/review/questions/${id(questionId)}/preview-answer`, { method: "POST" });
}

export async function findJudgment(citation: string) {
  return run<SearchResponse>(`/v1/review/judgments?citation=${encodeURIComponent(citation)}`);
}
