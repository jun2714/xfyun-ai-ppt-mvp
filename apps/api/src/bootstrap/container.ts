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
import { FilePresentationStateRepository } from "../infrastructure/persistence/file/file-presentation-state-repository.js";
import { FilePromptCatalogAdapter } from "../infrastructure/prompts/file-prompt-catalog.adapter.js";
import { OfficeRenderEvidenceAdapter } from "../infrastructure/rendering/office-render-evidence.adapter.js";
import { SharpAssetValidationAdapter } from "../infrastructure/assets/sharp-asset-validation.adapter.js";
import { FontkitTextMeasurerAdapter } from "../infrastructure/typography/fontkit-text-measurer.adapter.js";

export function createContainer() {
  const config = loadConfig();
  const http = new JsonHttpClient();
  const auth = new DmxAuth(config.dmxApiKey);
  const costPolicy = new ModelCostPolicy(config);
  const prompts = new FilePromptCatalogAdapter(config.promptDirectory);
  const generateText=new GenerateTextUseCase(new DmxTextModelAdapter(http, auth, config.dmxApiBaseUrl, config.textModel), costPolicy);
  const generateImage=new GenerateImageUseCase(new DmxImageModelAdapter(http, auth, config.dmxApiBaseUrl, config.imageModel, config.imageApiStyle), prompts, costPolicy);
  const reviewVisualQuality=new ReviewVisualQualityUseCase(new SvgContactSheetAdapter(),new DmxVisualReviewAdapter(http,auth,config.dmxApiBaseUrl,config.visionModel),prompts,costPolicy);
  const renderEvidence = new OfficeRenderEvidenceAdapter(config.officeRenderProgramId);
  return {
    config,
    generateText,
    generateImage,
    platform:new PresentationPlatformService(new FilePresentationStateRepository(config.dataDirectory),new NarrativePlanner(generateText,prompts),new DesignPlanner(generateText,prompts),renderEvidence,new SharpAssetValidationAdapter(),new FontkitTextMeasurerAdapter(),config.dmxApiKey?generateImage:undefined,config.dmxApiKey?reviewVisualQuality:undefined)
  };
}
