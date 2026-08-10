import { randomUUID } from "node:crypto";
import {
  NarrativeOutlineSchema,
  NarrativePageSchema,
  PresentationBriefSchema,
  versioned,
  type AssetPlan,
  type DeckDesignPlan,
  type NarrativeOutline,
  type PageDesignIntent,
  type PresentationBrief,
  type QualityReport,
  type SceneGraph
} from "@sparkdeck/presentation-model";
import { resolveDesignTokens, type DesignTokens } from "@sparkdeck/design-language";
import { composeDeck, type ResolvedCandidate } from "@sparkdeck/composition-engine";
import { buildAssetPlan, buildImageRequest } from "@sparkdeck/asset-planning";
import { applySceneCommand, compileSceneGraph, type SceneCommand } from "@sparkdeck/scene-graph";
import { applyVisualReview, buildVisualReviewBatch, evaluateScene } from "@sparkdeck/quality-engine";
import { exportSceneToPptx } from "@sparkdeck/pptx-export";
import type { Job } from "../../domain/jobs/job.js";
import type { GenerateImageUseCase } from "../use-cases/generate-image.use-case.js";
import { AppError } from "../../shared/errors/app-error.js";
import { DesignPlanner, NarrativePlanner, promptHash } from "./planning.service.js";
import type { ReviewVisualQualityUseCase } from "../use-cases/review-visual-quality.use-case.js";
import type { PresentationState, PresentationStateRepositoryPort, StoredAsset } from "../ports/presentation-state-repository.port.js";

type Usage = { id: string; provider: string; model: string; purpose: string; scopeId: string; requestHash: string; estimatedCostRmb: number; success: boolean; parentJob: string };
export class PresentationPlatformService {
  private readonly jobs = new Map<string, Job>();
  private readonly idempotentJobs = new Map<string, string>();
  private readonly usage: Usage[] = [];
  private readonly assetCache = new Map<string, string>();
  private readonly id = (prefix: string) => `${prefix}_${randomUUID()}`;

  constructor(private readonly repository: PresentationStateRepositoryPort, private readonly narrative: NarrativePlanner, private readonly designer: DesignPlanner, private readonly image: GenerateImageUseCase | undefined, private readonly visualReviewer?: ReviewVisualQualityUseCase) {}

  create(input: Omit<PresentationBrief, "schemaVersion" | "revision" | "contentHash" | "upstreamHashes" | "id">) {
    const id = this.id("pres");
    const brief = PresentationBriefSchema.parse(versioned({ id, ...input }));
    this.repository.save({ brief, assets: {}, repairCount: 0, history: [], future: [] });
    return brief;
  }

  list() { return this.repository.list().map((record) => record.brief); }
  get(id: string) {
    const value = this.repository.get(id);
    if (!value) throw new AppError("PRESENTATION_NOT_FOUND", "Presentation not found", 404);
    return value;
  }
  getJob(id: string) {
    const job = this.jobs.get(id);
    if (!job) throw new AppError("JOB_NOT_FOUND", "Job not found", 404);
    return job;
  }

  private newJob(scopeId: string, type: string, idempotencyKey: string): { job: Job; existing: boolean } {
    const lookup = `${scopeId}:${type}:${idempotencyKey}`;
    const existingId = this.idempotentJobs.get(lookup);
    if (existingId) return { job: this.getJob(existingId), existing: true };
    const job: Job = { id: this.id("job"), scopeId, type, status: "queued", progress: 0, stage: "queued", resultRef: null, error: null };
    this.jobs.set(job.id, job);
    this.idempotentJobs.set(lookup, job.id);
    return { job, existing: false };
  }
  private update(job: Job, patch: Partial<Job>) { Object.assign(job, patch); this.jobs.set(job.id, job); }
  private fail(job: Job, error: unknown) {
    this.update(job, { status: "failed", progress: 100, stage: "failed", error: { code: error instanceof AppError ? error.code : "JOB_FAILED", message: error instanceof Error ? error.message : "Job failed", incurredCost: false, freeRetryAllowed: false } });
  }
  private assetView(state: PresentationState) {
    return Object.fromEntries(Object.entries(state.assets).map(([id, asset]) => [id, { url: asset.url, dataUri: asset.base64 ? `data:image/png;base64,${asset.base64}` : undefined, alt: asset.alt }]));
  }
  private persist(state: PresentationState) { this.repository.save(state); }
  private compile(state: PresentationState, presentationId: string) {
    if (!state.outline || !state.design || !state.tokens || !state.candidates || !state.scene) throw new AppError("COMPOSITION_NOT_FOUND", "Composition is incomplete", 409);
    const revision = state.scene.revision + 1;
    state.scene = compileSceneGraph({ presentationId, outline: state.outline, intents: state.design.intents, candidateSets: state.candidates, tokens: state.tokens, canvas: state.scene.canvas, revision, ...(state.assetPlan ? { assetPlan: state.assetPlan } : {}), assets: this.assetView(state) });
    delete state.quality;
    delete state.visualReview;
  }
  private refreshAssetPlan(state: PresentationState, presentationId: string) {
    if (!state.outline || !state.design || !state.candidates) throw new AppError("COMPOSITION_NOT_FOUND", "Composition is incomplete", 409);
    const previous = state.assetPlan;
    const next = buildAssetPlan({ presentationId, outline: state.outline, intents: state.design.intents, candidateSets: state.candidates });
    if (previous) {
      for (const placement of next.placements) {
        const old = previous.placements.find((candidate) => candidate.requestId === placement.requestId && candidate.assetId);
        if (old?.assetId) { placement.assetId = old.assetId; placement.source = old.source; placement.promptHash = old.promptHash; }
      }
      next.resolvedAssetIds = [...new Set(next.placements.map((placement) => placement.assetId).filter((assetId): assetId is string => Boolean(assetId)))];
    }
    state.assetPlan = next;
  }

  startOutline(id: string, idempotencyKey: string) {
    const state = this.get(id);
    const { job, existing } = this.newJob(id, "outline.generate", idempotencyKey);
    if (existing) return job;
    void (async () => {
      try {
        this.update(job, { status: "running", stage: "planning", progress: 20 });
        const planned = await this.narrative.plan(state.brief);
        state.outline = planned.value;
        this.persist(state);
        this.usage.push({ id: this.id("usage"), provider: "dmx", model: planned.telemetry.model, purpose: "narrative", scopeId: id, requestHash: promptHash(state.brief), estimatedCostRmb: planned.telemetry.estimatedCostRmb, success: true, parentJob: job.id });
        this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.outline.contentHash });
      } catch (error) { this.fail(job, error); }
    })();
    return job;
  }

  saveOutline(id: string, outline: unknown, expectedRevision: number) {
    const state = this.get(id);
    if ((state.outline?.revision ?? 0) !== expectedRevision) throw new AppError("REVISION_CONFLICT", "Outline revision conflict", 409);
    const payload = NarrativePageSchema.array().min(1).parse((outline as { pages?: unknown }).pages);
    state.outline = NarrativeOutlineSchema.parse(versioned({ pages: payload, briefId: id, confirmedAt: null }, expectedRevision + 1, { brief: state.brief.contentHash }));
    delete state.design; delete state.tokens; delete state.candidates; delete state.assetPlan; delete state.scene; delete state.quality;
    this.persist(state);
    return state.outline;
  }

  confirmOutline(id: string, expectedRevision: number) {
    const state = this.get(id);
    if (!state.outline) throw new AppError("OUTLINE_NOT_FOUND", "Outline not found", 404);
    if (state.outline.revision !== expectedRevision) throw new AppError("REVISION_CONFLICT", "Outline revision conflict", 409);
    state.outline = NarrativeOutlineSchema.parse({ ...state.outline, confirmedAt: new Date().toISOString(), revision: state.outline.revision + 1 });
    this.persist(state);
    return state.outline;
  }

  startDesign(id: string, idempotencyKey: string) {
    const state = this.get(id);
    const { job, existing } = this.newJob(id, "design.generate", idempotencyKey);
    if (existing) return job;
    void (async () => {
      try {
        if (!state.outline?.confirmedAt) throw new AppError("OUTLINE_NOT_CONFIRMED", "Confirm outline first", 409);
        this.update(job, { status: "running", stage: "planning", progress: 20 });
        const planned = await this.designer.plan(state.brief, state.outline);
        state.design = planned.value;
        state.tokens = resolveDesignTokens(state.design.plan);
        this.persist(state);
        this.usage.push({ id: this.id("usage"), provider: "dmx", model: planned.telemetry.model, purpose: "design", scopeId: id, requestHash: promptHash(state.outline), estimatedCostRmb: planned.telemetry.estimatedCostRmb, success: true, parentJob: job.id });
        this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.design.plan.contentHash });
      } catch (error) { this.fail(job, error); }
    })();
    return job;
  }

  compose(id: string, canvas = { width: 960, height: 540 }, idempotencyKey: string) {
    const state = this.get(id);
    const { job, existing } = this.newJob(id, "composition.generate", idempotencyKey);
    if (existing) return job;
    try {
      if (!state.outline || !state.design || !state.tokens) throw new AppError("DESIGN_NOT_FOUND", "Generate design first", 409);
      this.update(job, { status: "running", stage: "generating_candidates", progress: 20 });
      state.candidates = composeDeck(state.outline.pages, state.design.intents, canvas, state.tokens);
      this.update(job, { stage: "scoring", progress: 65 });
      state.assetPlan = buildAssetPlan({ presentationId: id, outline: state.outline, intents: state.design.intents, candidateSets: state.candidates });
      state.scene = compileSceneGraph({ presentationId: id, outline: state.outline, intents: state.design.intents, candidateSets: state.candidates, tokens: state.tokens, canvas, assetPlan: state.assetPlan, assets: this.assetView(state) });
      this.persist(state);
      this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.scene.contentHash });
    } catch (error) { this.fail(job, error); }
    return job;
  }

  async resolveAssets(id: string, idempotencyKey: string) {
    const state = this.get(id);
    const { job, existing } = this.newJob(id, "assets.resolve", idempotencyKey);
    if (existing) return job;
    try {
      if (!state.assetPlan || !state.scene || !state.design) throw new AppError("COMPOSITION_NOT_FOUND", "Compose before assets", 409);
      this.update(job, { status: "running", stage: "resolving_assets", progress: 10 });
      for (const [index, placement] of state.assetPlan.placements.entries()) {
        if (placement.assetId) continue;
        const request = state.design.intents.flatMap((intent) => intent.mediaRequests).find((item) => item.id === placement.requestId);
        if (!request || !this.image) continue;
        const spec = buildImageRequest({ request, targetAspectRatio: placement.targetAspectRatio, illustrationDirection: state.design.plan.illustrationDirection });
        const cachedAssetId = this.assetCache.get(spec.promptHash);
        if (cachedAssetId && state.assets[cachedAssetId]) {
          placement.assetId = cachedAssetId; placement.source = "cache"; placement.promptHash = spec.promptHash;
        } else {
          const result = await this.image.execute({ prompt: spec.prompt, size: spec.size });
          const assetId = this.id("asset");
          state.assets[assetId] = { ...(result.url ? { url: result.url } : {}), ...(result.base64 ? { base64: result.base64 } : {}), alt: request.description, promptHash: spec.promptHash };
          this.assetCache.set(spec.promptHash, assetId);
          placement.assetId = assetId; placement.source = "generated"; placement.promptHash = spec.promptHash;
          this.usage.push({ id: this.id("usage"), provider: "dmx", model: result.model, purpose: "image", scopeId: placement.id, requestHash: spec.promptHash, estimatedCostRmb: result.estimatedCostRmb, success: true, parentJob: job.id });
        }
        this.update(job, { progress: 10 + Math.round((index + 1) / Math.max(1, state.assetPlan.placements.length) * 80) });
      }
      state.assetPlan.resolvedAssetIds = [...new Set(state.assetPlan.placements.map((placement) => placement.assetId).filter((assetId): assetId is string => Boolean(assetId)))];
      this.compile(state, id);
      this.persist(state);
      this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.scene?.contentHash ?? null });
    } catch (error) { this.fail(job, error); }
    return job;
  }

  async quality(id: string, idempotencyKey: string) {
    const state = this.get(id);
    const { job, existing } = this.newJob(id, "quality.evaluate", idempotencyKey);
    if (existing) return job;
    try {
      if (!state.scene) throw new AppError("SCENE_NOT_FOUND", "Scene not found", 404);
      this.update(job, { status: "running", stage: "rule_quality", progress: 50 });
      state.quality = evaluateScene(state.scene, { ...(state.assetPlan ? { assetPlan: state.assetPlan } : {}) });
      this.update(job, { stage: "visual_quality", progress: 75 });
      state.visualReview = buildVisualReviewBatch(state.scene, state.quality);
      if (this.visualReviewer && state.quality.passed && state.visualReview.pageIds.length) {
        const reviewed = await this.visualReviewer.execute(state.scene, state.visualReview.pageIds, state.visualReview.instructions);
        state.quality = applyVisualReview(state.quality, reviewed.issues);
        this.usage.push({ id: this.id("usage"), provider: "dmx", model: reviewed.model, purpose: "visual-quality", scopeId: id, requestHash: promptHash({ scene: state.scene.contentHash, pages: state.visualReview.pageIds }), estimatedCostRmb: reviewed.estimatedCostRmb, success: true, parentJob: job.id });
      }
      this.persist(state);
      this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.quality.contentHash });
    } catch (error) { this.fail(job, error); }
    return job;
  }

  repair(id: string, idempotencyKey: string) {
    const state = this.get(id);
    const { job, existing } = this.newJob(id, "quality.repair", idempotencyKey);
    if (existing) return job;
    try {
      if (!state.scene || !state.quality || !state.candidates || !state.outline || !state.design || !state.tokens) throw new AppError("QUALITY_NOT_FOUND", "Run quality before repair", 409);
      if (state.repairCount >= 1) throw new AppError("REPAIR_LIMIT_REACHED", "Automatic repair is limited to one pass", 409);
      this.update(job, { status: "running", stage: "repairing", progress: 30 });
      const failed = new Set(state.quality.issues.filter((issue) => issue.severity === "error" && issue.pageId).map((issue) => issue.pageId));
      state.candidates.forEach((set, index) => {
        if (!failed.has(state.outline!.pages[index]?.id)) return;
        const alternatives = set.filter((candidate) => !candidate.selected).sort((left, right) => right.score - left.score);
        if (alternatives[0]) set.forEach((candidate) => { candidate.selected = candidate.id === alternatives[0]!.id; });
      });
      this.refreshAssetPlan(state, id);
      this.compile(state, id);
      state.repairCount += 1;
      state.quality = { ...evaluateScene(state.scene!, { ...(state.assetPlan ? { assetPlan: state.assetPlan } : {}) }), repairCount: state.repairCount };
      this.persist(state);
      this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.quality.contentHash });
    } catch (error) { this.fail(job, error); }
    return job;
  }

  command(id: string, input: SceneCommand) {
    const state = this.get(id);
    if (!state.scene) throw new AppError("SCENE_NOT_FOUND", "Scene not found", 404);
    const previous = state.scene;
    try { state.scene = applySceneCommand(state.scene, input); }
    catch (error) { throw new AppError(error instanceof Error && error.message === "NODE_NOT_FOUND" ? "NODE_NOT_FOUND" : "REVISION_CONFLICT", error instanceof Error ? error.message : "Scene command failed", 409); }
    state.history.push(previous); state.future = []; delete state.quality; delete state.visualReview;
    this.persist(state);
    return state.scene;
  }
  undo(id: string) { const state = this.get(id); const previous = state.history.pop(); if (!previous || !state.scene) return state.scene; state.future.push(state.scene); state.scene = previous; delete state.quality; this.persist(state); return state.scene; }
  redo(id: string) { const state = this.get(id); const next = state.future.pop(); if (!next || !state.scene) return state.scene; state.history.push(state.scene); state.scene = next; delete state.quality; this.persist(state); return state.scene; }

  selectCandidate(id: string, pageId: string, candidateId: string, expectedRevision: number) {
    const state = this.get(id);
    if (!state.scene || state.scene.revision !== expectedRevision) throw new AppError("REVISION_CONFLICT", "Scene revision conflict", 409);
    const pageIndex = state.outline?.pages.findIndex((page) => page.id === pageId) ?? -1;
    const set = state.candidates?.[pageIndex];
    if (!set?.some((candidate) => candidate.id === candidateId)) throw new AppError("CANDIDATE_NOT_FOUND", "Candidate not found", 404);
    set.forEach((candidate) => { candidate.selected = candidate.id === candidateId; });
    this.refreshAssetPlan(state, id);
    this.compile(state, id);
    this.persist(state);
    return state.scene;
  }

  async export(id: string) {
    const state = this.get(id);
    if (!state.scene) throw new AppError("SCENE_NOT_FOUND", "Scene not found", 404);
    if (!state.quality?.passed || state.quality.upstreamHashes.scene !== state.scene.contentHash) throw new AppError("QUALITY_GATE_FAILED", "Quality gate has not passed for the current revision", 409);
    return exportSceneToPptx(state.scene);
  }
  usageLedger(id: string) {
    const jobIds = new Set([...this.jobs.values()].filter((job) => job.scopeId === id).map((job) => job.id));
    return this.usage.filter((item) => jobIds.has(item.parentJob));
  }
}
