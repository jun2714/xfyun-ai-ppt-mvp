import assert from "node:assert/strict";
import test from "node:test";
import { SceneGraphSchema, hashContent, versioned } from "@sparkdeck/presentation-model";
import { exportSceneToPptx } from "./index.js";

test("exports editable native text from scene graph", async () => {
  const scene = SceneGraphSchema.parse(versioned({
    presentationId: "p",
    canvas: { width: 960, height: 540, unit: "pt" as const },
    theme: {},
    pages: [{
      id: "page", width: 960, height: 540, background: "#FFFFFF", speakerNotes: [], requiredSourceIds: ["source"],
      selectedCandidateId: "c", alternativeCandidateIds: [], riskFlags: [],
      nodes: [{ id: "title", kind: "text" as const, sourceIds: ["source"], bounds: { x: 48, y: 40, width: 864, height: 80 }, zIndex: 0, style: { fontFamily: "Arial", fontSize: 36, fontWeight: 700, color: "#111111" }, content: { text: "Editable title" }, locked: false, contentHash: hashContent("title") }]
    }]
  }));
  const result = await exportSceneToPptx(scene);
  assert.equal(String.fromCharCode(...result.bytes.slice(0, 2)), "PK");
  assert.equal(result.semanticFingerprint.length, 64);
});
