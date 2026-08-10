import assert from "node:assert/strict";
import test from "node:test";
import { SceneGraphSchema, hashContent, versioned, type SceneGraph } from "@sparkdeck/presentation-model";
import { applySceneCommand, sceneSemanticFingerprint } from "./index.js";

const scene: SceneGraph = SceneGraphSchema.parse(versioned({
  presentationId: "p",
  canvas: { width: 960, height: 540, unit: "pt" as const },
  theme: {},
  pages: [{
    id: "page", width: 960, height: 540, background: "#FFFFFF", speakerNotes: [], requiredSourceIds: ["g"], selectedCandidateId: "c", alternativeCandidateIds: [], riskFlags: [],
    nodes: [{ id: "n", kind: "text", sourceIds: ["g"], bounds: { x: 10, y: 10, width: 300, height: 100 }, zIndex: 1, style: { fontSize: 24 }, content: { text: "before" }, locked: false, contentHash: hashContent("before") }]
  }]
}));

test("scene command updates revision, node hash and semantic fingerprint", () => {
  const before = sceneSemanticFingerprint(scene);
  const changed = applySceneCommand(scene, { type: "set-text", pageId: "page", nodeId: "n", value: "after", expectedRevision: 0 });
  assert.equal(changed.revision, 1);
  assert.notEqual(changed.pages[0]!.nodes[0]!.contentHash, scene.pages[0]!.nodes[0]!.contentHash);
  assert.notEqual(sceneSemanticFingerprint(changed), before);
});

test("manual nodes can be added and deleted without page-role templates", () => {
  const added = applySceneCommand(scene, { type: "add-text", pageId: "page", nodeId: "__page__", value: "新文字", expectedRevision: 0 });
  assert.equal(added.pages[0]!.nodes.length, 2);
  assert.equal(added.pages[0]!.nodes[1]!.content.text, "新文字");
  const removed = applySceneCommand(added, { type: "delete-node", pageId: "page", nodeId: added.pages[0]!.nodes[1]!.id, value: "", expectedRevision: 1 });
  assert.equal(removed.pages[0]!.nodes.length, 1);
  assert.equal(removed.revision, 2);
});
