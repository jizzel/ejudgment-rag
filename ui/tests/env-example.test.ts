import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { expect, it } from "vitest";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? sources(path) : /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

it("ui/.env.example documents exactly the environment variables the UI reads", () => {
  const used = new Set(
    sources(join(process.cwd(), "src")).flatMap((file) =>
      [...readFileSync(file, "utf8").matchAll(/process\.env\.([A-Z_][A-Z0-9_]*)/g)].map((m) => m[1]),
    ),
  );
  used.delete("NODE_ENV");
  const documented = new Set(
    [...readFileSync(join(process.cwd(), ".env.example"), "utf8").matchAll(/^#?\s*([A-Z][A-Z0-9_]+)=/gm)].map(
      (m) => m[1],
    ),
  );
  expect([...documented].sort()).toEqual([...used].sort());
});
