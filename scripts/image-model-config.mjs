export const DEFAULT_DMX_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-lite-image";

const STALE_DMX_GEMINI_IMAGE_MODELS = new Set([
  "gemini-3.1-flash-image",
]);

export const resolveGeminiImageModel = (source = {}) => {
  const providerSpecific = String(source.GEMINI_IMAGE_MODEL || "").trim();
  if (providerSpecific) return providerSpecific;

  const sharedModel = String(source.DMX_IMAGE_MODEL || "").trim();
  if (!sharedModel || STALE_DMX_GEMINI_IMAGE_MODELS.has(sharedModel)) {
    return DEFAULT_DMX_GEMINI_IMAGE_MODEL;
  }
  return sharedModel;
};
