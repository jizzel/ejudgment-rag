/** Placeholder cards with the shape of real results, so the page does not jump. */
export function ResultsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Searching" className="space-y-4">
      <p className="sr-only" role="status">
        Searching…
      </p>
      {[0, 1, 2].map((index) => (
        <div key={index} className="h-44 animate-pulse rounded-lg border border-line bg-surface p-4 motion-reduce:animate-none">
          <div className="h-5 w-2/3 rounded bg-line" />
          <div className="mt-2 h-3 w-1/3 rounded bg-line" />
          <div className="mt-5 space-y-2">
            <div className="h-3 rounded bg-line" />
            <div className="h-3 rounded bg-line" />
            <div className="h-3 w-5/6 rounded bg-line" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** The search bar's shape while the page (courts, session) loads. */
export function SearchFormSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading" className="max-w-3xl space-y-3">
      <div className="flex gap-2">
        <div className="h-12 flex-1 rounded-lg border border-line bg-surface" />
        <div className="h-12 w-24 rounded-lg bg-accent/30" />
      </div>
      <div className="h-5 w-20 rounded bg-line" />
    </div>
  );
}
