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
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Access is by invitation. Ask the administrator for an account.
        </p>
      </div>
      <Suspense fallback={null}>
        <Form searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
