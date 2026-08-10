import { z } from "zod";
import type { VisualReviewCommand, VisualReviewPort, VisualReviewResult } from "../../application/ports/visual-review.port.js";
import { AppError } from "../../shared/errors/app-error.js";
import { JsonHttpClient } from "../http/json-http-client.js";
import { DmxAuth } from "./dmx-auth.js";

const OutputSchema = z.object({ issues: z.array(z.object({
  pageId: z.string().min(1), dimension: z.enum(["Content", "Design", "Coherence"]), severity: z.enum(["warning", "error"]),
  message: z.string().min(1), repairIntent: z.string().min(1)
})) });
type DmxResponse = { model?: string; choices?: Array<{ message?: { content?: string } }>; usage?: { prompt_tokens?: number; completion_tokens?: number } };

/** Sends one multimodal DMX request and validates returned page references. */
export class DmxVisualReviewAdapter implements VisualReviewPort {
  constructor(private readonly http: JsonHttpClient, private readonly auth: DmxAuth, private readonly baseUrl: string, private readonly model: string) {}
  async review(command: VisualReviewCommand): Promise<VisualReviewResult> {
    const response = await this.http.post<DmxResponse>(`${this.baseUrl}/chat/completions`, this.auth.headers(), {
      model: this.model, stream: false, temperature: 0.1, max_tokens: command.maxOutputTokens, response_format: { type: "json_object" },
      messages: [{ role: "system", content: command.systemPrompt }, {
        role: "user", content: [
          { type: "text", text: command.contextJson },
          { type: "image_url", image_url: { url: command.contactSheetDataUri } }
        ]
      }]
    });
    const content = response.choices?.[0]?.message?.content;
    if (!content) throw new AppError("PROVIDER_EMPTY_RESPONSE", "DMX visual model returned no content", 502);
    let parsed: unknown;
    try { parsed = JSON.parse(content); } catch { throw new AppError("MODEL_JSON_INVALID", "Visual review did not return valid JSON", 502); }
    const output = OutputSchema.parse(parsed);
    if (output.issues.some((issue) => !command.pageIds.includes(issue.pageId))) throw new AppError("VISUAL_REVIEW_REFERENCE_INVALID", "Visual review referenced an unknown page", 422);
    return { model: response.model ?? this.model, inputTokens: response.usage?.prompt_tokens ?? 0, outputTokens: response.usage?.completion_tokens ?? 0, issues: output.issues };
  }
}
