/** Pure helpers for the gold-set review editor (mirrors the API's approval rule). */
import type { GoldDraft, GoldPassage, ReviewQuestion } from "./types";

export const CATEGORIES = ["citation", "case_name", "issue", "fact_pattern", "out_of_corpus"] as const;
export const REVIEW_ROLES = new Set(["reviewer", "admin"]);
export const STATUSES = ["draft", "approved", "retired"] as const;

export function canReview(role: string | null | undefined): boolean {
  return role != null && REVIEW_ROLES.has(role);
}
export const MIN_PASSAGE_CHARS = 20;

export type Labels = {
  question: string;
  category: GoldDraft["category"];
  court: string;
  jurisdiction: string;
  year_from: string;
  year_to: string;
  judge: string;
  expect_no_answer: boolean;
  gold_canonical_uris: string[];
  gold_passages: GoldPassage[];
  notes: string;
};

export function labelsFrom(question: ReviewQuestion): Labels {
  const filters = question.filters as Record<string, string | number | undefined>;
  return {
    question: question.question,
    category: question.category as GoldDraft["category"],
    court: String(filters.court ?? ""),
    jurisdiction: String(filters.jurisdiction ?? ""),
    year_from: filters.year_from == null ? "" : String(filters.year_from),
    year_to: filters.year_to == null ? "" : String(filters.year_to),
    judge: String(filters.judge ?? ""),
    expect_no_answer: question.expect_no_answer,
    gold_canonical_uris: [...question.gold_canonical_uris],
    gold_passages: question.gold_passages.map((p) => ({ ...p })),
    notes: question.notes ?? "",
  };
}

function year(value: string): number | null {
  return /^\d{4}$/.test(value.trim()) ? Number(value.trim()) : null;
}

/** Filter inputs that can't be saved as entered (never dropped: that would widen the filters). */
export function filterProblems(labels: Labels): string[] {
  const problems: string[] = [];
  for (const [name, value] of [["From year", labels.year_from], ["To year", labels.year_to]]) {
    if (value.trim() && year(value) === null) problems.push(`${name} must be a 4-digit year.`);
  }
  const from = year(labels.year_from);
  const to = year(labels.year_to);
  if (from !== null && to !== null && from > to) problems.push("From year is after To year.");
  return problems;
}

/** What the API's PUT/POST body gets (filters only when set). Throws on unsavable filters. */
export function toDraft(labels: Labels): GoldDraft {
  const problems = filterProblems(labels);
  if (problems.length > 0) throw new Error(problems.join(" "));
  const filters: GoldDraft["filters"] = {};
  if (labels.court.trim()) filters.court = labels.court.trim();
  if (labels.jurisdiction.trim()) filters.jurisdiction = labels.jurisdiction.trim();
  if (labels.year_from.trim()) filters.year_from = year(labels.year_from);
  if (labels.year_to.trim()) filters.year_to = year(labels.year_to);
  if (labels.judge.trim()) filters.judge = labels.judge.trim();
  return {
    question: labels.question.trim(),
    category: labels.category,
    filters,
    expect_no_answer: labels.expect_no_answer,
    gold_canonical_uris: labels.gold_canonical_uris,
    gold_passages: labels.gold_passages,
    notes: labels.notes.trim() || null,
  };
}

/** Why the labels can't be approved yet (empty when they can); same rule as the API. */
export function approvalProblems(labels: Labels): string[] {
  const problems: string[] = [];
  if (!labels.question.trim()) problems.push("The question is empty.");
  const hasCases = labels.gold_canonical_uris.length > 0;
  if (labels.expect_no_answer && hasCases) {
    problems.push("A question that should get no answer cannot have gold cases.");
  }
  if (!labels.expect_no_answer && !hasCases) {
    problems.push("Mark at least one gold case, or that the system should give no answer.");
  }
  const cases = new Set(labels.gold_canonical_uris);
  if (labels.gold_passages.some((p) => !cases.has(p.canonical_uri))) {
    problems.push("Every gold passage must come from a gold case.");
  }
  problems.push(...filterProblems(labels));
  return problems;
}

export function toggleCase(labels: Labels, uri: string): Labels {
  const has = labels.gold_canonical_uris.includes(uri);
  return {
    ...labels,
    gold_canonical_uris: has
      ? labels.gold_canonical_uris.filter((u) => u !== uri)
      : [...labels.gold_canonical_uris, uri],
    // Removing a case also removes its passages.
    gold_passages: has ? labels.gold_passages.filter((p) => p.canonical_uri !== uri) : labels.gold_passages,
  };
}

/** Adds a passage (verbatim; its case becomes gold too), or removes it if already marked. */
export function togglePassage(labels: Labels, uri: string, text: string): Labels {
  const passage = text.trim();
  if (passage.length < MIN_PASSAGE_CHARS) return labels;
  const exists = labels.gold_passages.some((p) => p.canonical_uri === uri && p.text === passage);
  if (exists) {
    return { ...labels, gold_passages: labels.gold_passages.filter((p) => !(p.canonical_uri === uri && p.text === passage)) };
  }
  const cases = labels.gold_canonical_uris.includes(uri)
    ? labels.gold_canonical_uris
    : [...labels.gold_canonical_uris, uri];
  return { ...labels, gold_canonical_uris: cases, gold_passages: [...labels.gold_passages, { canonical_uri: uri, text: passage }] };
}

export function sameLabels(a: Labels, b: Labels): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
