import type { FilterField } from "@/lib/search";
import type { CourtInfo } from "@/lib/types";

import { field, primaryButton } from "./ui";

export type SearchFormValues = {
  q?: string;
  court?: string;
  year_from?: string;
  year_to?: string;
  judge?: string;
};

export type FieldErrors = Partial<Record<FilterField, string>>;

export function YearField({
  name,
  label,
  value,
  error,
}: {
  name: FilterField;
  label: string;
  value?: string;
  error?: string;
}) {
  const id = `${name}-error`;
  return (
    <div className="text-sm">
      <label className="block">
        <span className="mb-1 block text-muted">{label}</span>
        <input
          name={name}
          inputMode="numeric"
          defaultValue={value}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? id : undefined}
          className={field}
        />
      </label>
      {error && (
        <p id={id} className="mt-1 text-xs font-medium text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}

/** A plain GET form: the URL holds the search, so results are shareable and need no JS.
 * Filters sit in a disclosure that opens itself when one is set or needs fixing. */
export function SearchForm({
  values,
  courts,
  errors = {},
}: {
  values: SearchFormValues;
  courts: CourtInfo[] | null;
  errors?: FieldErrors;
}) {
  const filtered = Boolean(values.court || values.year_from || values.year_to || values.judge);
  const hasErrors = Object.keys(errors).length > 0;
  return (
    <form action="/" method="get" role="search" className="space-y-3">
      <label className="block">
        <span className="sr-only">Search judgments</span>
        <span className="flex flex-col gap-2 sm:flex-row">
          <input
            type="search"
            name="q"
            defaultValue={values.q}
            placeholder="Citation, case name, words or a legal question"
            maxLength={1000}
            required
            className="min-h-12 w-full rounded-lg border border-line bg-surface px-4 text-base text-ink shadow-sm"
          />
          <button type="submit" className={`${primaryButton} min-h-12 px-6`}>
            Search
          </button>
        </span>
      </label>
      <details className="group" open={filtered || hasErrors || undefined}>
        <summary className="inline-flex min-h-8 items-center text-sm text-accent">
          <span className="mr-1.5 inline-block transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden>
            ›
          </span>
          Filters{filtered ? " (active)" : ""}
        </summary>
        <fieldset className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <legend className="sr-only">Filters</legend>
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Court</span>
            {courts ? (
              <select name="court" defaultValue={values.court ?? ""} className={field}>
                <option value="">All courts</option>
                {courts.map((court) => (
                  <option key={court.court_code} value={court.court_code}>
                    {court.court_name ?? court.court_code} ({court.judgments})
                  </option>
                ))}
              </select>
            ) : (
              <input name="court" defaultValue={values.court} placeholder="e.g. ghasc" className={field} />
            )}
          </label>
          <YearField name="year_from" label="From year" value={values.year_from} error={errors.year_from} />
          <YearField name="year_to" label="To year" value={values.year_to} error={errors.year_to} />
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Judge</span>
            <input name="judge" defaultValue={values.judge} minLength={2} maxLength={100} className={field} />
          </label>
        </fieldset>
      </details>
    </form>
  );
}
