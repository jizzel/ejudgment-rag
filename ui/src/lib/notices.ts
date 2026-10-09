// Attribution and notice text come from the API's own schema defaults, so the UI cannot
// drift from what the API returns with every result.
import openapi from "./openapi.json";

const response = openapi.components.schemas.SearchResponse.properties;

export const ATTRIBUTION: string = response.attribution.default;
export const NOTICE: string = response.notice.default;
export const GHALII_URL = "https://ghalii.org";
