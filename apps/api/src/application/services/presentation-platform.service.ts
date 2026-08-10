import { randomUUID } from "node:crypto";
import {
  NarrativeOutlineSchema,
  PresentationBriefSchema,
  hashContent,
  versioned,
  type PresentationBrief,
  type SceneGraph
} from "@sparkdeck/presentation-model";
import { DEFAULT_CANVAS, resolveDesignTokens } from "@sparkdeck/design-language";
import { composeDeck, composePage, RelationConstraintCompiler, selectDeckCandidates, type RepairConstraint, type ResolvedCandidate } from "@sparkdeck/composition-engine";
import { buildAssetBundlePlan, buildImageRequest } from "@sparkdeck/asset-planning";
import { applySceneCommand, compileSceneGraph, type SceneCommand } from "@sparkdeck/scene-graph";
import { applyVisualReview, buildVisualReviewBatch, evaluateScene, type TextMeasurer } from "@sparkdeck/quality-engine";
import { exportSceneToPptx } from "@sparkdeck/pptx-export";
import type { Job } from "../../domain/jobs/job.js";
import type { GenerateImageUseCase } from "../use-cases/generate-image.use-case.js";
import type { RenderEvidencePort } from "../ports/render-evidence.port.js";
import { AppError } from "../../shared/errors/app-error.js";
import { DesignPlanner, NarrativePlanner, promptHash, validateNarrative } from "./planning.service.js";
import type { ReviewVisualQualityUseCase } from "../use-cases/review-visual-quality.use-case.js";
import type { PresentationState, PresentationStateRepositoryPort, StoredAsset, UsageLedgerEntry } from "../ports/presentation-state-repository.port.js";
import type { AssetValidationPort } from "../ports/asset-validation.port.js";

/** Coordinates versioned 008 use cases while keeping provider and renderer decisions in adapters. */
export class PresentationPlatformService {
  private readonly jobs = new Map<string, Job>();
  private readonly idempotentJobs = new Map<string, string>();
  private readonly usage: UsageLedgerEntry[] = [];
  private readonly assetCache = new Map<string, StoredAsset>();
  private readonly id = (prefix: string) => `${prefix}_${randomUUID()}`;

  constructor(
    private readonly repository: PresentationStateRepositoryPort,
    private readonly narrative: NarrativePlanner,
    private readonly designer: DesignPlanner,
    private readonly renderEvidence: RenderEvidencePort,
    private readonly assetValidator: AssetValidationPort,
    private readonly textMeasurer: TextMeasurer,
    private readonly image?: GenerateImageUseCase,
    private readonly visualReviewer?: ReviewVisualQualityUseCase
  ) {
    // Rehydrate operational records and asset cache so restart never causes duplicate paid work.
    for (const state of this.repository.list()) {
      let recoveredInterruptedJob = false;
      for (const job of state.jobs ?? []) {
        if (job.status === "queued" || job.status === "running") {
          Object.assign(job, { status: "failed", stage: "failed", progress: 100, error: { code: "PROCESS_INTERRUPTED", message: "The previous process stopped before this job completed", incurredCost: false, manualRetryAllowed: true } });
          recoveredInterruptedJob = true;
        }
        this.jobs.set(job.id, job);
      }
      for (const [key, jobId] of Object.entries(state.idempotency ?? {})) this.idempotentJobs.set(`${state.brief.id}:${key}`, jobId);
      this.usage.push(...(state.usage ?? []));
      for (const trace of state.assetTraces) if (trace.assetId && state.assets[trace.assetId]) this.assetCache.set(trace.requestHash, state.assets[trace.assetId]!);
      if (recoveredInterruptedJob) this.repository.save(state);
    }
  }

  create(input: Omit<PresentationBrief, "schemaVersion" | "revision" | "contentHash" | "upstreamHashes" | "id">) {
    const id = this.id("pres");
    const brief = PresentationBriefSchema.parse(versioned({ id, ...input }));
    this.repository.save({ brief, assets: {}, layoutTraces: {}, assetTraces: [], repairCount: 0, history: [], future: [], jobs: [], idempotency: {}, usage: [] });
    return brief;
  }

  list() { return this.repository.list().map((record) => record.brief); }
  get(id: string) { const value = this.repository.get(id); if (!value) throw new AppError("PRESENTATION_NOT_FOUND", "Presentation not found", 404); return value; }
  getJob(id: string) { const job = this.jobs.get(id); if (!job) throw new AppError("JOB_NOT_FOUND", "Job not found", 404); return job; }

  private newJob(state: PresentationState, type: string, idempotencyKey: string): { job: Job; existing: boolean } {
    const scopeId = state.brief.id;
    const lookup = `${scopeId}:${type}:${idempotencyKey}`;
    const existingId = this.idempotentJobs.get(lookup);
    if (existingId) return { job: this.getJob(existingId), existing: true };
    const job: Job = { id: this.id("job"), scopeId, type, status: "queued", progress: 0, stage: "queued", resultRef: null, error: null };
    this.jobs.set(job.id, job); this.idempotentJobs.set(lookup, job.id);
    state.jobs.push(job); state.idempotency[`${type}:${idempotencyKey}`] = job.id; this.persist(state);
    return { job, existing: false };
  }
  private update(job: Job, patch: Partial<Job>) {
    Object.assign(job, patch); this.jobs.set(job.id, job);
    const persisted = this.repository.get(job.scopeId);
    const durableJob = persisted?.jobs.find((item) => item.id === job.id);
    if (persisted && durableJob) { Object.assign(durableJob, patch); this.repository.save(persisted); }
  }
  private fail(job: Job, error: unknown) {
    const appError = error instanceof AppError ? error : undefined;
    this.update(job, { status: "failed", progress: 100, stage: "failed", error: { code: appError?.code ?? "JOB_FAILED", message: error instanceof Error ? error.message : "Job failed", incurredCost: appError?.context.incurredCost ?? false, manualRetryAllowed: appError?.context.manualRetryAllowed ?? false, ...(appError?.context.modelResponseEvidence ? { evidence: appError.context.modelResponseEvidence } : {}) } });
  }
  private persist(state: PresentationState) { this.repository.save(state); }
  /** Hashes only user/business state; job progress and append-only usage must not invalidate their own job. */
  private businessHash(state: PresentationState) {
    const { jobs: _jobs, idempotency: _idempotency, usage: _usage, ...business } = state;
    return hashContent(business);
  }
  /** Commits work produced from an immutable snapshot and preserves newer operational records. */
  private commitSnapshot(snapshot: PresentationState, capturedHash: string, stage: string, incurredCost: boolean) {
    const current = this.get(snapshot.brief.id);
    if (this.businessHash(current) !== capturedHash) {
      throw new AppError("REVISION_CONFLICT", `Presentation changed while ${stage} was running`, 409, [], { stage, incurredCost, manualRetryAllowed: true });
    }
    snapshot.jobs = current.jobs;
    snapshot.idempotency = current.idempotency;
    snapshot.usage = current.usage;
    this.persist(snapshot);
    return snapshot;
  }
  private recordUsage(state: PresentationState, entry: UsageLedgerEntry) {
    this.usage.push(entry); state.usage.push(entry);
    // Cost evidence is committed immediately, even when later validation rejects the paid response.
    const persisted = this.repository.get(state.brief.id);
    if (persisted && !persisted.usage.some((item) => item.id === entry.id)) { persisted.usage.push(entry); this.repository.save(persisted); }
  }
  private assetView(state: PresentationState) {
    return Object.fromEntries(Object.entries(state.assets).map(([id, asset]) => [id, { url: asset.base64 ? `/api/v1/presentations/${state.brief.id}/assets/${id}/content` : asset.url, alt: asset.alt }]));
  }

  /** Injects verified bytes only inside render/export memory so API Scene responses never expose base64. */
  private renderableScene(state: PresentationState): SceneGraph {
    if (!state.scene) throw new AppError("SCENE_NOT_FOUND", "Scene not found", 404);
    const scene = structuredClone(state.scene);
    for (const page of scene.pages) for (const node of page.nodes) if (node.kind === "image" && typeof node.content.assetId === "string") {
      const asset = state.assets[node.content.assetId];
      if (asset?.base64) { node.content.dataUri = `data:image/png;base64,${asset.base64}`; delete node.content.url; }
    }
    return scene;
  }

  /** Invalidates every artifact that depends on narrative content. */
  private invalidateAfterOutline(state: PresentationState) {
    delete state.design; delete state.tokens; delete state.canvas; delete state.candidates; delete state.assetBundle; delete state.scene; delete state.quality; delete state.visualReview; delete state.renderEvidence;
    state.layoutTraces = {}; state.assetTraces = []; state.history = []; state.future = [];
  }
  /** Invalidates geometry and evidence while retaining narrative and project-owned assets. */
  private invalidateAfterDesign(state: PresentationState) {
    delete state.canvas; delete state.candidates; delete state.assetBundle; delete state.scene; delete state.quality; delete state.visualReview; delete state.renderEvidence;
    state.layoutTraces = {}; state.assetTraces = []; state.history = []; state.future = [];
  }
  /** Any Scene mutation makes previous quality and exported render evidence stale. */
  private invalidateAfterScene(state: PresentationState) { delete state.quality; delete state.visualReview; delete state.renderEvidence; }

  private compile(state: PresentationState) {
    if (!state.outline || !state.design || !state.tokens || !state.candidates || !state.canvas) throw new AppError("COMPOSITION_NOT_FOUND", "Composition is incomplete", 409);
    const revision = (state.scene?.revision ?? -1) + 1;
    state.scene = compileSceneGraph({ presentationId: state.brief.id, outline: state.outline, intents: state.design.intents, candidateSets: state.candidates, tokens: state.tokens, canvas: state.canvas, revision, ...(state.assetBundle ? { assetPlan: state.assetBundle } : {}), assets: this.assetView(state) });
    this.invalidateAfterScene(state);
  }

  /** Rebuilds placements from selected geometry and preserves only identity-compatible resolved assets. */
  private refreshAssetBundle(state: PresentationState) {
    if (!state.outline || !state.design || !state.candidates) throw new AppError("COMPOSITION_NOT_FOUND", "Composition is incomplete", 409);
    const previous = state.assetBundle;
    const next = buildAssetBundlePlan({ presentationId: state.brief.id, outline: state.outline, design: state.design.plan, intents: state.design.intents, candidateSets: state.candidates });
    if (previous) for (const placement of next.placements) {
      const old = previous.placements.find((candidate) => candidate.identityId === placement.identityId && candidate.role === placement.role && candidate.assetId);
      if (old?.assetId && state.assets[old.assetId]?.identityId === placement.identityId) { placement.assetId = old.assetId; placement.source = old.source; placement.promptHash = old.promptHash; }
    }
    next.resolvedAssetIds = [...new Set(next.placements.map((placement) => placement.assetId).filter((assetId): assetId is string => Boolean(assetId)))];
    state.assetBundle = next;
  }

  startOutline(id: string, idempotencyKey: string) {
    const state = this.get(id); const { job, existing } = this.newJob(state, "narrative.generate", idempotencyKey); if (existing) return job;
    const capturedHash = this.businessHash(state);
    void (async () => {
      try {
        this.update(job, { status: "running", stage: "planning", progress: 20 });
        const planned = await this.narrative.plan(state.brief);
        this.recordUsage(state, { id: this.id("usage"), provider: "dmx", model: planned.telemetry.model, purpose: "narrative", scopeId: id, requestHash: promptHash({ brief: state.brief.contentHash, prompt: planned.telemetry.prompt.contentHash }), estimatedCostRmb: planned.telemetry.estimatedCostRmb, success: true, parentJob: job.id });
        this.invalidateAfterOutline(state); state.outline = planned.value;
        this.commitSnapshot(state, capturedHash, "narrative", true);
        this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.outline.contentHash });
      } catch (error) {
        if (error instanceof AppError && error.context.modelTelemetry) {
          const telemetry = error.context.modelTelemetry;
          this.recordUsage(state, { id: this.id("usage"), provider: "dmx", model: telemetry.model, purpose: "narrative", scopeId: id, requestHash: promptHash({ brief: state.brief.contentHash, prompt: telemetry.prompt.contentHash }), estimatedCostRmb: telemetry.estimatedCostRmb, success: false, parentJob: job.id });
        }
        this.fail(job, error);
      }
    })();
    return job;
  }

  saveOutline(id: string, outline: unknown, expectedRevision: number) {
    const state = this.get(id);
    if (!state.outline || state.outline.revision !== expectedRevision) throw new AppError("REVISION_CONFLICT", "Outline revision conflict", 409);
    const parsed = NarrativeOutlineSchema.pick({ pages: true, arc: true }).parse(outline);
    const next = NarrativeOutlineSchema.parse(versioned({ briefId: id, pages: parsed.pages, arc: parsed.arc, confirmedAt: null }, expectedRevision + 1, { brief: state.brief.contentHash }));
    validateNarrative(next, state.brief); this.invalidateAfterOutline(state); state.outline = next; this.persist(state); return next;
  }

  confirmOutline(id: string, expectedRevision: number) {
    const state = this.get(id); if (!state.outline) throw new AppError("OUTLINE_NOT_FOUND", "Outline not found", 404);
    if (state.outline.revision !== expectedRevision) throw new AppError("REVISION_CONFLICT", "Outline revision conflict", 409);
    const { briefId, pages, arc } = state.outline;
    state.outline = NarrativeOutlineSchema.parse(versioned({ briefId, pages, arc, confirmedAt: new Date().toISOString() }, expectedRevision + 1, { brief: state.brief.contentHash }));
    this.persist(state); return state.outline;
  }

  startDesign(id: string, idempotencyKey: string) {
    const state = this.get(id); const { job, existing } = this.newJob(state, "design.generate", idempotencyKey); if (existing) return job;
    const capturedHash = this.businessHash(state);
    void (async () => {
      try {
        if (!state.outline?.confirmedAt) throw new AppError("OUTLINE_NOT_CONFIRMED", "Confirm outline first", 409);
        this.update(job, { status: "running", stage: "planning", progress: 20 });
        const planned = await this.designer.plan(state.brief, state.outline);
        this.recordUsage(state, { id: this.id("usage"), provider: "dmx", model: planned.telemetry.model, purpose: "design", scopeId: id, requestHash: promptHash({ outline: state.outline.contentHash, prompt: planned.telemetry.prompt.contentHash }), estimatedCostRmb: planned.telemetry.estimatedCostRmb, success: true, parentJob: job.id });
        this.invalidateAfterDesign(state); state.design = planned.value; state.tokens = resolveDesignTokens(planned.value.plan);
        this.commitSnapshot(state, capturedHash, "design", true);
        this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: planned.value.plan.contentHash });
      } catch (error) {
        if (error instanceof AppError && error.context.modelTelemetry) {
          const telemetry = error.context.modelTelemetry;
          this.recordUsage(state, { id: this.id("usage"), provider: "dmx", model: telemetry.model, purpose: "design", scopeId: id, requestHash: promptHash({ outline: state.outline?.contentHash ?? state.brief.contentHash, prompt: telemetry.prompt.contentHash }), estimatedCostRmb: telemetry.estimatedCostRmb, success: false, parentJob: job.id });
        }
        this.fail(job, error);
      }
    })();
    return job;
  }

  compose(id: string, canvas = DEFAULT_CANVAS, idempotencyKey: string) {
    const state = this.get(id); const { job, existing } = this.newJob(state, "composition.generate", idempotencyKey); if (existing) return job;
    try {
      if (!state.outline || !state.design || !state.tokens) throw new AppError("DESIGN_NOT_FOUND", "Generate design first", 409);
      this.update(job, { status: "running", stage: "generating_candidates", progress: 20 });
      state.canvas = canvas; state.candidates = composeDeck(state.outline, state.design.intents, state.design.plan, canvas, state.tokens);
      state.layoutTraces = Object.fromEntries(state.candidates.flat().map((candidate) => [candidate.id, candidate.trace]));
      this.update(job, { stage: "scoring", progress: 65 });
      this.refreshAssetBundle(state); this.compile(state); this.persist(state);
      this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.scene!.contentHash });
    } catch (error) { this.fail(job, error); }
    return job;
  }

  async resolveAssets(id: string, idempotencyKey: string) {
    const state = this.get(id); const { job, existing } = this.newJob(state, "assets.resolve", idempotencyKey); if (existing) return job;
    const capturedHash = this.businessHash(state);
    try {
      if (!state.assetBundle || !state.scene || !state.design) throw new AppError("COMPOSITION_NOT_FOUND", "Compose before assets", 409);
      this.update(job, { status: "running", stage: "resolving_assets", progress: 10 });
      const unresolvedIdentityIds = [...new Set(state.assetBundle.placements.filter((placement) => !placement.assetId).map((placement) => placement.identityId))];
      for (const [index, identityId] of unresolvedIdentityIds.entries()) {
        const placements = state.assetBundle.placements.filter((placement) => placement.identityId === identityId && !placement.assetId);
        const placement = placements[0];
        const request = state.design.intents.flatMap((intent) => intent.mediaRequests).find((item) => item.identityId === identityId);
        if (!placement || !request || !this.image) continue;
        const spec = buildImageRequest({ request, targetAspectRatio: placement.targetAspectRatio, mediaLanguage: state.design.plan.visualGrammar.mediaLanguage });
        const modelInput = { context: { ...spec.context }, size: spec.size };
        const requestHash = this.image.requestHash(modelInput);
        const cached = this.assetCache.get(requestHash);
        const assetId = this.id("asset");
        if (cached) {
          state.assets[assetId] = structuredClone(cached);
          placements.forEach((item) => { item.assetId = assetId; item.source = "cache"; item.promptHash = requestHash; });
          state.assetTraces.push({ placementId: placement.id, identityId, requestHash, source: "cache", cacheHit: true, assetId });
        } else {
          const result = await this.image.execute(modelInput);
          this.recordUsage(state, { id: this.id("usage"), provider: "dmx", model: result.model, purpose: "image", scopeId: identityId, requestHash: result.requestHash, estimatedCostRmb: result.estimatedCostRmb, success: true, parentJob: job.id });
          const validated = await this.assetValidator.validate({ ...(result.url ? { url: result.url } : {}), ...(result.base64 ? { base64: result.base64 } : {}), role: request.role, targetAspectRatio: placement.targetAspectRatio, incurredCost: true });
          const asset: StoredAsset = { base64: validated.base64, alt: request.audienceAlt ?? "", promptHash: result.requestHash, identityId, role: request.role, width: validated.width, height: validated.height, qualityStatus: "passed" };
          state.assets[assetId] = asset; this.assetCache.set(result.requestHash, structuredClone(asset));
          placements.forEach((item) => { item.assetId = assetId; item.source = "generated"; item.promptHash = result.requestHash; });
          state.assetTraces.push({ placementId: placement.id, identityId, requestHash: result.requestHash, source: "generated", cacheHit: false, assetId });
        }
        this.update(job, { progress: 10 + Math.round((index + 1) / Math.max(1, unresolvedIdentityIds.length) * 80) });
      }
      state.assetBundle.resolvedAssetIds = [...new Set(state.assetBundle.placements.map((placement) => placement.assetId).filter((assetId): assetId is string => Boolean(assetId)))];
      this.compile(state); this.commitSnapshot(state, capturedHash, "asset resolution", unresolvedIdentityIds.length > 0);
      this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.scene!.contentHash });
    } catch (error) { this.fail(job, error); }
    return job;
  }

  async quality(id: string, idempotencyKey: string) {
    const state = this.get(id); const { job, existing } = this.newJob(state, "quality.evaluate", idempotencyKey); if (existing) return job;
    const capturedHash = this.businessHash(state);
    try {
      if (!state.scene || !state.outline) throw new AppError("SCENE_NOT_FOUND", "Scene not found", 404);
      this.update(job, { status: "running", stage: "rule_quality", progress: 50 });
      state.quality = evaluateScene(state.scene, { measurer: this.textMeasurer, outline: state.outline, ...(state.assetBundle ? { assetPlan: state.assetBundle } : {}) });
      let finalContactSheet: string | undefined;
      if (state.quality.passed) {
        const renderable = this.renderableScene(state);
        const artifact = await exportSceneToPptx(renderable);
        const rendered = await this.renderEvidence.create(renderable, artifact.bytes);
        state.renderEvidence = rendered.evidence;
        finalContactSheet = rendered.contactSheetDataUri;
        state.quality = evaluateScene(state.scene, { measurer: this.textMeasurer, outline: state.outline, ...(state.assetBundle ? { assetPlan: state.assetBundle } : {}), renderEvidence: state.renderEvidence });
      }
      state.visualReview = buildVisualReviewBatch(state.scene, state.quality);
      this.update(job, { stage: "visual_quality", progress: 75 });
      if (this.visualReviewer && state.quality.passed && state.visualReview.pageIds.length) {
        const reviewed = await this.visualReviewer.execute(state.scene, state.visualReview.pageIds, state.visualReview.dimensions, finalContactSheet);
        state.quality = applyVisualReview(state.quality, reviewed.issues);
        this.recordUsage(state, { id: this.id("usage"), provider: "dmx", model: reviewed.model, purpose: "visual-quality", scopeId: id, requestHash: promptHash({ scene: state.scene.contentHash, pages: state.visualReview.pageIds, prompt: reviewed.prompt.contentHash }), estimatedCostRmb: reviewed.estimatedCostRmb, success: true, parentJob: job.id });
      }
      this.commitSnapshot(state, capturedHash, "quality review", Boolean(this.visualReviewer && state.visualReview.pageIds.length));
      this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.quality.contentHash });
    } catch (error) { this.fail(job, error); }
    return job;
  }

  /** Converts quality failures into generic search constraints and recomposes linked page groups. */
  repair(id: string, idempotencyKey: string) {
    const state = this.get(id); const { job, existing } = this.newJob(state, "quality.repair", idempotencyKey); if (existing) return job;
    try {
      if (!state.scene || !state.quality || !state.candidates || !state.outline || !state.design || !state.tokens || !state.canvas) throw new AppError("QUALITY_NOT_FOUND", "Run quality before repair", 409);
      if (state.repairCount >= 1) throw new AppError("REPAIR_LIMIT_REACHED", "Automatic repair is limited to one pass", 409);
      this.update(job, { status: "running", stage: "repairing", progress: 30 });
      const failedPageIds = new Set(state.quality.issues.filter((issue) => issue.severity === "error" && issue.pageId).map((issue) => issue.pageId!));
      for (const link of state.outline.arc.pageLinks) if (link.fromPageId && (failedPageIds.has(link.fromPageId) || failedPageIds.has(link.toPageId))) { failedPageIds.add(link.fromPageId); failedPageIds.add(link.toPageId); }
      const repairs: RepairConstraint[] = [...failedPageIds].map((pageId) => ({
        id: `repair:${state.repairCount + 1}:${pageId}`,
        pageId,
        issueCodes: state.quality!.issues.filter((issue) => issue.pageId === pageId).map((issue) => issue.code),
        forbiddenGrammarHashes: state.candidates![state.outline!.pages.findIndex((page) => page.id === pageId)]?.filter((candidate) => candidate.selected).map((candidate) => candidate.grammarHash) ?? []
      }));
      const relationConstraints = new RelationConstraintCompiler().compile(state.outline, state.design.plan);
      const nextSets = state.outline.pages.map((page, index) => {
        if (!failedPageIds.has(page.id)) return state.candidates![index]!;
        const intent = state.design!.intents.find((item) => item.pageId === page.id)!;
        return composePage(page, intent, state.design!.plan, relationConstraints, state.canvas!, state.tokens!, repairs);
      });
      state.candidates = selectDeckCandidates(state.outline.pages.map((page) => page.id), nextSets, relationConstraints, state.canvas);
      state.layoutTraces = Object.fromEntries(state.candidates.flat().map((candidate) => [candidate.id, candidate.trace]));
      this.refreshAssetBundle(state); this.compile(state); state.repairCount += 1;
      state.quality = { ...evaluateScene(state.scene!, { measurer: this.textMeasurer, outline: state.outline, ...(state.assetBundle ? { assetPlan: state.assetBundle } : {}) }), repairCount: state.repairCount };
      this.persist(state); this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: state.quality.contentHash });
    } catch (error) { this.fail(job, error); }
    return job;
  }

  async command(id: string, input: SceneCommand) {
    let state = this.get(id); if (!state.scene) throw new AppError("SCENE_NOT_FOUND", "Scene not found", 404);
    if (input.type === "set-asset") {
      const reference = String(input.value ?? "");
      const localMatch = /^data:image\/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$/.exec(reference);
      let safeRemote = false;
      try {
        const url = new URL(reference);
        safeRemote = url.protocol === "https:" && !/^(?:localhost|127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|0\.|169\.254\.|\[?::1\]?)$/i.test(url.hostname);
      } catch { safeRemote = false; }
      if (!safeRemote && !localMatch) throw new AppError("ASSET_REFERENCE_UNSAFE", "Image replacement must be an HTTPS public URL or supported local image", 400);
      const page = state.scene.pages.find((item) => item.id === input.pageId);
      const node = page?.nodes.find((item) => item.id === input.nodeId);
      if (!page || node?.kind !== "image") throw new AppError("NODE_NOT_FOUND", "Image node not found", 404);
      const role = typeof node.content.mediaRole === "string" ? node.content.mediaRole as StoredAsset["role"] : "subject";
      const validated = await this.assetValidator.validate({ ...(localMatch ? { base64: localMatch[1]! } : { url: reference }), role, targetAspectRatio: node.bounds.width / node.bounds.height, incurredCost: false });
      // Validation performs network I/O. Re-read the aggregate afterwards so a
      // concurrent edit can never be overwritten by the stale Scene captured above.
      state = this.get(id);
      if (!state.scene || state.scene.revision !== input.expectedRevision) throw new AppError("REVISION_CONFLICT", "Scene revision conflict", 409);
      const currentPage = state.scene.pages.find((item) => item.id === input.pageId);
      const currentNode = currentPage?.nodes.find((item) => item.id === input.nodeId);
      if (!currentPage || currentNode?.kind !== "image") throw new AppError("NODE_NOT_FOUND", "Image node not found", 404);
      const assetId = this.id("asset");
      state.assets[assetId] = { base64: validated.base64, alt: "", promptHash: hashContent({ source: "user", reference }), identityId: `user-${currentNode.id}`, role, width: validated.width, height: validated.height, qualityStatus: "passed" };
      input = { ...input, value: { url: `/api/v1/presentations/${id}/assets/${assetId}/content`, assetId } };
    }
    const previous = state.scene;
    try { state.scene = applySceneCommand(state.scene, input); }
    catch (error) {
      const code = error instanceof Error ? error.message : "SCENE_COMMAND_FAILED";
      const status = code === "NODE_NOT_FOUND" || code === "PAGE_NOT_FOUND" ? 404 : 409;
      throw new AppError(code, error instanceof Error ? error.message : "Scene command failed", status);
    }
    state.history.push(previous); state.future = []; this.invalidateAfterScene(state); this.persist(state); return state.scene;
  }
  undo(id: string) { const state = this.get(id); const previous = state.history.pop(); if (!previous || !state.scene) return state.scene; state.future.push(state.scene); state.scene = previous; this.invalidateAfterScene(state); this.persist(state); return state.scene; }
  redo(id: string) { const state = this.get(id); const next = state.future.pop(); if (!next || !state.scene) return state.scene; state.history.push(state.scene); state.scene = next; this.invalidateAfterScene(state); this.persist(state); return state.scene; }

  selectCandidate(id: string, pageId: string, candidateId: string, expectedRevision: number) {
    const state = this.get(id); if (!state.scene || state.scene.revision !== expectedRevision) throw new AppError("REVISION_CONFLICT", "Scene revision conflict", 409);
    if (!state.outline || !state.design || !state.candidates || !state.canvas) throw new AppError("COMPOSITION_NOT_FOUND", "Composition is incomplete", 409);
    const pageIndex = state.outline.pages.findIndex((page) => page.id === pageId); const set = state.candidates[pageIndex];
    if (!set?.some((candidate) => candidate.id === candidateId)) throw new AppError("CANDIDATE_NOT_FOUND", "Candidate not found", 404);
    const previous = state.scene;
    const relationConstraints = new RelationConstraintCompiler().compile(state.outline, state.design.plan);
    state.candidates = selectDeckCandidates(state.outline.pages.map((page) => page.id), state.candidates, relationConstraints, state.canvas, { [pageId]: candidateId });
    this.refreshAssetBundle(state); this.compile(state);
    state.history.push(previous); state.future = [];
    this.persist(state); return state.scene;
  }

  /** Re-searches one page without model or image calls, then lets deck-level constraints choose linked pages. */
  redesignPage(id: string, pageId: string, expectedRevision: number) {
    const state = this.get(id);
    if (!state.scene || state.scene.revision !== expectedRevision) throw new AppError("REVISION_CONFLICT", "Scene revision conflict", 409);
    if (!state.outline || !state.design || !state.tokens || !state.canvas || !state.candidates) throw new AppError("COMPOSITION_NOT_FOUND", "Composition is incomplete", 409);
    const pageIndex = state.outline.pages.findIndex((page) => page.id === pageId);
    const page = state.outline.pages[pageIndex];
    const intent = state.design.intents.find((item) => item.pageId === pageId);
    if (!page || !intent) throw new AppError("PAGE_NOT_FOUND", "Page not found", 404);
    const previous = state.scene;
    const relations = new RelationConstraintCompiler().compile(state.outline, state.design.plan);
    const forbiddenGrammarHashes = state.candidates[pageIndex]?.filter((candidate) => candidate.selected).map((candidate) => candidate.grammarHash) ?? [];
    const repair: RepairConstraint = { id: `manual-redesign:${pageId}:${expectedRevision}`, pageId, issueCodes: ["MANUAL_REDESIGN"], forbiddenGrammarHashes };
    const nextSets = state.candidates.map((set, index) => index === pageIndex ? composePage(page, intent, state.design!.plan, relations, state.canvas!, state.tokens!, [repair]) : set);
    state.candidates = selectDeckCandidates(state.outline.pages.map((item) => item.id), nextSets, relations, state.canvas);
    state.layoutTraces = Object.fromEntries(state.candidates.flat().map((candidate) => [candidate.id, candidate.trace]));
    this.refreshAssetBundle(state); this.compile(state);
    state.history.push(previous); state.future = [];
    this.persist(state);
    return state.scene;
  }

  /** Regenerates exactly one visual identity on explicit request; no automatic retry or hidden extra image call occurs. */
  async regenerateAsset(id: string, assetId: string, expectedRevision: number, idempotencyKey: string) {
    let state = this.get(id);
    if (!state.scene || state.scene.revision !== expectedRevision) throw new AppError("REVISION_CONFLICT", "Scene revision conflict", 409);
    const { job, existing } = this.newJob(state, `asset.regenerate:${assetId}`, idempotencyKey);
    if (existing) return job;
    try {
      if (!state.assetBundle || !state.design || !this.image) throw new AppError("ASSET_GENERATION_UNAVAILABLE", "Image generation is unavailable for this project", 409);
      const stored = state.assets[assetId];
      const placement = state.assetBundle.placements.find((item) => item.assetId === assetId);
      const request = placement && state.design.intents.flatMap((intent) => intent.mediaRequests).find((item) => item.identityId === placement.identityId);
      if (!stored || !placement || !request) throw new AppError("ASSET_NOT_FOUND", "Generated asset or placement not found", 404);
      this.update(job, { status: "running", stage: "regenerating_asset", progress: 20 });
      const spec = buildImageRequest({ request, targetAspectRatio: placement.targetAspectRatio, mediaLanguage: state.design.plan.visualGrammar.mediaLanguage });
      const modelInput = { context: { ...spec.context }, size: spec.size };
      const result = await this.image.execute(modelInput);
      this.recordUsage(state, { id: this.id("usage"), provider: "dmx", model: result.model, purpose: "image-regeneration", scopeId: placement.identityId, requestHash: result.requestHash, estimatedCostRmb: result.estimatedCostRmb, success: true, parentJob: job.id });
      const validated = await this.assetValidator.validate({ ...(result.url ? { url: result.url } : {}), ...(result.base64 ? { base64: result.base64 } : {}), role: request.role, targetAspectRatio: placement.targetAspectRatio, incurredCost: true });

      // The paid response is accounted for above, but a concurrent edit still wins.
      // Refusing the stale commit prevents regeneration from erasing user changes.
      state = this.get(id);
      if (!state.scene || state.scene.revision !== expectedRevision || !state.assetBundle) throw new AppError("REVISION_CONFLICT", "Scene changed while the asset was being regenerated", 409, [], { stage: "asset-regeneration", incurredCost: true, manualRetryAllowed: true });
      const replacementId = this.id("asset");
      const replacement: StoredAsset = { base64: validated.base64, alt: request.audienceAlt ?? "", promptHash: result.requestHash, identityId: placement.identityId, role: request.role, width: validated.width, height: validated.height, qualityStatus: "passed" };
      state.assets[replacementId] = replacement;
      for (const item of state.assetBundle.placements) if (item.identityId === placement.identityId) { item.assetId = replacementId; item.source = "generated"; item.promptHash = result.requestHash; }
      state.assetBundle.resolvedAssetIds = [...new Set(state.assetBundle.placements.map((item) => item.assetId).filter((value): value is string => Boolean(value)))];
      this.assetCache.set(result.requestHash, structuredClone(replacement));
      const previous = state.scene;
      this.compile(state); state.history.push(previous); state.future = [];
      this.persist(state); this.update(job, { status: "succeeded", stage: "completed", progress: 100, resultRef: replacementId });
    } catch (error) { this.fail(job, error); }
    return job;
  }

  /** Exports only after rule/visual quality and actual PPTX render evidence pass for the same Scene hash. */
  async export(id: string) {
    const state = this.get(id);
    const capturedHash = this.businessHash(state);
    if (!state.scene || !state.outline) throw new AppError("SCENE_NOT_FOUND", "Scene not found", 404);
    if (!state.quality?.passed || state.quality.upstreamHashes.scene !== state.scene.contentHash || state.quality.visualReviewStatus === "pending" || state.quality.visualReviewStatus === "failed") throw new AppError("QUALITY_GATE_FAILED", "Quality gate has not passed for the current revision", 409);
    const renderable = this.renderableScene(state);
    const artifact = await exportSceneToPptx(renderable);
    const rendered = await this.renderEvidence.create(renderable, artifact.bytes);
    state.renderEvidence = rendered.evidence;
    const refreshedRules = evaluateScene(state.scene, { measurer: this.textMeasurer, outline: state.outline, ...(state.assetBundle ? { assetPlan: state.assetBundle } : {}), renderEvidence: state.renderEvidence });
    const priorVisualIssues = state.quality.issues.filter((issue) => issue.code === "VISUAL_REVIEW" && issue.pageId).map((issue) => ({ pageId: issue.pageId!, dimension: issue.dimension as "Content" | "Design" | "Coherence", severity: issue.severity, message: issue.message, repairIntent: issue.repairIntent ?? "manual-review" }));
    state.quality = applyVisualReview(refreshedRules, priorVisualIssues);
    this.commitSnapshot(state, capturedHash, "export rendering", false);
    if (!state.renderEvidence.passed || !state.quality.passed) throw new AppError("EXPORT_RENDER_DIVERGENCE", "Final PPTX render evidence did not pass", 409, [], { stage: "rendering", presentationId: id, incurredCost: false, manualRetryAllowed: false });
    return artifact;
  }

  usageLedger(id: string) { const jobIds = new Set([...this.jobs.values()].filter((job) => job.scopeId === id).map((job) => job.id)); return this.usage.filter((item) => jobIds.has(item.parentJob)); }
  assetContent(id: string, assetId: string) { const asset = this.get(id).assets[assetId]; if (!asset?.base64) throw new AppError("ASSET_CONTENT_NOT_FOUND", "Asset content not found", 404); return Buffer.from(asset.base64, "base64"); }
}
