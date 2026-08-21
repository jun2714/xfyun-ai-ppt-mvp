import { getApiUrl } from "@/utils/api";
import { ApiResponseHandler } from "./api-error-handler";
import { getHeader, getHeaderForFormData } from "./header";

export interface LibraryItem {
  id: string;
  title: string;
  description?: string | null;
  category: string;
  age_group: string;
  page_count: number;
  thumbnail?: string | null;
  slide_image_urls?: string[];
  download_count: number;
  editable: boolean;
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

export class LibraryService {
  static async list(params: {
    q?: string;
    category?: string;
    age_group?: string;
  } = {}): Promise<LibraryListResponse> {
    const search = new URLSearchParams();
    if (params.q) search.set("q", params.q);
    if (params.category && params.category !== "全部") search.set("category", params.category);
    if (params.age_group && params.age_group !== "全部") search.set("age_group", params.age_group);
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
  }): Promise<LibraryItem> {
    const form = new FormData();
    form.append("file", payload.file);
    form.append("title", payload.title);
    form.append("description", payload.description || "");
    form.append("category", payload.category);
    form.append("age_group", payload.age_group);
    const response = await fetch(getApiUrl("/api/v1/ppt/library"), {
      method: "POST",
      headers: getHeaderForFormData(),
      body: form,
    });
    return ApiResponseHandler.handleResponse(response, "上传案例失败");
  }

  static async get(itemId: string): Promise<LibraryItem> {
    const response = await fetch(
      getApiUrl(`/api/v1/ppt/library/${encodeURIComponent(itemId)}`),
      { headers: getHeader() },
    );
    return ApiResponseHandler.handleResponse(response, "加载案例失败");
  }

  static async cloneForEdit(itemId: string): Promise<{ template_id: string; title: string }> {
    const response = await fetch(
      getApiUrl(`/api/v1/ppt/library/${encodeURIComponent(itemId)}/clone`),
      {
        method: "POST",
        headers: getHeader(),
      },
    );
    return ApiResponseHandler.handleResponse(response, "创建编辑副本失败");
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
