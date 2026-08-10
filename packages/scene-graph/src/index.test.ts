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

test("linked pages are protected and multi-selection alignment is revisioned", () => {
  const linked = SceneGraphSchema.parse(versioned({ ...scene, pages: scene.pages.map((page) => ({ ...page, pageLinkIds: ["link-a"] })) }));
  assert.throws(() => applySceneCommand(linked, { type: "delete-page", pageId: "page", nodeId: "__page__", value: "", expectedRevision: 0 }), /LINKED_PAGE_PROTECTED/);
  const first = applySceneCommand(scene, { type: "add-shape", pageId: "page", nodeId: "__page__", value: "", expectedRevision: 0 });
  const second = applySceneCommand(first, { type: "add-shape", pageId: "page", nodeId: "__page__", value: "", expectedRevision: 1 });
  const ids = second.pages[0]!.nodes.slice(-2).map((node) => node.id);
  const aligned = applySceneCommand(second, { type: "align-nodes", pageId: "page", nodeId: "__page__", value: { nodeIds: ids, axis: "horizontal", mode: "start" }, expectedRevision: 2 });
  const selected = aligned.pages[0]!.nodes.filter((node) => ids.includes(node.id));
  assert.equal(selected[0]!.bounds.x, selected[1]!.bounds.x);
  assert.equal(aligned.revision, 3);
});

test("editor commands duplicate, style and lock nodes without losing revision history", () => {
  const duplicated = applySceneCommand(scene, { type: "duplicate-node", pageId: "page", nodeId: "n", value: "", expectedRevision: 0 });
  assert.equal(duplicated.pages[0]!.nodes.length, 2);
  const copy = duplicated.pages[0]!.nodes[1]!;
  assert.notEqual(copy.id, "n");
  const styled = applySceneCommand(duplicated, { type: "set-style", pageId: "page", nodeId: copy.id, value: { fontSize: 32, color: "#123456", lineHeight: 1.4 }, expectedRevision: 1 });
  assert.equal(styled.pages[0]!.nodes[1]!.style.fontSize, 32);
  const locked = applySceneCommand(styled, { type: "set-locked", pageId: "page", nodeId: copy.id, value: true, expectedRevision: 2 });
  assert.throws(() => applySceneCommand(locked, { type: "delete-node", pageId: "page", nodeId: copy.id, value: "", expectedRevision: 3 }), /NODE_LOCKED/);
  const unlocked = applySceneCommand(locked, { type: "set-locked", pageId: "page", nodeId: copy.id, value: false, expectedRevision: 3 });
  assert.equal(unlocked.pages[0]!.nodes[1]!.locked, false);
});
