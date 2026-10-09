import type { CourtInfo } from "@/lib/types";

export type SearchFormValues = {
  q?: string;
  court?: string;
  year_from?: string;
  year_to?: string;
  judge?: string;
};

const field =
  "w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900";

/** A plain GET form: the URL holds the search, so results are shareable and need no JS. */
export function SearchForm({
  values,
  courts,
  action = "/",
  questionLabel = "Search judgments",
  placeholder = "Citation, case name, words or a legal question",
  multiline = false,
}: {
  values: SearchFormValues;
  courts: CourtInfo[] | null;
  action?: string;
  questionLabel?: string;
  placeholder?: string;
  multiline?: boolean;
}) {
  return (
    <form action={action} method="get" className="space-y-3" role="search">
      <label className="block">
        <span className="mb-1 block text-sm font-medium">{questionLabel}</span>
        {multiline ? (
          <textarea name="q" defaultValue={values.q} placeholder={placeholder} rows={3} maxLength={1000} required className={field} />
        ) : (
          <input type="search" name="q" defaultValue={values.q} placeholder={placeholder} maxLength={1000} required className={field} />
        )}
      </label>
      <fieldset className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <legend className="sr-only">Filters</legend>
        <label className="block text-sm">
          <span className="mb-1 block text-zinc-600 dark:text-zinc-400">Court</span>
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
        <label className="block text-sm">
          <span className="mb-1 block text-zinc-600 dark:text-zinc-400">From year</span>
          <input type="number" name="year_from" min={1900} max={2100} defaultValue={values.year_from} className={field} />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-zinc-600 dark:text-zinc-400">To year</span>
          <input type="number" name="year_to" min={1900} max={2100} defaultValue={values.year_to} className={field} />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block text-zinc-600 dark:text-zinc-400">Judge</span>
          <input name="judge" defaultValue={values.judge} minLength={2} maxLength={100} className={field} />
        </label>
      </fieldset>
      <button type="submit" className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900">
        {multiline ? "Ask" : "Search"}
      </button>
    </form>
  );
}
