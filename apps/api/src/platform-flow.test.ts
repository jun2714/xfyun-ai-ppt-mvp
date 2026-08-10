import assert from "node:assert/strict";
import test from "node:test";
import { versioned, type DeckDesignPlan, type NarrativeOutline, type PageDesignIntent, type PresentationBrief } from "@sparkdeck/presentation-model";
import { PresentationPlatformService } from "./application/services/presentation-platform.service.js";
import { MemoryPresentationStateRepository } from "./infrastructure/persistence/memory/memory-presentation-state-repository.js";

const page = { id: "page-a", purpose: "explain", headline: "A clear idea", message: "One message", contentGroups: [{ id: "group-a", kind: "paragraph" as const, text: "Audience-facing content", claimIds: [], required: true }, { id: "group-b", kind: "annotation" as const, text: "Supporting annotation", claimIds: [], required: true }], speakerNotes: [], evidenceRequests: [], continuityLinks: [] };
const outline = (brief: PresentationBrief): NarrativeOutline => versioned({ briefId: brief.id, pages: [page], confirmedAt: null }, 0, { brief: brief.contentHash });
const plan = (brief: PresentationBrief): DeckDesignPlan => versioned({
  briefId: brief.id, designSeed: "seed", tone: ["warm"],
  typography: { character: "friendly", headingFamily: "Microsoft YaHei", bodyFamily: "Microsoft YaHei", headingWeight: 700, bodyWeight: 400 },
  palette: { mood: "bright", background: "#FFF8EB", surface: "#FFFFFF", text: "#334155", primary: "#4F9C67", secondary: "#F28C45", accent: "#F2C94C", muted: "#CBD5E1" },
  shapeLanguage: { character: "soft", cornerStyle: "round", strokeStyle: "subtle", motif: "organic curves" },
  illustrationDirection: "consistent editorial illustration", densityTarget: "airy", rhythm: { variation: "moderate", continuity: ["consistent color"] }, consistencyRules: ["one focal message"]
});
const intent: PageDesignIntent = {
  pageId: "page-a", focalMessage: "One message", hierarchy: [{ contentGroupId: "group-a", priority: 1 }, { contentGroupId: "group-b", priority: 2 }],
  groups: [{ id: "design-group", contentGroupIds: ["group-a", "group-b"], treatment: "paired" }], relationships: [], visualStrategy: "subject", balance: "asymmetric", flow: "horizontal", density: "low", emphasis: [],
  mediaRequests: [{ id: "media-a", claimIds: [], role: "subject", description: "supporting subject", fit: "contain", focalPolicy: "subject", required: true }], avoid: []
};

test("full flow delays images until selected composition and reuses idempotent jobs", async () => {
  let imageCalls = 0;
  const telemetry = { model: "fake-text", inputTokens: 100, outputTokens: 200, estimatedCostRmb: 0.001 };
  const narrative = { plan: async (brief: PresentationBrief) => ({ value: outline(brief), telemetry }) } as NarrativePlannerLike;
  const designer = { plan: async (brief: PresentationBrief) => ({ value: { plan: plan(brief), intents: [intent] }, telemetry }) } as DesignPlannerLike;
  const image = { execute: async () => { imageCalls += 1; return { model: "fake", base64: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=", estimatedCostRmb: 0 }; } } as ImageUseCaseLike;
  const service = new PresentationPlatformService(new MemoryPresentationStateRepository(), narrative as never, designer as never, image as never);
  const brief = service.create({ title: "Unknown subject", audience: "learners", usageContext: "classroom", objective: "understand", pageCount: 1, constraints: [], sourceAssetIds: [], language: "en" });
  const generatedOutline = outline(brief);
  service.saveOutline(brief.id, generatedOutline, 0);
  service.confirmOutline(brief.id, 1);
  service.startDesign(brief.id, "design-once");
  await new Promise((resolve) => setTimeout(resolve, 0));
  service.compose(brief.id, { width: 960, height: 540 }, "compose-once");
  const state = service.get(brief.id);
  assert.equal(imageCalls, 0);
  assert.ok((state.candidates?.[0]?.length ?? 0) >= 2);
  assert.equal(state.outline?.pages[0]?.contentGroups.length, 2);
  assert.ok(state.scene);
  const first = await service.resolveAssets(brief.id, "assets-once");
  const repeated = await service.resolveAssets(brief.id, "assets-once");
  assert.equal(first.id, repeated.id);
  assert.equal(imageCalls, 1);
  assert.equal(state.assetPlan?.resolvedAssetIds.length, 1);
  await service.quality(brief.id, "quality-once");
  assert.equal(state.quality?.passed, true);
  const artifact = await service.export(brief.id);
  assert.equal(String.fromCharCode(...artifact.bytes.slice(0, 2)), "PK");
});

type PlanningTelemetry = { model: string; inputTokens: number; outputTokens: number; estimatedCostRmb: number };
type NarrativePlannerLike = { plan(brief: PresentationBrief): Promise<{ value: NarrativeOutline; telemetry: PlanningTelemetry }> };
type DesignPlannerLike = { plan(brief: PresentationBrief): Promise<{ value: { plan: DeckDesignPlan; intents: PageDesignIntent[] }; telemetry: PlanningTelemetry }> };
type ImageUseCaseLike = { execute(input: unknown): Promise<{ model: string; base64: string; estimatedCostRmb: number }> };
