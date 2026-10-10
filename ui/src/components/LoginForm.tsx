"use client";

import { useActionState } from "react";

import type { LoginState } from "@/app/actions";
import { errorMessage } from "@/lib/errors";

const field =
  "w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900";

export function LoginForm({
  action,
  next,
}: {
  action: (state: LoginState, form: FormData) => Promise<LoginState>;
  next: string;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  return (
    <form action={formAction} className="max-w-sm space-y-3">
      <input type="hidden" name="next" value={next} />
      <label className="block">
        <span className="mb-1 block text-sm font-medium">Email</span>
        <input type="email" name="email" autoComplete="username" defaultValue={state.email} required className={field} />
      </label>
      <label className="block">
        <span className="mb-1 block text-sm font-medium">Password</span>
        <input type="password" name="password" autoComplete="current-password" required className={field} />
      </label>
      {state.error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {errorMessage(state.error)}
        </p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900"
      >
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
