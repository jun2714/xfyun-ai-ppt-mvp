import { AppError } from "../../shared/errors/app-error.js";

/** Executes exactly one provider request; retry belongs to no layer because paid calls must never repeat automatically. */
export class JsonHttpClient {
  constructor() {}

  async post<T>(url: string, headers: Record<string, string>, body: unknown): Promise<T> {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(body)
      });
      const raw = await response.text();
      let parsed: unknown;
      try {
        parsed = raw ? JSON.parse(raw) : {};
      } catch {
        throw new AppError("PROVIDER_INVALID_RESPONSE", "DMX returned non-JSON data", 502);
      }
      if (!response.ok) {
        const providerMessage = this.readProviderMessage(parsed);
        throw new AppError("PROVIDER_ERROR", `DMX request failed (${response.status}): ${providerMessage}`, 502);
      }
      return parsed as T;
    } catch (error) {
      if (error instanceof AppError) throw error;
      throw new AppError("PROVIDER_UNAVAILABLE", "Unable to reach DMX", 502);
    }
  }

  private readProviderMessage(value: unknown): string {
    if (typeof value !== "object" || value === null) return "Unknown provider error";
    const error = (value as { error?: unknown }).error;
    if (typeof error === "string") return error;
    if (typeof error === "object" && error !== null && "message" in error) {
      return String((error as { message: unknown }).message);
    }
    return "Unknown provider error";
  }
}
