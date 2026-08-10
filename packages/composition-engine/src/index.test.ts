import assert from "node:assert/strict";
import test from "node:test";
import { composeDeck, composePage } from "./index.js";

const page = {
  id: "p",
  purpose: "explain",
  headline: "A clear title",
  message: "Message",
  contentGroups: [
    { id: "g1", kind: "paragraph" as const, text: "Audience-facing explanation", claimIds: [], required: true },
    { id: "g2", kind: "list" as const, items: ["First", "Second"], claimIds: [], required: true }
  ],
  speakerNotes: [], evidenceRequests: [], continuityLinks: []
};
const intent = {
  pageId: "p", focalMessage: "Message",
  hierarchy: [{ contentGroupId: "g1", priority: 1 }, { contentGroupId: "g2", priority: 2 }],
  groups: [{ id: "dg", contentGroupIds: ["g1", "g2"], treatment: "paired" as const }],
  relationships: [], visualStrategy: "subject" as const, balance: "asymmetric" as const,
  flow: "horizontal" as const, density: "low" as const, emphasis: [],
  mediaRequests: [{ id: "m", claimIds: [], role: "subject" as const, description: "subject", fit: "contain" as const, focalPolicy: "subject" as const, required: true }],
  avoid: []
};
const tokens = {
  background: "#ffffff", surface: "#f3f4f6", text: "#111111", textOnPrimary: "#ffffff",
  primary: "#047857", secondary: "#f97316", accent: "#facc15", muted: "#cbd5e1",
  headingFontFamily: "Arial", bodyFontFamily: "Arial", headingWeight: 700, bodyWeight: 400,
  deckTitlePt: 56, titlePt: 40, bodyPt: 20, captionPt: 16, lineHeight: 1.2, space: 16,
  safeInset: 36, radius: 10, strokeWidth: 1, motif: "organic"
};

test("creates two to four constraint-valid candidates for different canvases", () => {
  for (const canvas of [{ width: 960, height: 540 }, { width: 720, height: 720 }, { width: 540, height: 960 }]) {
    const result = composePage(page, intent, canvas, tokens);
    assert.ok(result.length >= 2 && result.length <= 4);
    assert.equal(result.filter((candidate) => candidate.selected).length, 1);
    assert.ok(result.every((candidate) => candidate.hardFailures.length === 0));
    assert.ok(result.every((candidate) => candidate.resolved.children.length > 0));
  }
});

test("deck selection penalizes identical adjacent silhouettes", () => {
  const pages = [page, { ...page, id: "p2", headline: "Another clear title", contentGroups: page.contentGroups.map((group) => ({ ...group, id: `${group.id}-2` })) }];
  const intents = [intent, { ...intent, pageId: "p2", hierarchy: intent.hierarchy.map((item) => ({ ...item, contentGroupId: `${item.contentGroupId}-2` })), groups: [{ ...intent.groups[0]!, id: "dg2", contentGroupIds: ["g1-2", "g2-2"] }], mediaRequests: [{ ...intent.mediaRequests[0]!, id: "m2" }] }];
  const sets = composeDeck(pages, intents, { width: 960, height: 540 }, tokens);
  assert.equal(sets.length, 2);
  assert.equal(sets.every((set) => set.filter((candidate) => candidate.selected).length === 1), true);
});
