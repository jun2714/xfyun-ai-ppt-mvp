import { GenerateImageUseCase } from "../application/use-cases/generate-image.use-case.js";
import { GenerateTextUseCase } from "../application/use-cases/generate-text.use-case.js";
import { ModelCostPolicy } from "../domain/budget/model-cost-policy.js";
import { loadConfig } from "../infrastructure/config/env.js";
import { DmxAuth } from "../infrastructure/dmx/dmx-auth.js";
import { DmxImageModelAdapter } from "../infrastructure/dmx/dmx-image-model.adapter.js";
import { DmxTextModelAdapter } from "../infrastructure/dmx/dmx-text-model.adapter.js";
import { JsonHttpClient } from "../infrastructure/http/json-http-client.js";

export function createContainer() {
  const config = loadConfig();
  const http = new JsonHttpClient(config.requestTimeoutMs);
  const auth = new DmxAuth(config.dmxApiKey);
  const costPolicy = new ModelCostPolicy(config);
  return {
    config,
    generateText: new GenerateTextUseCase(new DmxTextModelAdapter(http, auth, config.dmxApiBaseUrl, config.textModel), costPolicy, config.textMaxOutputTokens),
    generateImage: new GenerateImageUseCase(new DmxImageModelAdapter(http, auth, config.dmxApiBaseUrl, config.imageModel), costPolicy)
  };
}
