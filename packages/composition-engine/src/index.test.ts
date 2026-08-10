import assert from "node:assert/strict";
import test from "node:test";
import { versioned, type DeckDesignPlan, type NarrativeOutline } from "@sparkdeck/presentation-model";
import { composeDeck, composePage, generateCandidateTrees, RelationConstraintCompiler } from "./index.js";

const page = {
  id: "p",
  purpose: "explain",
  headline: "A clear title",
  message: "Message",
  contentGroups: [
    { id: "g1", kind: "paragraph" as const, text: "Audience-facing explanation", claimIds: [], required: true },
    { id: "g2", kind: "list" as const, items: ["First", "Second"], claimIds: [], required: true }
  ],
  speakerNotes: [], evidenceRequests: []
};
const intent = {
  pageId: "p", focalMessage: "Message",
  hierarchy: [{ contentGroupId: "g1", priority: 1 }, { contentGroupId: "g2", priority: 2 }],
  groups: [{ id: "dg", contentGroupIds: ["g1", "g2"], treatment: "paired" as const }],
  relationships: [], visualStrategy: "subject" as const, balance: "asymmetric" as const,
  flow: "horizontal" as const, density: "low" as const, emphasis: [],
  mediaRequests: [{ id: "m", identityId: "identity-a", semanticEntityId: "entity-a", visualIdentityKey: "visual-a", reusePolicy: "exact" as const, claimIds: [], role: "subject" as const, description: "subject", fit: "contain" as const, focalPolicy: "subject" as const, required: true }],
  avoid: []
};
const design: DeckDesignPlan = versioned({
  briefId: "brief", designSeed: "seed", tone: ["clear"],
  typography: { character: "friendly", headingFamily: "Arial", bodyFamily: "Arial", headingWeight: 700, bodyWeight: 400 },
  palette: { mood: "clear", background: "#ffffff", surface: "#f3f4f6", text: "#111111", primary: "#047857", secondary: "#f97316", accent: "#facc15", muted: "#cbd5e1" },
  visualGrammar: { typographyCharacter: "friendly", shapeVocabulary: { character: "soft", forms: ["rounded-rectangle", "circle"], strokeStyle: "subtle", cornerStyle: "round" }, motifRules: [], mediaLanguage: { rendering: "illustrated", backgroundTreatment: "spatial", subjectTreatment: "consistent", consistencyRule: "preserve identity" }, variationPolicy: { continuityStrength: "high", diversityStrength: "medium" } },
  densityTarget: "airy", rhythm: { variation: "moderate", continuity: ["consistent type"] }, consistencyRules: ["one focal message"], crossPageConstraints: [],
  assetIdentities: [{ id: "identity-a", semanticEntityId: "entity-a", visualIdentityKey: "visual-a", role: "subject", reusePolicy: "exact" }]
});
const tokens = {
  background: "#ffffff", surface: "#f3f4f6", text: "#111111", textOnPrimary: "#ffffff",
  primary: "#047857", secondary: "#f97316", accent: "#facc15", muted: "#cbd5e1",
  headingFontFamily: "Arial", bodyFontFamily: "Arial", headingWeight: 700, bodyWeight: 400,
  deckTitlePt: 56, titlePt: 40, bodyPt: 20, captionPt: 16, lineHeight: 1.2, space: 16,
  safeInset: 36, radius: 10, strokeWidth: 1, motif: "organic"
};

test("creates two to four constraint-valid candidates for different canvases", () => {
  for (const canvas of [{ width: 960, height: 540 }, { width: 720, height: 720 }, { width: 540, height: 960 }]) {
    const result = composePage(page, intent, design, [], canvas, tokens);
    assert.ok(result.length >= 2 && result.length <= 8);
    assert.equal(result.filter((candidate) => candidate.selected).length, 1);
    assert.ok(result.every((candidate) => candidate.hardFailures.length === 0));
    assert.ok(result.every((candidate) => candidate.resolved.children.length > 0));
  }
});

test("headline participates in distinct semantic structures without a fixed title band", () => {
  const result = composePage(page, intent, design, [], { width: 960, height: 540 }, tokens);
  const allTrees = generateCandidateTrees(page, intent, design, []);
  const serialized = allTrees.map((candidate) => JSON.stringify(candidate.tree));
  assert.equal(serialized.some((tree) => tree.includes("title-band") || tree.includes("title-and-body")), false);
  assert.ok(serialized.some((tree) => tree.includes("headline-anchor")));
  assert.ok(new Set(result.map((candidate) => candidate.silhouette)).size > 1);
});

test("deck selection penalizes identical adjacent silhouettes", () => {
  const pages = [page, { ...page, id: "p2", headline: "Another clear title", contentGroups: page.contentGroups.map((group) => ({ ...group, id: `${group.id}-2` })) }];
  const intents = [intent, { ...intent, pageId: "p2", hierarchy: intent.hierarchy.map((item) => ({ ...item, contentGroupId: `${item.contentGroupId}-2` })), groups: [{ ...intent.groups[0]!, id: "dg2", contentGroupIds: ["g1-2", "g2-2"] }], mediaRequests: [{ ...intent.mediaRequests[0]!, id: "m2" }] }];
  const outline: NarrativeOutline = versioned({ briefId: "brief", pages, arc: { centralOutcome: "understand", sections: [{ id: "section-a", purpose: "explain", pageIds: ["p", "p2"], transition: "continue" }], pageLinks: [] }, confirmedAt: null });
  const constraints = new RelationConstraintCompiler().compile(outline, design);
  const sets = composeDeck(outline, intents, design, { width: 960, height: 540 }, tokens);
  assert.equal(sets.length, 2);
  assert.equal(sets.every((set) => set.filter((candidate) => candidate.selected).length === 1), true);
});

test("content-count and canvas variations terminate with traceable legal candidates", () => {
  const canvases = [{ width: 960, height: 540 }, { width: 720, height: 720 }, { width: 540, height: 960 }];
  for (let index = 0; index < 36; index += 1) {
    const groupCount = index % 12 + 1;
    const mediaCount = index * 5 % 9;
    const groups = Array.from({ length: groupCount }, (_, groupIndex) => ({ id: `property-g-${index}-${groupIndex}`, kind: "paragraph" as const, text: "content ".repeat((index + groupIndex) % 3 + 1), claimIds: [], required: true }));
    const propertyPage = { ...page, id: `property-p-${index}`, headline: "A deterministic heading", contentGroups: groups };
    const mediaRequests = Array.from({ length: mediaCount }, (_, mediaIndex) => ({ ...intent.mediaRequests[0]!, id: `property-m-${index}-${mediaIndex}`, identityId: `property-i-${index}-${mediaIndex}`, semanticEntityId: `property-e-${index}-${mediaIndex}`, visualIdentityKey: `property-v-${index}-${mediaIndex}` }));
    const propertyIntent = { ...intent, pageId: propertyPage.id, hierarchy: groups.map((group, groupIndex) => ({ contentGroupId: group.id, priority: Math.min(5, groupIndex + 1) })), groups: [{ id: `property-dg-${index}`, contentGroupIds: groups.map((group) => group.id), treatment: "progressive" as const }], mediaRequests };
    const result = composePage(propertyPage, propertyIntent, design, [], canvases[index % canvases.length]!, tokens);
    assert.ok(result.length >= 2);
    assert.ok(result.every((candidate) => candidate.hardFailures.length === 0 && candidate.trace.differences.length === 4));
    assert.ok(result.flatMap((candidate) => candidate.resolved.children).every((node) => Object.values(node.bounds).every(Number.isFinite)));
  }
});
