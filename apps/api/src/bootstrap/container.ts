import { GenerateImageUseCase } from "../application/use-cases/generate-image.use-case.js";
import { GenerateTextUseCase } from "../application/use-cases/generate-text.use-case.js";
import { ModelCostPolicy } from "../domain/budget/model-cost-policy.js";
import { loadConfig } from "../infrastructure/config/env.js";
import { DmxAuth } from "../infrastructure/dmx/dmx-auth.js";
import { DmxImageModelAdapter } from "../infrastructure/dmx/dmx-image-model.adapter.js";
import { DmxTextModelAdapter } from "../infrastructure/dmx/dmx-text-model.adapter.js";
import { JsonHttpClient } from "../infrastructure/http/json-http-client.js";
import { DesignPlanner, NarrativePlanner } from "../application/services/planning.service.js";
import { PresentationPlatformService } from "../application/services/presentation-platform.service.js";

export function createContainer() {
  const config = loadConfig();
  const http = new JsonHttpClient(config.requestTimeoutMs);
  const auth = new DmxAuth(config.dmxApiKey);
  const costPolicy = new ModelCostPolicy(config);
  const generateText=new GenerateTextUseCase(new DmxTextModelAdapter(http, auth, config.dmxApiBaseUrl, config.textModel), costPolicy, config.textMaxOutputTokens);
  const generateImage=new GenerateImageUseCase(new DmxImageModelAdapter(http, auth, config.dmxApiBaseUrl, config.imageModel), costPolicy);
  return {
    config,
    generateText,
    generateImage,
    platform:new PresentationPlatformService(new NarrativePlanner(generateText),new DesignPlanner(generateText),config.dmxApiKey?generateImage:undefined)
  };
}
