import type { CaseResult, ChatResponse, JudgmentRef, PassageContext, QueryInfo } from "@/lib/types";

export const judgment: JudgmentRef = {
  judgment_id: "11111111-1111-5111-8111-111111111111",
  canonical_uri: "/akn/gh/judgment/ghasc/2020/38/eng@2020-02-07",
  citation: "Mensah v Owusu [2020] GHASC 38 (7 February 2020)",
  title: "Mensah v Owusu",
  court_code: "ghasc",
  court_name: "Supreme Court",
  jurisdiction: "gh",
  judgment_date: "2020-02-07",
  source_url: "https://ghalii.org/akn/gh/judgment/ghasc/2020/38/eng@2020-02-07",
};

export const queryInfo: QueryInfo = {
  detected_citation: null,
  looks_like_case_name: false,
  filters_applied: {},
  mode_requested: "hybrid",
  mode_used: "hybrid",
  reranked: true,
  degraded: false,
  degraded_reason: null,
};

export const caseResult: CaseResult = {
  judgment,
  also_published_as: [],
  match_type: "hybrid",
  score: 0.9,
  passages: [
    {
      chunk_id: "22222222-2222-5222-8222-222222222222",
      judgment,
      excerpt: "The landlord was entitled to recover possession. <img src=x onerror=alert(1)>",
      section_label: null,
      paragraph_refs: [],
      page_reference_status: "verified",
      page_start: 4,
      page_end: 5,
      match_type: "hybrid",
      lexical_score: null,
      dense_score: null,
      rrf_score: null,
      rerank_score: null,
    },
  ],
};

const base = {
  question: "When may a landlord recover possession?",
  session_id: null,
  query_info: queryInfo,
  attribution: "Source: GhaLII test attribution",
  notice: "Test notice",
};

export const answered: ChatResponse = {
  ...base,
  abstained: false,
  abstain_reason: null,
  answer: "The landlord could recover possession. [1]",
  claims: [
    {
      text: "The landlord could recover possession.",
      kind: "holding",
      source_numbers: [1],
      quote: "entitled to recover possession",
      quote_chunk_id: "22222222-2222-5222-8222-222222222222",
      pinpoint: "PDF pages 5-6",
      support_score: 0.97,
    },
  ],
  sources: [
    {
      number: 1,
      judgment,
      also_published_as: [],
      passages: [
        {
          chunk_id: "22222222-2222-5222-8222-222222222222",
          excerpt: "The landlord was entitled to recover possession.",
          page_reference_status: "unknown",
          page_start: null,
          page_end: null,
        },
      ],
    },
  ],
  limitations: ["Some cited passages have no verified page numbers; cite them by case and link only."],
  model_limitations: "Only one case was relevant.",
  matched_cases: [judgment],
  generation: {
    provider: "ollama",
    model: "gemma4:latest",
    requested_model: "gemma4:latest",
    prompt_version: "grounded-v1",
    support_model: "cross-encoder/nli-deberta-v3-base@6c749ce",
    input_tokens: 3000,
    output_tokens: 120,
    latency_ms: 15400,
    sources_sent: 8,
    source_ids_cited: 1,
    invalid_source_ids: 0,
    removed_claims: {},
  },
};

export const abstained: ChatResponse = {
  ...answered,
  abstained: true,
  abstain_reason: "model_abstained",
  answer: null,
  claims: [],
  sources: [],
  limitations: [],
  model_limitations: "The sources do not cover drone licensing.",
};

export const passageContext: PassageContext = {
  judgment,
  passage: {
    chunk_id: "22222222-2222-5222-8222-222222222222",
    ordinal: 3,
    excerpt: "The respondent's tenancy ended.\nThe landlord was entitled to\nrecover possession of the premises.",
    section_label: null,
    page_reference_status: "pending",
    page_start: null,
    page_end: null,
  },
  before: [
    {
      chunk_id: "33333333-3333-5333-8333-333333333333",
      ordinal: 2,
      excerpt: "The facts are these.",
      section_label: null,
      page_reference_status: "pending",
      page_start: null,
      page_end: null,
    },
  ],
  after: [],
  attribution: "Source: GhaLII test attribution",
  notice: "Test notice",
};
