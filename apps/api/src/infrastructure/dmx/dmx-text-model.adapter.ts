import type { TextModelCommand, TextModelPort } from "../../application/ports/text-model.port.js";
import type { TextModelResult } from "../../domain/model-generation/model.types.js";
import { AppError } from "../../shared/errors/app-error.js";
import { JsonHttpClient } from "../http/json-http-client.js";
import { DmxAuth } from "./dmx-auth.js";

interface DmxChatResponse {
  model?: string;
  choices?: Array<{ message?: { content?: string } }>;
  usage?: { prompt_tokens?: number; completion_tokens?: number };
}

/** Maps the text Port to one DMX chat-completions request. */
export class DmxTextModelAdapter implements TextModelPort {
  constructor(
    private readonly http: JsonHttpClient,
    private readonly auth: DmxAuth,
    private readonly baseUrl: string,
    private readonly model: string
  ) {}

  async generate(command: TextModelCommand): Promise<TextModelResult> {
    const response = await this.http.post<DmxChatResponse>(
      `${this.baseUrl}/chat/completions`,
      this.auth.headers(),
      {
        model: this.model,
        messages: [
          { role: "system", content: command.systemPrompt },
          { role: "user", content: command.userPrompt }
        ],
        stream: false,
        temperature: command.temperature,
        ...(command.maxOutputTokens === undefined ? {} : { max_tokens: command.maxOutputTokens }),
        ...(command.responseFormat === "json_object"
          ? { response_format: { type: "json_object" } }
          : {})
      }
    );
    const content = response.choices?.[0]?.message?.content;
    if (!content) throw new AppError("PROVIDER_EMPTY_RESPONSE", "DMX text model returned no content", 502);
    return {
      content,
      model: response.model ?? this.model,
      usage: {
        inputTokens: response.usage?.prompt_tokens ?? 0,
        outputTokens: response.usage?.completion_tokens ?? 0
      }
    };
  }
}
