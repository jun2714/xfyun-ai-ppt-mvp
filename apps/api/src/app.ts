import cors from "@fastify/cors";
import Fastify from "fastify";
import { createContainer } from "./bootstrap/container.js";
import { AppError } from "./shared/errors/app-error.js";
import type { ImageGenerationRequest, TextGenerationRequest } from "./domain/model-generation/model.types.js";

export function buildApp() {
  const app = Fastify({ logger: false });
  const container = createContainer();
  void app.register(cors, { origin: false });
  app.get("/api/v1/health", async () => ({ status: "ok", generationEnabled: container.config.dmxApiKey.length > 0 }));

  if (process.env.NODE_ENV !== "production") {
    app.post("/api/v1/models/text/generate", async (request) => container.generateText.execute(request.body as TextGenerationRequest));
    app.post("/api/v1/models/image/generate", async (request) => container.generateImage.execute(request.body as ImageGenerationRequest));
  }

  app.setErrorHandler((error, request, reply) => {
    if (error instanceof AppError) return reply.status(error.statusCode).send({ error: { code: error.code, message: error.message, details: error.details }, meta: { requestId: request.id } });
    app.log.error(error);
    return reply.status(500).send({ error: { code: "INTERNAL_ERROR", message: "Unexpected server error", details: [] }, meta: { requestId: request.id } });
  });
  return app;
}
