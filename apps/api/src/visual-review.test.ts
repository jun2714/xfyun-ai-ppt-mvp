import assert from "node:assert/strict";
import test from "node:test";
import { SceneGraphSchema, hashContent, versioned } from "@sparkdeck/presentation-model";
import { DmxVisualReviewAdapter } from "./infrastructure/dmx/dmx-visual-review.adapter.js";
import { DmxAuth } from "./infrastructure/dmx/dmx-auth.js";
import type { JsonHttpClient } from "./infrastructure/http/json-http-client.js";
import { SvgContactSheetAdapter } from "./infrastructure/rendering/svg-contact-sheet.adapter.js";

test("contact sheet rasterizes selected scene pages locally", async () => {
  const scene = SceneGraphSchema.parse(versioned({ presentationId: "p", canvas: { width: 960, height: 540, unit: "pt" as const }, theme: {}, pages: [{ id: "page", width: 960, height: 540, background: "#FFFFFF", speakerNotes: [], requiredSourceIds: ["page"], selectedCandidateId: "c", alternativeCandidateIds: [], riskFlags: ["opening"], nodes: [{ id: "title", kind: "text", sourceIds: ["page"], bounds: { x: 50, y: 40, width: 860, height: 80 }, zIndex: 1, style: { fontFamily: "Arial", fontSize: 40, fontWeight: 700, color: "#111111" }, content: { text: "A clear title", semantic: "title" }, locked: false, contentHash: hashContent("title") }] }] }));
  const dataUri = await new SvgContactSheetAdapter().render(scene, ["page"]);
  assert.match(dataUri, /^data:image\/png;base64,/);
  assert.ok(dataUri.length > 1_000);
});

test("visual review uses one multimodal request and validates page references", async () => {
  let body: any;
  const http = { post: async (_url: string, _headers: Record<string, string>, input: unknown) => { body = input; return { model: "gemini-2.5-flash", choices: [{ message: { content: JSON.stringify({ issues: [] }) } }], usage: { prompt_tokens: 100, completion_tokens: 20 } }; } } as unknown as JsonHttpClient;
  const result = await new DmxVisualReviewAdapter(http, new DmxAuth("test"), "https://www.dmxapi.cn/v1", "gemini-2.5-flash").review({ contactSheetDataUri: "data:image/png;base64,AAAA", pageIds: ["page"], instructions: "Review design", maxOutputTokens: 500 });
  assert.equal(result.issues.length, 0);
  assert.equal(body.messages[1].content.filter((item: { type: string }) => item.type === "image_url").length, 1);
});
