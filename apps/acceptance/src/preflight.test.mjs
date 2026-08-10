import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { runPreflight } from "./preflight.mjs";

test("failed preflight records zero paid calls", async () => {
  const outside = await mkdtemp(resolve(tmpdir(), "sparkdeck-brief-"));
  const fakeRepo = await mkdtemp(resolve(tmpdir(), "sparkdeck-repo-"));
  await writeFile(resolve(fakeRepo, "package.json"), JSON.stringify({ packageManager: "pnpm@10.23.0" }));
  const briefPath = resolve(outside, "brief.json");
  await writeFile(briefPath, JSON.stringify({ title: "x", audience: "x", usageContext: "x", objective: "x", pageCount: 2, constraints: [], language: "zh-CN" }));
  const output = resolve(fakeRepo, "output");
  await mkdir(output);
  const previous = { ...process.env };
  Object.assign(process.env, { DMX_API_KEY: "test-only", DMX_TEXT_MODEL: "text", DMX_IMAGE_MODEL: "image", DMX_VISION_MODEL: "vision" });
  try {
    const report = await runPreflight({ repositoryRoot: fakeRepo, briefPath, promptDirectory: resolve(fakeRepo, "missing-prompts"), dataDirectory: resolve(fakeRepo, "data"), outputDirectory: output, tempDirectory: resolve(fakeRepo, "tmp"), reportPath: resolve(output, "preflight-report.json"), maxCalls: 3, skipOffice: true });
    assert.equal(report.passed, false);
    assert.deepEqual(report.usage, { textCalls: 0, imageCalls: 0, visualCalls: 0, estimatedCostRmb: 0 });
    assert.deepEqual(JSON.parse(await readFile(resolve(output, "preflight-report.json"), "utf8")).usage, report.usage);
  } finally { process.env = previous; }
});
