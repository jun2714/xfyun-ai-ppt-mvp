import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { versioned, type PresentationBrief } from "@sparkdeck/presentation-model";
import { FilePresentationStateRepository } from "./infrastructure/persistence/file/file-presentation-state-repository.js";

test("file repository survives reconstruction and leaves no partial temp document", async () => {
  const root = await mkdtemp(join(tmpdir(), "sparkdeck-repository-test-"));
  try {
    const brief = versioned({ id: "pres_restart", title: "Persistence contract", audience: "reviewers", usageContext: "verification", objective: "recover state", pageCount: 1, constraints: [], sourceAssetIds: [], language: "en" }) as PresentationBrief;
    const state = { brief, assets: {}, layoutTraces: {}, assetTraces: [], repairCount: 0, history: [], future: [], jobs: [], idempotency: {}, usage: [] };
    const repository = new FilePresentationStateRepository(root);
    repository.save(state);
    repository.save({ ...state, repairCount: 1 });
    const restored = new FilePresentationStateRepository(root).get(brief.id);
    assert.equal(restored?.brief.contentHash, brief.contentHash);
    assert.deepEqual(restored?.jobs, []);
    assert.equal(restored?.repairCount, 1);
    assert.equal((await readdir(join(root, "presentations"))).some((name) => name.endsWith(".tmp")), false);
    assert.throws(() => new FilePresentationStateRepository(root).get("../escape"), /INVALID_PRESENTATION_ID/);
  } finally { await rm(root, { recursive: true, force: true }); }
});
