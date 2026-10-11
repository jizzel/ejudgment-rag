"use client";

import { useActionState } from "react";

import type { LoginState } from "@/app/actions";
import { errorMessage } from "@/lib/errors";

import { field, primaryButton } from "./ui";

export function LoginForm({
  action,
  next,
}: {
  action: (state: LoginState, form: FormData) => Promise<LoginState>;
  next: string;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  return (
    <form action={formAction} aria-label="Sign in" className="space-y-4">
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
      <button type="submit" disabled={pending} className={`${primaryButton} w-full`}>
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
