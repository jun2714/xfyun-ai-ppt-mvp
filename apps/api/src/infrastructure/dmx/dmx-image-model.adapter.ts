import type { ImageModelCommand, ImageModelPort } from "../../application/ports/image-model.port.js";
import type { ImageModelResult } from "../../domain/model-generation/model.types.js";
import { AppError } from "../../shared/errors/app-error.js";
import { JsonHttpClient } from "../http/json-http-client.js";
import { DmxAuth } from "./dmx-auth.js";

interface DmxImageResponse {
  data?: Array<{ url?: string; b64_json?: string }>;
  output?: Array<{ type?: string; content?: Array<{ type?: string; text?: string }> }>;
}

/** Translates the configured DMX image protocol without inferring behavior from model names. */
export class DmxImageModelAdapter implements ImageModelPort {
  constructor(
    private readonly http: JsonHttpClient,
    private readonly auth: DmxAuth,
    private readonly baseUrl: string,
    private readonly model: string,
    private readonly apiStyle: "responses" | "images"
  ) {}

  async generate(command: ImageModelCommand): Promise<ImageModelResult> {
    const usesResponsesApi = this.apiStyle === "responses";
    const response = await this.http.post<DmxImageResponse>(
      `${this.baseUrl}/${usesResponsesApi ? "responses" : "images/generations"}`,
      this.auth.headers(),
      usesResponsesApi
        ? {
            model: this.model,
            input: {
              messages: [{ role: "user", content: [{ text: command.prompt }] }],
              parameters: {
                size: command.size.replace("x", "*"),
                n: 1,
                prompt_extend: true,
                watermark: false
              }
            }
          }
        : {
            model: this.model,
            prompt: command.prompt,
            size: command.size.replace("x", "*"),
            n: 1,
            response_format: "url"
          }
    );
    const image = response.data?.[0];
    const responseUrl = response.output
      ?.flatMap((item) => item.content ?? [])
      .find((item) => item.type === "image" && item.text)?.text;
    const url = image?.url ?? responseUrl;
    if (!url && !image?.b64_json) throw new AppError("PROVIDER_EMPTY_RESPONSE", "DMX image model returned no image", 502);
    return {
      model: this.model,
      ...(url ? { url } : {}),
      ...(image?.b64_json ? { base64: image.b64_json } : {})
    };
  }
}
