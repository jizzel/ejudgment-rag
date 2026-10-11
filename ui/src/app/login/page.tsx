import { Suspense } from "react";

import { login } from "@/app/actions";
import { LoginForm } from "@/components/LoginForm";
import { safeNext } from "@/lib/auth";

async function Form({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { next } = await searchParams;
  return <LoginForm action={login} next={safeNext(typeof next === "string" ? next : "/")} />;
}

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <div className="mx-auto max-w-md space-y-6 pt-6 sm:pt-16">
      <div className="space-y-2 text-center">
        <h1 className="font-serif text-3xl font-semibold">E-Judgment research</h1>
        <p className="text-muted">
          Search Ghanaian judgments from GhaLII and ask questions answered only from quoted,
          checked passages. A research aid, not legal advice.
        </p>
      </div>
      <div className="rounded-lg border border-line bg-surface p-6 shadow-sm">
        <h2 className="mb-4 font-semibold">Sign in</h2>
        {/* Same height as the form, so the card does not jump when it arrives. */}
        <Suspense fallback={<div aria-busy="true" className="h-[12.25rem]" />}>
          <Form searchParams={searchParams} />
        </Suspense>
      </div>
      <p className="text-center text-sm text-muted">
        Access is by invitation. Ask the administrator for an account.
      </p>
    </div>
  );
}
