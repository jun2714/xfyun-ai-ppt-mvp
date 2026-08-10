import assert from "node:assert/strict";
import test from "node:test";
import { versioned, type NarrativeOutline, type PresentationBrief } from "@sparkdeck/presentation-model";
import { NarrativePlanner, validateNarrative } from "./application/services/planning.service.js";

const brief = versioned({ id: "brief-validation", title: "Validation subject", audience: "audience", usageContext: "review", objective: "understand", pageCount: 2, constraints: [], sourceAssetIds: [], language: "en" }) as PresentationBrief;
const page = (id: string, groupId: string) => ({ id, purpose: "explain", headline: `Headline ${id}`, message: `Message ${id}`, contentGroups: [{ id: groupId, kind: "paragraph" as const, text: `Content ${id}`, claimIds: [], required: true }], speakerNotes: [], evidenceRequests: [] });

test("narrative predicates validate concealed and introduced sources without layout semantics", () => {
  const pages = [page("page-a", "group-a"), page("page-b", "group-b")];
  const outline = versioned({ briefId: brief.id, pages, arc: { centralOutcome: "understand", sections: [{ id: "section-a", purpose: "explain", pageIds: ["page-a", "page-b"], transition: "continue" }], pageLinks: [{ id: "link-a", fromPageId: "page-a", toPageId: "page-b", predicates: [{ kind: "conceal" as const, sourceIds: ["group-b"], onPageId: "page-a" }, { kind: "introduce" as const, sourceIds: ["group-b"], onPageId: "page-b" }] }] }, confirmedAt: null }) as NarrativeOutline;
  assert.doesNotThrow(() => validateNarrative(outline, brief));
  const leaked = { ...outline, pages: [page("page-a", "group-b"), page("page-b", "group-c")] } as NarrativeOutline;
  assert.throws(() => validateNarrative(leaked, brief), /Concealed content is visible/);
});

test("invalid model JSON fails once without a paid automatic retry", async () => {
  let calls = 0;
  const text = { execute: async () => { calls += 1; return { content: "not-json", model: "fake", usage: { inputTokens: 1, outputTokens: 1, estimatedCostRmb: 0 } }; } };
  const prompt = { id: "narrative", version: "008.0-test", content: "contract", contentHash: "a".repeat(64) };
  const planner = new NarrativePlanner(text as never, { get: () => prompt } as never);
  await assert.rejects(() => planner.plan(brief), /valid JSON/);
  assert.equal(calls, 1);
});

test("narrative rejects repeated headlines and headline/body duplication", () => {
  const pages = [page("page-a", "group-a"), { ...page("page-b", "group-b"), headline: "Headline page-a" }];
  const repeated = versioned({ briefId: brief.id, pages, arc: { centralOutcome: "understand", sections: [{ id: "section-a", purpose: "explain", pageIds: ["page-a", "page-b"], transition: "continue" }], pageLinks: [] }, confirmedAt: null }) as NarrativeOutline;
  assert.throws(() => validateNarrative(repeated, brief), /headlines must not repeat/i);
  const duplicatedBody = { ...repeated, pages: [page("page-a", "group-a"), { ...page("page-b", "group-b"), headline: "Message page-b" }] } as NarrativeOutline;
  assert.throws(() => validateNarrative(duplicatedBody, brief), /repeats body copy/i);
});
