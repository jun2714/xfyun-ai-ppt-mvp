import { v4 as uuidv4 } from "uuid";
import { extractTemplateV2Layouts } from "@/components/slide-editor/importing/template-v2-import";
import { getApiUrl } from "@/utils/api";
import { pickUuid } from "@/utils/uuid";
import { ApiResponseHandler } from "./api-error-handler";
import { getHeader } from "./header";
import { PresentationGenerationApi } from "./presentation-generation";
import TemplateService, {
  type TemplateDetailsResponse,
} from "./template";

const EDIT_COPY_MARK = "编辑副本";
const LINK_STORAGE_KEY = "teachnova.library-edit-copy";

type LinkedPresentations = Record<string, string>;

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function readLinkedPresentations(): LinkedPresentations {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(LINK_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function rememberLinkedPresentation(templateId: string, presentationId: string) {
  if (typeof window === "undefined" || !templateId || !presentationId) return;
  const next = readLinkedPresentations();
  next[templateId] = presentationId;
  try {
    window.localStorage.setItem(LINK_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // ignore quota / private mode
  }
}

export function linkedPresentationId(templateId: string): string {
  return pickUuid(readLinkedPresentations()[templateId]);
}

export function isLibraryEditCopyName(name?: string | null): boolean {
  return Boolean(name && name.includes(EDIT_COPY_MARK));
}

export function cleanEditCopyTitle(name?: string | null): string {
  const text = String(name || "")
    .replace(/[（(]\s*编辑副本\s*[）)]/g, "")
    .trim();
  return text || String(name || "").trim() || "未命名课件";
}

export function layoutsFromTemplate(template: {
  layouts?: unknown;
  raw_layouts?: unknown;
}): ReturnType<typeof extractTemplateV2Layouts> {
  const layouts = extractTemplateV2Layouts(template.layouts);
  if (layouts.length) return layouts;
  return extractTemplateV2Layouts(template.raw_layouts);
}

function slidesFromLayouts(
  presentationId: string,
  layouts: Array<Record<string, unknown>>,
) {
  return layouts.map((layout, index) => ({
    id: uuidv4(),
    presentation: presentationId,
    layout_group: presentationId,
    layout: String(layout.id || `layout_${index + 1}`),
    index,
    content: {},
    speaker_note: "",
    ui: cloneJson(layout),
  }));
}

async function updatePresentationSlides(
  presentationId: string,
  title: string,
  layouts: Array<Record<string, unknown>>,
) {
  await PresentationGenerationApi.updatePresentationContent({
    id: presentationId,
    title,
    n_slides: layouts.length,
    slides: slidesFromLayouts(presentationId, layouts),
  });
}

async function createPresentationViaBlank(
  title: string,
  layouts: Array<Record<string, unknown>>,
): Promise<{ presentation_id: string; title: string }> {
  const blank = await PresentationGenerationApi.createBlankPresentation();
  const presentationId = pickUuid(blank.id);
  if (!presentationId) {
    throw new Error("未返回可编辑项目");
  }
  await updatePresentationSlides(presentationId, title, layouts);
  return { presentation_id: presentationId, title };
}

async function convertTemplateViaApi(
  templateId: string,
  payload: {
    title?: string;
    deleteTemplate?: boolean;
    layouts?: unknown;
  },
): Promise<{ presentation_id: string; title: string }> {
  const apiTemplateId = templateId.replace(/^template-v2-/, "");
  const response = await fetch(
    getApiUrl(
      `/api/v1/ppt/template/${encodeURIComponent(apiTemplateId)}/to-presentation`,
    ),
    {
      method: "POST",
      headers: getHeader(),
      body: JSON.stringify({
        title: payload.title,
        delete_template: payload.deleteTemplate !== false,
        layouts: payload.layouts,
      }),
    },
  );
  if (response.status === 404 || response.status === 405) {
    throw new Error("CONVERT_ENDPOINT_MISSING");
  }
  const data = await ApiResponseHandler.handleResponse(
    response,
    "创建可编辑项目失败",
  );
  const presentationId = pickUuid(
    data?.presentation_id,
    data?.presentationId,
    data?.id,
  );
  if (!presentationId) {
    throw new Error("未返回可编辑项目");
  }
  return {
    presentation_id: presentationId,
    title: data?.title || payload.title || "未命名课件",
  };
}

export async function upsertPresentationFromLayouts(options: {
  templateId?: string;
  presentationId?: string;
  title: string;
  layouts: unknown[];
  deleteTemplate?: boolean;
}): Promise<{ presentation_id: string; title: string }> {
  const title = cleanEditCopyTitle(options.title);
  const layouts = options.layouts.filter(
    (layout): layout is Record<string, unknown> =>
      Boolean(layout) && typeof layout === "object" && !Array.isArray(layout),
  );
  if (!layouts.length) {
    throw new Error("课件没有可编辑的页面");
  }

  const templateId = options.templateId || "";
  const existingId =
    pickUuid(options.presentationId) || linkedPresentationId(templateId);

  if (existingId) {
    try {
      await updatePresentationSlides(existingId, title, layouts);
      if (templateId) rememberLinkedPresentation(templateId, existingId);
      return { presentation_id: existingId, title };
    } catch {
      // The linked project may have been deleted. Create a new one below.
    }
  }

  if (templateId) {
    try {
      const converted = await convertTemplateViaApi(templateId, {
        title,
        deleteTemplate: options.deleteTemplate !== false,
        layouts,
      });
      rememberLinkedPresentation(templateId, converted.presentation_id);
      return converted;
    } catch (error) {
      if (!(error instanceof Error) || error.message !== "CONVERT_ENDPOINT_MISSING") {
        // Keep going: older APIs can still materialize through blank + update.
      }
    }
  }

  const created = await createPresentationViaBlank(title, layouts);
  if (templateId) rememberLinkedPresentation(templateId, created.presentation_id);
  if (options.deleteTemplate !== false && templateId) {
    try {
      await TemplateService.deleteTemplate(templateId);
    } catch {
      // Leftover copy in 模板中心 is non-fatal.
    }
  }
  return created;
}

export async function materializeTemplateAsPresentation(
  templateId: string,
  title?: string,
): Promise<{ presentation_id: string; title: string }> {
  const linked = linkedPresentationId(templateId);
  if (linked) {
    try {
      await TemplateService.deleteTemplate(templateId);
    } catch {
      // Already converted; ignore missing template.
    }
    return { presentation_id: linked, title: cleanEditCopyTitle(title) };
  }

  const template = await TemplateService.getTemplateDetails(templateId);
  const layouts = layoutsFromTemplate(template);
  return upsertPresentationFromLayouts({
    templateId: template.id || templateId,
    title: title || template.name || "未命名课件",
    layouts,
    deleteTemplate: true,
  });
}

let migrateInFlight: Promise<number> | null = null;

export async function migrateLibraryEditCopyTemplates(): Promise<number> {
  if (migrateInFlight) return migrateInFlight;
  migrateInFlight = (async () => {
    const summaries = await TemplateService.getTemplateSummaries(false);
    const copies = (summaries.items || []).filter(
      (item) => !item.is_default && isLibraryEditCopyName(item.name),
    );
    if (!copies.length) return 0;

    const { DashboardApi } = await import("./dashboard");
    const existing = await DashboardApi.getPresentations("v2-standard");
    const existingTitles = new Set(
      existing.map((item) => cleanEditCopyTitle(item.title)),
    );

    let converted = 0;
    for (const item of copies) {
      const title = cleanEditCopyTitle(item.name);
      try {
        if (existingTitles.has(title) || linkedPresentationId(item.id)) {
          await TemplateService.deleteTemplate(item.id);
          continue;
        }
        await materializeTemplateAsPresentation(item.id, item.name);
        existingTitles.add(title);
        converted += 1;
      } catch (error) {
        console.error("failed to migrate edit-copy template", item.id, error);
      }
    }
    return converted;
  })().finally(() => {
    migrateInFlight = null;
  });
  return migrateInFlight;
}

export async function dedupeSameTitlePresentations(): Promise<number> {
  const { DashboardApi } = await import("./dashboard");
  const presentations = await DashboardApi.getPresentations("v2-standard");
  const groups = new Map<string, typeof presentations>();
  for (const item of presentations) {
    const title = cleanEditCopyTitle(item.title);
    if (!title) continue;
    const list = groups.get(title) || [];
    list.push(item);
    groups.set(title, list);
  }

  let removed = 0;
  for (const items of groups.values()) {
    if (items.length < 2) continue;
    const sorted = [...items].sort((left, right) => {
      const rightTime = Date.parse(right.updated_at || right.created_at || "") || 0;
      const leftTime = Date.parse(left.updated_at || left.created_at || "") || 0;
      return rightTime - leftTime;
    });
    const newest = Date.parse(sorted[0].created_at || "") || 0;
    const burst = sorted.filter((item) => {
      const created = Date.parse(item.created_at || "") || 0;
      return Math.abs(created - newest) <= 5000;
    });
    if (burst.length < 2) continue;
    for (const extra of burst.slice(1)) {
      const result = await DashboardApi.deletePresentation(extra.id);
      if (result?.success) removed += 1;
    }
  }
  return removed;
}

export async function materializeTemplateDetails(
  template: TemplateDetailsResponse,
  layouts?: Array<Record<string, unknown>>,
): Promise<{ presentation_id: string; title: string }> {
  return upsertPresentationFromLayouts({
    templateId: template.id,
    title: template.name,
    layouts: layouts?.length ? layouts : layoutsFromTemplate(template),
    deleteTemplate: true,
  });
}
