import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runPreflight } from "./preflight.mjs";
import { executeAcceptance } from "./execute.mjs";

const packageRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const defaultRepositoryRoot = resolve(packageRoot, "../..");
try { process.loadEnvFile(resolve(defaultRepositoryRoot, ".env")); } catch (error) { if (error?.code !== "ENOENT") throw error; }

const valueAfter = (name) => {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
};
const repositoryRoot = resolve(valueAfter("--repository-root") ?? defaultRepositoryRoot);
const brief = valueAfter("--brief") ?? process.env.SPARKDECK_ACCEPTANCE_BRIEF;
if (!brief) throw new Error("Pass an external Brief with --brief <absolute-or-relative-path>");
const outputDirectory = resolve(repositoryRoot, valueAfter("--output") ?? ".runtime/009-acceptance");
const report = await runPreflight({
  repositoryRoot,
  briefPath: resolve(brief),
  promptDirectory: resolve(repositoryRoot, process.env.PROMPT_DIRECTORY ?? "apps/api/prompts/009"),
  dataDirectory: resolve(repositoryRoot, process.env.DATA_DIRECTORY ?? ".data"),
  outputDirectory,
  tempDirectory: resolve(process.env.TEMP ?? process.env.TMP ?? ".runtime/tmp"),
  reportPath: resolve(outputDirectory, "preflight-report.json"),
  maxCalls: Number(process.env.ACCEPTANCE_MAX_MODEL_CALLS ?? 30),
  skipOffice: false
});
console.log(JSON.stringify(report));
if (!report.passed) process.exitCode = 1;
else if (!process.argv.includes("--preflight-only")) {
  const result = await executeAcceptance({ repositoryRoot, briefPath: resolve(brief), outputDirectory });
  console.log(JSON.stringify(result.report));
}
