import assert from "node:assert/strict";
import test from "node:test";
import { SceneGraphSchema, hashContent, versioned, type SceneGraph } from "@sparkdeck/presentation-model";
import { applyVisualReview, buildVisualReviewBatch, evaluateScene } from "./index.js";

const makeScene = (): SceneGraph => SceneGraphSchema.parse(versioned({
  presentationId: "p", canvas: { width: 960, height: 540, unit: "pt" as const }, theme: {},
  pages: [{ id: "page", width: 960, height: 540, background: "#FFFFFF", speakerNotes: [], requiredSourceIds: ["page"], selectedCandidateId: "c", alternativeCandidateIds: [], riskFlags: ["opening"], nodes: [
    { id: "title", kind: "text", sourceIds: ["page"], bounds: { x: 60, y: 40, width: 840, height: 70 }, zIndex: 2, style: { fontSize: 40, fontFamily: "Arial", fontWeight: 700, lineHeight: 1.2, color: "#111111" }, content: { text: "Clear title", semantic: "title" }, locked: false, contentHash: hashContent("title") }
  ] }]
}));

test("all pages receive rule checks and risky pages enter one visual batch", () => {
  const scene = makeScene();
  const report = evaluateScene(scene);
  assert.equal(report.passed, true);
  assert.deepEqual(report.visualReviewPageIds, ["page"]);
  assert.equal(buildVisualReviewBatch(scene, report).maxPaidCalls, 1);
});

test("missing required content is a hard failure", () => {
  const scene = makeScene();
  scene.pages[0]!.requiredSourceIds.push("missing");
  const report = evaluateScene(scene);
  assert.equal(report.passed, false);
  assert.ok(report.issues.some((issue) => issue.code === "REQUIRED_CONTENT_MISSING"));
});

test("visual review can fail a rule-clean high-risk page without coordinates", () => {
  const report = evaluateScene(makeScene());
  const reviewed = applyVisualReview(report, [{ pageId: "page", dimension: "Design", severity: "error", message: "The focal point is visually unclear", repairIntent: "increase focal hierarchy" }]);
  assert.equal(reviewed.passed, false);
  assert.equal(reviewed.visualReviewStatus, "failed");
  assert.equal(reviewed.issues.at(-1)?.nodeIds.length, 0);
});
