// Types generated from the API's OpenAPI schema (npm run gen:api); never edited by hand.
import type { components } from "./api-types";

type Schemas = components["schemas"];

export type SearchRequest = Schemas["SearchRequest"];
export type SearchFilters = Schemas["SearchFilters"];
export type SearchResponse = Schemas["SearchResponse"];
export type CaseResult = Schemas["CaseResult"];
export type PassageResult = Schemas["PassageResult"];
export type JudgmentRef = Schemas["JudgmentRef"];
export type QueryInfo = Schemas["QueryInfo"];
export type ChatRequest = Schemas["ChatRequest"];
export type ChatResponse = Schemas["ChatResponse"];
export type ChatClaim = Schemas["ChatClaim"];
export type ChatSource = Schemas["ChatSource"];
export type PassageContext = Schemas["PassageContext"];
export type ContextPassage = Schemas["ContextPassage"];
export type CourtInfo = Schemas["CourtInfo"];
export type CourtsResponse = Schemas["CourtsResponse"];
export type ErrorResponse = Schemas["ErrorResponse"];
export type LoginResponse = Schemas["LoginResponse"];
export type UserInfo = Schemas["UserInfo"];
export type ReviewList = Schemas["ReviewList"];
export type ReviewSummary = Schemas["ReviewSummary"];
export type ReviewDetail = Schemas["ReviewDetail"];
export type ReviewQuestion = Schemas["ReviewQuestion"];
export type ReviewWrite = Schemas["ReviewWrite"];
export type GoldDraft = Schemas["GoldDraft"];
export type GoldPassage = Schemas["GoldPassage"];
export type PageStatus = PassageResult["page_reference_status"];
