import { errorMessage } from "@/lib/errors";

export function ErrorPanel({ code, detail }: { code: string; detail?: string }) {
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100">
      <p className="font-medium">{errorMessage(code, detail)}</p>
      {detail && detail !== errorMessage(code, detail) && (
        <p className="mt-1 text-xs opacity-80">
          Details: {detail} ({code})
        </p>
      )}
    </div>
  );
}
