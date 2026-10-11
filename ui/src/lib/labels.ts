/** Display names for the review workflow's stored values (the API values are unchanged). */
import type { components } from "./api-types";

type Schemas = components["schemas"];
export type Category = Schemas["GoldDraft"]["category"];
export type GoldStatus = Schemas["GoldStatus"];
export type GoldAction = Schemas["GoldAction"];

export const CATEGORY_LABELS: Record<Category, string> = {
  citation: "Citation",
  case_name: "Case name",
  issue: "Legal issue",
  fact_pattern: "Fact pattern",
  out_of_corpus: "Outside the corpus",
};

export const STATUS_LABELS: Record<GoldStatus, string> = {
  draft: "Draft",
  approved: "Approved",
  retired: "Retired",
};

export const ACTION_LABELS: Record<GoldAction, string> = {
  created: "Created",
  imported: "Imported",
  edited: "Edited",
  approved: "Approved",
  reopened: "Reopened",
  retired: "Retired",
};

/** The label of a value, or the value itself when it has none (never an empty cell). */
export function label(labels: Record<string, string>, value: string): string {
  return labels[value] ?? value;
}
