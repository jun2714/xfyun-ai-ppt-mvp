import cors from "@fastify/cors";
import Fastify from "fastify";
import { z } from "zod";
import { PresentationBriefSchema } from "@sparkdeck/presentation-model";
import { createContainer } from "./bootstrap/container.js";
import { AppError } from "./shared/errors/app-error.js";
import type { ImageGenerationRequest, TextGenerationRequest } from "./domain/model-generation/model.types.js";

const Id = z.object({ id: z.string().min(1) });
const PageId = z.object({ id: z.string().min(1), pageId: z.string().min(1) });
const AssetId = z.object({ id: z.string().min(1), assetId: z.string().min(1) });
const JobRequest = z.object({ idempotencyKey: z.string().min(1) });
const Expected = JobRequest.extend({ expectedRevision: z.number().int().nonnegative() });
const BriefInput = PresentationBriefSchema.omit({ id: true, schemaVersion: true, revision: true, contentHash: true, upstreamHashes: true });
const Command = Expected.extend({
  type: z.enum(["set-text", "set-style", "set-bounds", "set-z", "set-rotation", "set-asset", "set-crop", "set-locked", "duplicate-node", "add-text", "add-shape", "add-image", "delete-node", "add-page", "duplicate-page", "delete-page", "reorder-page", "align-nodes", "distribute-nodes", "set-theme"]),
  pageId: z.string(),
  nodeId: z.string(),
  value: z.unknown()
});
const success = <T>(data: T, requestId: string) => ({ data, meta: { requestId } });

/** Creates the HTTP interface; routes translate requests but never make layout decisions. */
export function buildApp() {
  const app = Fastify({ logger: false, bodyLimit: 18 * 1024 * 1024 });
  const container = createContainer();
  void app.register(cors, { origin: false });

  app.get("/api/v1/health", async () => ({ status: "ok", generationEnabled: container.config.dmxApiKey.length > 0, schemaVersion: "008.0" }));
  app.post("/api/v1/presentations", async (request, reply) => reply.status(201).send(success(container.platform.create(BriefInput.parse(request.body)), request.id)));
  app.get("/api/v1/presentations", async (request) => success(container.platform.list(), request.id));
  app.get("/api/v1/presentations/:id", async (request) => {
    const state = container.platform.get(Id.parse(request.params).id);
    return success({ brief: state.brief, outline: state.outline, design: state.design, assetBundle: state.assetBundle, scene: state.scene, quality: state.quality, renderEvidence: state.renderEvidence }, request.id);
  });

  const startNarrative = async (request: any, reply: any) => {
    const body = JobRequest.parse(request.body);
    return reply.status(202).send(success(container.platform.startOutline(Id.parse(request.params).id, body.idempotencyKey), request.id));
  };
  app.post("/api/v1/presentations/:id/narrative-jobs", startNarrative);
  app.post("/api/v1/presentations/:id/outline-jobs", startNarrative);
  app.get("/api/v1/presentations/:id/outline", async (request) => success(container.platform.get(Id.parse(request.params).id).outline, request.id));
  app.put("/api/v1/presentations/:id/outline", async (request) => {
    const id = Id.parse(request.params).id;
    const body = z.object({ expectedRevision: z.number().int().nonnegative(), idempotencyKey: z.string(), outline: z.unknown() }).parse(request.body);
    return success(container.platform.saveOutline(id, body.outline, body.expectedRevision), request.id);
  });
  app.post("/api/v1/presentations/:id/outline/confirm", async (request) => {
    const id = Id.parse(request.params).id; const body = Expected.parse(request.body);
    return success(container.platform.confirmOutline(id, body.expectedRevision), request.id);
  });
  app.post("/api/v1/presentations/:id/design-jobs", async (request, reply) => {
    const body = JobRequest.parse(request.body);
    return reply.status(202).send(success(container.platform.startDesign(Id.parse(request.params).id, body.idempotencyKey), request.id));
  });
  app.get("/api/v1/presentations/:id/design", async (request) => success(container.platform.get(Id.parse(request.params).id).design, request.id));
  app.post("/api/v1/presentations/:id/composition-jobs", async (request, reply) => {
    const id = Id.parse(request.params).id;
    const body = JobRequest.extend({ canvas: z.object({ width: z.number().positive(), height: z.number().positive() }).optional() }).parse(request.body);
    return reply.status(202).send(success(container.platform.compose(id, body.canvas, body.idempotencyKey), request.id));
  });
  app.get("/api/v1/presentations/:id/compositions", async (request) => success(container.platform.get(Id.parse(request.params).id).candidates, request.id));
  app.post("/api/v1/presentations/:id/asset-jobs", async (request, reply) => {
    const body = JobRequest.parse(request.body);
    return reply.status(202).send(success(await container.platform.resolveAssets(Id.parse(request.params).id, body.idempotencyKey), request.id));
  });
  app.get("/api/v1/presentations/:id/assets", async (request) => {
    const state = container.platform.get(Id.parse(request.params).id);
    const assets = Object.fromEntries(Object.entries(state.assets).map(([assetId, asset]) => [assetId, { alt: asset.alt, promptHash: asset.promptHash, identityId: asset.identityId, role: asset.role, width: asset.width, height: asset.height, qualityStatus: asset.qualityStatus }]));
    return success({ bundle: state.assetBundle, assets }, request.id);
  });
  app.get("/api/v1/presentations/:id/assets/:assetId/content", async (request, reply) => {
    const params = AssetId.parse(request.params);
    return reply.header("content-type", "image/png").header("cache-control", "private, max-age=31536000, immutable").send(container.platform.assetContent(params.id, params.assetId));
  });
  app.post("/api/v1/presentations/:id/quality-jobs", async (request, reply) => {
    const body = JobRequest.parse(request.body);
    return reply.status(202).send(success(await container.platform.quality(Id.parse(request.params).id, body.idempotencyKey), request.id));
  });
  app.post("/api/v1/presentations/:id/repair-jobs", async (request, reply) => {
    const body = JobRequest.parse(request.body);
    return reply.status(202).send(success(container.platform.repair(Id.parse(request.params).id, body.idempotencyKey), request.id));
  });
  app.get("/api/v1/presentations/:id/scene", async (request) => success(container.platform.get(Id.parse(request.params).id).scene, request.id));
  app.post("/api/v1/presentations/:id/commands", async (request) => {
    const id = Id.parse(request.params).id; const body = Command.parse(request.body);
    return success(await container.platform.command(id, body), request.id);
  });
  app.post("/api/v1/presentations/:id/undo", async (request) => success(container.platform.undo(Id.parse(request.params).id), request.id));
  app.post("/api/v1/presentations/:id/redo", async (request) => success(container.platform.redo(Id.parse(request.params).id), request.id));
  app.post("/api/v1/presentations/:id/pages/:pageId/select-composition", async (request) => {
    const params = PageId.parse(request.params); const body = Expected.extend({ candidateId: z.string() }).parse(request.body);
    return success(container.platform.selectCandidate(params.id, params.pageId, body.candidateId, body.expectedRevision), request.id);
  });
  app.post("/api/v1/presentations/:id/pages/:pageId/redesign", async (request) => {
    const params = PageId.parse(request.params); const body = Expected.parse(request.body);
    return success(container.platform.redesignPage(params.id, params.pageId, body.expectedRevision), request.id);
  });
  app.post("/api/v1/presentations/:id/assets/:assetId/regeneration-jobs", async (request, reply) => {
    const params = AssetId.parse(request.params); const body = Expected.parse(request.body);
    return reply.status(202).send(success(await container.platform.regenerateAsset(params.id, params.assetId, body.expectedRevision, body.idempotencyKey), request.id));
  });
  app.post("/api/v1/presentations/:id/exports", async (request, reply) => {
    const id = Id.parse(request.params).id; const body = Expected.parse(request.body); const state = container.platform.get(id);
    if (state.scene?.revision !== body.expectedRevision) throw new AppError("REVISION_CONFLICT", "Scene revision conflict", 409);
    const artifact = await container.platform.export(id);
    return reply.header("content-type", "application/vnd.openxmlformats-officedocument.presentationml.presentation").header("x-scene-fingerprint", artifact.semanticFingerprint).send(Buffer.from(artifact.bytes));
  });
  app.get("/api/v1/jobs/:id", async (request) => success(container.platform.getJob(Id.parse(request.params).id), request.id));

  // Debug evidence is deliberately unavailable in production until an administrator auth adapter exists.
  if (process.env.NODE_ENV !== "production") {
    app.get("/api/v1/presentations/:id/layout-traces", async (request) => success(container.platform.get(Id.parse(request.params).id).layoutTraces, request.id));
    app.get("/api/v1/presentations/:id/asset-traces", async (request) => success(container.platform.get(Id.parse(request.params).id).assetTraces, request.id));
    app.get("/api/v1/presentations/:id/quality-evidence", async (request) => { const state = container.platform.get(Id.parse(request.params).id); return success({ quality: state.quality, visualReview: state.visualReview, renderEvidence: state.renderEvidence }, request.id); });
    app.get("/api/v1/presentations/:id/usage", async (request) => { const id = Id.parse(request.params).id; return success(container.platform.usageLedger(id), request.id); });
    app.post("/api/v1/models/text/generate", async (request) => container.generateText.execute(request.body as TextGenerationRequest));
    app.post("/api/v1/models/image/generate", async (request) => container.generateImage.execute(request.body as ImageGenerationRequest));
  }

  app.setErrorHandler((error, request, reply) => {
    if (error instanceof AppError) return reply.status(error.statusCode).send({ error: { code: error.code, message: error.message, stage: error.context.stage, presentationId: error.context.presentationId, pageId: error.context.pageId, nodeIds: error.context.nodeIds ?? [], incurredCost: error.context.incurredCost ?? false, manualRetryAllowed: error.context.manualRetryAllowed ?? false, details: error.details }, meta: { requestId: request.id } });
    if (error instanceof z.ZodError) return reply.status(400).send({ error: { code: "VALIDATION_ERROR", message: "Invalid request", incurredCost: false, manualRetryAllowed: false, details: error.issues }, meta: { requestId: request.id } });
    app.log.error(error);
    return reply.status(500).send({ error: { code: "INTERNAL_ERROR", message: "Unexpected server error", incurredCost: false, manualRetryAllowed: false, details: [] }, meta: { requestId: request.id } });
  });
  return app;
}
