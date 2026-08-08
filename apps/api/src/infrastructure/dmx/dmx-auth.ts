import { AppError } from "../../shared/errors/app-error.js";

export class DmxAuth {
  constructor(private readonly apiKey: string) {}

  headers(): Record<string, string> {
    if (!this.apiKey) {
      throw new AppError("MODEL_NOT_CONFIGURED", "DMX_API_KEY is not configured", 503);
    }
    return { Authorization: `Bearer ${this.apiKey}` };
  }
}
