import { getApiUrl } from "@/utils/api";
import { ApiResponseHandler } from "./api-error-handler";
import { getHeader, getHeaderForFormData } from "./header";
import { pickUuid } from "@/utils/uuid";
import { materializeTemplateAsPresentation } from "./materialize-template";

export interface LibraryItem {
  id: string;
  title: string;
  description?: string | null;
  category: string;
  age_group: string;
  season?: string;
  scene?: string;
  page_count: number;
  thumbnail?: string | null;
  slide_image_urls?: string[];
  download_count: number;
  editable: boolean;
  preview_status?: string;
  preview_engine?: string;
  created_at?: string;
  updated_at?: string;
}

export interface LibraryListResponse {
  items: LibraryItem[];
  total: number;
  can_manage?: boolean;
}

export const LIBRARY_CATEGORIES = [
  "全部",
  "健康",
  "语言",
  "社会",
  "科学",
  "艺术",
  "家园共育",
  "节日",
  "其他",
] as const;

export const LIBRARY_AGE_GROUPS = ["全部", "小班", "中班", "大班", "混龄"] as const;
export const LIBRARY_SEASONS = ["全部", "春季", "秋季", "不限"] as const;
export const LIBRARY_SCENES = ["全部", "教学", "家长会", "公开课", "其他"] as const;

export function guessLibraryTags(filename: string) {
  const text = filename.replace(/\.pptx$/i, "");
  const title = text.replace(/^\d+\s*/, "").replace(/^《|》$/g, "").trim() || text;
  let age_group = "混龄";
  if (text.includes("小班")) age_group = "小班";
  else if (text.includes("中班")) age_group = "中班";
  else if (text.includes("大班")) age_group = "大班";
  let season = "不限";
  if (/春|下学期/.test(text)) season = "春季";
  else if (/秋|上学期|开学/.test(text)) season = "秋季";
  let scene = "其他";
  if (/公开课|观摩/.test(text)) scene = "公开课";
  else if (/家长会|家长|毕业|幼小|衔接/.test(text)) scene = "家长会";
  else if (text.includes("教学")) scene = "教学";
  let category = scene === "家长会" ? "家园共育" : "其他";
  if (/健康|卫生|安全/.test(text)) category = "健康";
  else if (/语言|阅读|绘本/.test(text)) category = "语言";
  else if (/社会|交往/.test(text)) category = "社会";
  else if (/科学|探索/.test(text)) category = "科学";
  else if (/艺术|美术|音乐/.test(text)) category = "艺术";
  else if (/节日|新年|端午|中秋/.test(text)) category = "节日";
  return { title, category, age_group, season, scene };
}

export class LibraryService {
  static async list(params: {
    q?: string;
    category?: string;
    age_group?: string;
    season?: string;
    scene?: string;
  } = {}): Promise<LibraryListResponse> {
    const search = new URLSearchParams();
    if (params.q) search.set("q", params.q);
    if (params.category && params.category !== "全部") search.set("category", params.category);
    if (params.age_group && params.age_group !== "全部") search.set("age_group", params.age_group);
    if (params.season && params.season !== "全部") search.set("season", params.season);
    if (params.scene && params.scene !== "全部") search.set("scene", params.scene);
    const query = search.toString();
    const response = await fetch(
      getApiUrl(`/api/v1/ppt/library${query ? `?${query}` : ""}`),
      { headers: getHeader() },
    );
    return ApiResponseHandler.handleResponse(response, "加载素材库失败");
  }

  static async upload(payload: {
    file: File;
    title: string;
    description?: string;
    category: string;
    age_group: string;
    season?: string;
    scene?: string;
  }): Promise<LibraryItem> {
    const maxAttempts = 3;
    let lastError: Error | null = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      const form = new FormData();
      form.append("file", payload.file);
      form.append("title", payload.title);
      form.append("description", payload.description || "");
      form.append("category", payload.category);
      form.append("age_group", payload.age_group);
      form.append("season", payload.season || "不限");
      form.append("scene", payload.scene || "其他");
      const response = await fetch(getApiUrl("/api/v1/ppt/library"), {
        method: "POST",
        headers: getHeaderForFormData(),
        body: form,
      });
      if (response.ok || ![502, 503, 504].includes(response.status) || attempt === maxAttempts) {
        return ApiResponseHandler.handleResponse(response, "上传案例失败");
      }
      lastError = new Error("网关暂时不可用，正在重试上传");
      await new Promise((resolve) => window.setTimeout(resolve, 800 * attempt));
    }
    throw lastError ?? new Error("上传案例失败");
  }

  static async get(itemId: string): Promise<LibraryItem> {
    const response = await fetch(
      getApiUrl(`/api/v1/ppt/library/${encodeURIComponent(itemId)}`),
      { headers: getHeader() },
    );
    return ApiResponseHandler.handleResponse(response, "加载案例失败");
  }

  static async cloneForEdit(itemId: string): Promise<{ presentation_id: string; title: string }> {
    const response = await fetch(
      getApiUrl(`/api/v1/ppt/library/${encodeURIComponent(itemId)}/clone`),
      {
        method: "POST",
        headers: getHeader(),
      },
    );
    const data = await ApiResponseHandler.handleResponse(response, "创建可编辑项目失败");
    const presentationId = pickUuid(
      data?.presentation_id,
      data?.presentationId,
      data?.id,
    );
    const templateId = pickUuid(data?.template_id, data?.templateV2Id);
    if (presentationId) {
      return {
        presentation_id: presentationId,
        title: data?.title || "",
      };
    }
    if (templateId) {
      const converted = await materializeTemplateAsPresentation(
        templateId,
        data?.title,
      );
      return {
        presentation_id: converted.presentation_id,
        title: converted.title || data?.title || "",
      };
    }
    throw new Error("未返回有效项目编号");
  }

  static async download(itemId: string, title: string): Promise<void> {
    const response = await fetch(
      getApiUrl(`/api/v1/ppt/library/${encodeURIComponent(itemId)}/download`),
      { headers: getHeaderForFormData() },
    );
    if (!response.ok) {
      await ApiResponseHandler.handleResponse(response, "下载失败");
      return;
    }
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const data = (await response.json()) as { url?: string };
      if (!data.url) {
        throw new Error("下载地址为空");
      }
      const link = document.createElement("a");
      link.href = data.url;
      link.download = `${title || "案例"}.pptx`;
      link.rel = "noopener";
      link.target = "_blank";
      document.body.appendChild(link);
      link.click();
      link.remove();
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${title || "案例"}.pptx`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  static async remove(itemId: string): Promise<void> {
    const response = await fetch(
      getApiUrl(`/api/v1/ppt/library/${encodeURIComponent(itemId)}`),
      {
        method: "DELETE",
        headers: getHeader(),
      },
    );
    if (!response.ok) {
      await ApiResponseHandler.handleResponse(response, "删除失败");
    }
  }
}
