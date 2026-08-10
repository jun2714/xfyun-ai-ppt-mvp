import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { PromptCatalogPort, PromptContract } from "../../application/ports/prompt-catalog.port.js";
import { AppError } from "../../shared/errors/app-error.js";

/** Reads immutable prompt contracts from a configured directory and verifies their headers. */
export class FilePromptCatalogAdapter implements PromptCatalogPort {
  constructor(private readonly directory: string) {}

  get(id: "narrative" | "design" | "image" | "visual-quality"): PromptContract {
    const root = resolve(this.directory);
    const file = resolve(join(root, `${id}.prompt.txt`));
    if (!file.startsWith(`${root}\\`) && file !== root) throw new AppError("PROMPT_PATH_INVALID", "Prompt contract path is outside the configured directory", 500);
    let raw = "";
    try { raw = readFileSync(file, "utf8"); }
    catch { throw new AppError("PROMPT_CONTRACT_MISSING", `Prompt contract is missing: ${id}`, 500); }
    const [header, ...body] = raw.replace(/^\uFEFF/, "").split(/\r?\n/);
    const match = /^version:\s*([A-Za-z0-9._-]+)$/.exec(header?.trim() ?? "");
    const content = body.join("\n").trim();
    if (!match || !content) throw new AppError("PROMPT_CONTRACT_INVALID", `Prompt contract is invalid: ${id}`, 500);
    return { id, version: match[1]!, content, contentHash: createHash("sha256").update(raw).digest("hex") };
  }
}
