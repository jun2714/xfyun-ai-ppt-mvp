import assert from "node:assert/strict";
import test from "node:test";
import { versioned, type DeckDesignPlan, type NarrativeOutline, type PageDesignIntent, type PresentationBrief } from "@sparkdeck/presentation-model";
import { PresentationPlatformService } from "./application/services/presentation-platform.service.js";
import { MemoryPresentationStateRepository } from "./infrastructure/persistence/memory/memory-presentation-state-repository.js";
import { AppError } from "./shared/errors/app-error.js";

const page = { id: "page-a", purpose: "explain", headline: "A clear idea", message: "One message", contentGroups: [{ id: "group-a", kind: "paragraph" as const, text: "Audience-facing content", claimIds: [], required: true }, { id: "group-b", kind: "annotation" as const, text: "Supporting annotation", claimIds: [], required: true }], speakerNotes: [], evidenceRequests: [] };
const outline = (brief: PresentationBrief): NarrativeOutline => versioned({ briefId: brief.id, pages: [page], arc: { centralOutcome: "understand", sections: [{ id: "section-a", purpose: "explain", pageIds: ["page-a"], transition: "complete" }], pageLinks: [] }, confirmedAt: null }, 0, { brief: brief.contentHash });
const plan = (brief: PresentationBrief): DeckDesignPlan => versioned({
  briefId: brief.id, designSeed: "seed", tone: ["warm"],
  typography: { character: "friendly", headingFamily: "Microsoft YaHei", bodyFamily: "Microsoft YaHei", headingWeight: 700, bodyWeight: 400 },
  palette: { mood: "bright", background: "#FFF8EB", surface: "#FFFFFF", text: "#334155", primary: "#4F9C67", secondary: "#F28C45", accent: "#F2C94C", muted: "#CBD5E1" },
  visualGrammar: { typographyCharacter: "friendly", shapeVocabulary: { character: "soft", forms: ["rounded-rectangle", "circle"], strokeStyle: "subtle", cornerStyle: "round" }, motifRules: [], mediaLanguage: { rendering: "illustrated", backgroundTreatment: "spatial", subjectTreatment: "consistent", consistencyRule: "preserve identity" }, variationPolicy: { continuityStrength: "high", diversityStrength: "medium" } },
  densityTarget: "airy", rhythm: { variation: "moderate", continuity: ["consistent color"] }, consistencyRules: ["one focal message"], crossPageConstraints: [],
  assetIdentities: [{ id: "identity-a", semanticEntityId: "entity-a", visualIdentityKey: "visual-a", role: "subject", reusePolicy: "exact" }]
});
const intent: PageDesignIntent = {
  pageId: "page-a", focalMessage: "One message", hierarchy: [{ contentGroupId: "group-a", priority: 1 }, { contentGroupId: "group-b", priority: 2 }],
  groups: [{ id: "design-group", contentGroupIds: ["group-a", "group-b"], treatment: "paired" }], relationships: [], visualStrategy: "subject", balance: "asymmetric", flow: "horizontal", density: "low", emphasis: [],
  mediaRequests: [{ id: "media-a", identityId: "identity-a", semanticEntityId: "entity-a", visualIdentityKey: "visual-a", reusePolicy: "exact", claimIds: [], role: "subject", description: "supporting subject", fit: "contain", focalPolicy: "subject", required: true }], avoid: []
};

test("full flow delays images until selected composition and reuses idempotent jobs", async () => {
  let imageCalls = 0;
  let releaseReplacement!: () => void;
  const replacementGate = new Promise<void>((resolve) => { releaseReplacement = resolve; });
  const telemetry = { model: "fake-text", inputTokens: 100, outputTokens: 200, estimatedCostRmb: 0.001, prompt: { id: "test", version: "008.0-test", contentHash: "a".repeat(64) } };
  const narrative = { plan: async (brief: PresentationBrief) => ({ value: outline(brief), telemetry }) } as NarrativePlannerLike;
  const designer = { plan: async (brief: PresentationBrief) => ({ value: { plan: plan(brief), intents: [intent] }, telemetry }) } as DesignPlannerLike;
  const image = { requestHash: () => "request-hash", execute: async () => { imageCalls += 1; return { model: "fake", base64: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=", requestHash: "request-hash", estimatedCostRmb: 0 }; } } as ImageUseCaseLike;
  const renderEvidence = { create: async (scene: { presentationId: string; pages: { id: string; width: number; height: number }[] }) => ({ evidence: versioned({ presentationId: scene.presentationId, pages: scene.pages.map((item) => ({ pageId: item.id, sceneImageHash: "a".repeat(64), pptxImageHash: "b".repeat(64), differenceScore: 0, width: item.width, height: item.height })), passed: true, pptxHash: "c".repeat(64) }, 0, { scene: "d".repeat(64) }), contactSheetDataUri: "data:image/png;base64,AAAA" }) };
  const assetValidator = { validate: async (input: { base64?: string; url?: string }) => { if (input.url) await replacementGate; return { base64: input.base64 ?? "replacement", width: 1024, height: 1024, hasMeaningfulTransparency: false }; } };
  const textMeasurer = { measure: (input: { text: string; fontSize: number; lineHeight: number }) => ({ width: input.text.length * input.fontSize, height: input.fontSize * input.lineHeight, lines: 1 }) };
  const visualReviewer = { execute: async () => ({ issues: [], model: "fake-vision", inputTokens: 1, outputTokens: 1, estimatedCostRmb: 0, prompt: { id: "test", version: "008.0-test", contentHash: "b".repeat(64) } }) };
  const service = new PresentationPlatformService(new MemoryPresentationStateRepository(), narrative as never, designer as never, renderEvidence as never, assetValidator as never, textMeasurer as never, image as never, visualReviewer as never);
  const brief = service.create({ title: "Unknown subject", audience: "learners", usageContext: "classroom", objective: "understand", pageCount: 1, constraints: [], sourceAssetIds: [], language: "en" });
  service.startOutline(brief.id, "outline-once");
  await new Promise((resolve) => setTimeout(resolve, 0));
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
  assert.equal(service.get(brief.id).assetBundle?.resolvedAssetIds.length, 1);
  await service.quality(brief.id, "quality-once");
  assert.equal(service.get(brief.id).quality?.passed, true);
  const artifact = await service.export(brief.id);
  assert.equal(String.fromCharCode(...artifact.bytes.slice(0, 2)), "PK");

  // A remote image validation may finish after another editor command. The
  // stale network result must lose instead of overwriting the newer revision.
  const editable = service.get(brief.id).scene!;
  const imageNode = editable.pages[0]!.nodes.find((node) => node.kind === "image")!;
  const textNode = editable.pages[0]!.nodes.find((node) => node.kind === "text")!;
  const replacing = service.command(brief.id, { type: "set-asset", pageId: "page-a", nodeId: imageNode.id, value: "https://example.com/replacement.png", expectedRevision: editable.revision });
  await service.command(brief.id, { type: "set-text", pageId: "page-a", nodeId: textNode.id, value: "Newer edit wins", expectedRevision: editable.revision });
  releaseReplacement();
  await assert.rejects(replacing, (error: unknown) => error instanceof AppError && error.code === "REVISION_CONFLICT");
  assert.equal(service.get(brief.id).scene!.pages[0]!.nodes.find((node) => node.id === textNode.id)?.content.text, "Newer edit wins");
});

type PlanningTelemetry = { model: string; inputTokens: number; outputTokens: number; estimatedCostRmb: number; prompt: { id: string; version: string; contentHash: string } };
type NarrativePlannerLike = { plan(brief: PresentationBrief): Promise<{ value: NarrativeOutline; telemetry: PlanningTelemetry }> };
type DesignPlannerLike = { plan(brief: PresentationBrief): Promise<{ value: { plan: DeckDesignPlan; intents: PageDesignIntent[] }; telemetry: PlanningTelemetry }> };
type ImageUseCaseLike = { requestHash(input: unknown): string; execute(input: unknown): Promise<{ model: string; base64: string; requestHash: string; estimatedCostRmb: number }> };
