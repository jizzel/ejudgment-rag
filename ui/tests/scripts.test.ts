import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, it } from "vitest";

it("the UI servers listen on loopback only (no sign-in until M4 slice 2)", () => {
  // Next binds 0.0.0.0 by default, which would expose the unauthenticated UI and chat proxy.
  const { scripts } = JSON.parse(readFileSync(join(process.cwd(), "package.json"), "utf8")) as {
    scripts: Record<string, string>;
  };
  for (const name of ["dev", "start"]) {
    expect(scripts[name], name).toMatch(/(?:-H|--hostname)\s+127\.0\.0\.1\b/);
    expect(scripts[name], name).not.toMatch(/0\.0\.0\.0/);
  }
});
