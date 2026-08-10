import assert from "node:assert/strict";
import test from "node:test";
import { access, readFile, readdir } from "node:fs/promises";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const workspace = fileURLToPath(new URL("../../../", import.meta.url));
async function files(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry): Promise<string[]> => {
    if (["dist", "node_modules"].includes(entry.name)) return [];
    const path = join(directory, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  }));
  return nested.flat();
}

test("production source has no business-to-layout dispatch or generated-code execution", async () => {
  const roots = [join(workspace, "apps", "api", "src"), join(workspace, "packages")];
  const paths = (await Promise.all(roots.map(files))).flat().filter((file) => [".ts", ".tsx"].includes(extname(file)) && !file.endsWith(".test.ts") && !file.endsWith(".test.tsx"));
  const source = (await Promise.all(paths.map((file) => readFile(file, "utf8")))).join("\n");
  const forbidden = [
    /(?:page|slide)\.role\s*===/i,
    /scenario\s*===/i,
    /pageNumber\s*===/i,
    /\blayoutId\s*[:=]/i,
    /blocks\s*\[\s*0\s*\]/i,
    /eval\s*\(/i,
    /new\s+Function\s*\(/i,
    /if\s*\([^)]*(?:家长会|动物课|安全教育|中班|小班|大班)/i
  ];
  for (const pattern of forbidden) assert.equal(pattern.test(source), false, `forbidden production pattern: ${pattern}`);
});

test("third-party reference repositories are not vendored into the runtime", async () => {
  let exists = true;
  try { await access(join(workspace, "third_party")); } catch { exists = false; }
  assert.equal(exists, false);
});
