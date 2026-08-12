const SELECTED_TEMPLATE_STORAGE_KEY = "teachnova.selectedTemplateId";

export function readPreferredTemplateId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.sessionStorage.getItem(SELECTED_TEMPLATE_STORAGE_KEY);
    return value?.trim() || null;
  } catch {
    return null;
  }
}

export function writePreferredTemplateId(templateId: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (!templateId) {
      window.sessionStorage.removeItem(SELECTED_TEMPLATE_STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(SELECTED_TEMPLATE_STORAGE_KEY, templateId);
  } catch {
    // ignore storage failures
  }
}
