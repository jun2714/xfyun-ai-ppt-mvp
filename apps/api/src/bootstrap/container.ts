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
import { ReviewVisualQualityUseCase } from "../application/use-cases/review-visual-quality.use-case.js";
import { DmxVisualReviewAdapter } from "../infrastructure/dmx/dmx-visual-review.adapter.js";
import { SvgContactSheetAdapter } from "../infrastructure/rendering/svg-contact-sheet.adapter.js";
import { MemoryPresentationStateRepository } from "../infrastructure/persistence/memory/memory-presentation-state-repository.js";

export function createContainer() {
  const config = loadConfig();
  const http = new JsonHttpClient(config.requestTimeoutMs);
  const auth = new DmxAuth(config.dmxApiKey);
  const costPolicy = new ModelCostPolicy(config);
  const generateText=new GenerateTextUseCase(new DmxTextModelAdapter(http, auth, config.dmxApiBaseUrl, config.textModel), costPolicy, config.textMaxOutputTokens);
  const generateImage=new GenerateImageUseCase(new DmxImageModelAdapter(http, auth, config.dmxApiBaseUrl, config.imageModel), costPolicy);
  const reviewVisualQuality=new ReviewVisualQualityUseCase(new SvgContactSheetAdapter(),new DmxVisualReviewAdapter(http,auth,config.dmxApiBaseUrl,config.visionModel),costPolicy,1200);
  return {
    config,
    generateText,
    generateImage,
    platform:new PresentationPlatformService(new MemoryPresentationStateRepository(),new NarrativePlanner(generateText),new DesignPlanner(generateText),config.dmxApiKey?generateImage:undefined,config.dmxApiKey?reviewVisualQuality:undefined)
  };
}
