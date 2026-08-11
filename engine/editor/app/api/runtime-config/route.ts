import { NextResponse } from "next/server";
import { authStatusForRequest } from "@/lib/server-auth-role";
import { readUserConfigFile } from "@/lib/user-config-store";
import { hasValidLLMConfig, normalizeLLMConfig } from "@/utils/storeHelpers";
import { LLMConfig } from "@/types/llm_config";

export const dynamic = "force-dynamic";

const SECRET_FIELD = /(API_KEY|ACCESS_KEY|SECRET|TOKEN|PASSWORD)/i;

function runtimeConfigFromEnv(): LLMConfig {
  return normalizeLLMConfig({
    LLM: process.env.LLM,
    CUSTOM_LLM_URL: process.env.CUSTOM_LLM_URL,
    CUSTOM_LLM_API_KEY: process.env.CUSTOM_LLM_API_KEY,
    CUSTOM_MODEL: process.env.CUSTOM_MODEL,
    IMAGE_PROVIDER: process.env.IMAGE_PROVIDER,
    GOOGLE_API_KEY: process.env.GOOGLE_API_KEY,
    OPENAI_COMPAT_IMAGE_BASE_URL: process.env.OPENAI_COMPAT_IMAGE_BASE_URL,
    OPENAI_COMPAT_IMAGE_API_KEY: process.env.OPENAI_COMPAT_IMAGE_API_KEY,
    OPENAI_COMPAT_IMAGE_MODEL: process.env.OPENAI_COMPAT_IMAGE_MODEL,
    DISABLE_IMAGE_GENERATION:
      process.env.DISABLE_IMAGE_GENERATION?.toLowerCase() === "true",
  });
}

export async function GET(request: Request) {
  const auth = await authStatusForRequest(request);
  if (!auth.authenticated) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
  try {
    const path = process.env.USER_CONFIG_PATH;
    // In Teachnova the server-side .env is authoritative. A user config file
    // may override non-empty values, but its absence must not make the editor
    // claim that models are unconfigured.
    const envConfig = runtimeConfigFromEnv();
    const full = normalizeLLMConfig(
      path
        ? { ...envConfig, ...(readUserConfigFile<LLMConfig>(path) || {}) }
        : envConfig
    );
    const config = Object.fromEntries(
      Object.entries(full).map(([key, value]) => [
        key,
        SECRET_FIELD.test(key) ? (value ? "__configured__" : "") : value,
      ])
    );
    return NextResponse.json({
      configured: hasValidLLMConfig(full),
      config,
    });
  } catch {
    return NextResponse.json(
      { configured: false, config: {} },
      { status: 200 }
    );
  }
}
