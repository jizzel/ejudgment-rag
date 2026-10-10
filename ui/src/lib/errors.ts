/** An API failure with the API's stable error code (or a UI-side one). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const MESSAGES: Record<string, string> = {
  api_unreachable: "The research API is not running or not reachable.",
  database_unavailable: "The judgment database is not reachable right now.",
  llm_unavailable:
    "The answer model is not available (is Ollama running, or is the OpenAI provider configured?). Search still works.",
  verifier_unavailable:
    "Answers are switched off because the model that checks them against the sources is not installed.",
  budget_exhausted: "The answer budget for this period is used up. Search still works.",
  query_empty: "Please enter some text.",
  unauthenticated: "Please sign in to continue.",
  invalid_credentials: "Email or password is incorrect.",
  too_many_attempts: "Too many failed sign-ins. Wait a few minutes and try again.",
  forbidden_origin: "This request did not come from this site.",
  forbidden: "Your account is not allowed to do this.",
  version_conflict: "Someone else changed this question meanwhile. Reload it and apply your changes again.",
  gold_invalid: "The labels are not complete enough to approve.",
  gold_question_not_found: "That question does not exist.",
  invalid_transition: "That step is not possible for this question's current status.",
  gold_question_retired: "Reopen the question to edit it.",
  invalid_filter: "One of the filters is not valid.",
  invalid_request: "The request was not valid (it may be too long or ask for too many results).",
  passage_not_found: "That passage is not available.",
  judgment_not_found: "That judgment is not available.",
};

export function errorMessage(code: string, fallback?: string): string {
  return MESSAGES[code] ?? fallback ?? "Something went wrong.";
}

/** The error from an API error body, or a generic one for the status. */
export function errorFromBody(status: number, body: unknown): ApiError {
  const error = (body as { error?: { code?: unknown; message?: unknown } } | null)?.error;
  const code = typeof error?.code === "string" ? error.code : `http_${status}`;
  const message = typeof error?.message === "string" ? error.message : `HTTP ${status}`;
  return new ApiError(status, code, message);
}

export type Attempt<T> = { ok: true; value: T } | { ok: false; error: ApiError };

/** Awaits an API call, turning an ApiError into a value (other errors still throw), so pages
 * render outside try/catch and real rendering errors reach the error boundary. */
export async function attempt<T>(call: Promise<T>): Promise<Attempt<T>> {
  try {
    return { ok: true, value: await call };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error };
    throw error;
  }
}
