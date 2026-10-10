import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, it } from "vitest";

import openapi from "@/lib/openapi.json";

it("the generated types cover every schema of the API snapshot (run npm run gen:api)", () => {
  const types = readFileSync(join(process.cwd(), "src/lib/api-types.ts"), "utf8");
  for (const name of Object.keys(openapi.components.schemas)) {
    // An object schema becomes `Name: {`, a union (e.g. the chat stream events) `Name: A | B`.
    expect(types, `api-types.ts lacks ${name}`).toMatch(new RegExp(`\\b${name}: `));
  }
  for (const path of Object.keys(openapi.paths)) {
    expect(types, `api-types.ts lacks ${path}`).toContain(`"${path}": {`);
  }
});
