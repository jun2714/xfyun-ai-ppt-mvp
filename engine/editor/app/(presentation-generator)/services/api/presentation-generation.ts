import { getHeader, getHeaderForFormData } from "./header";
import { IconSearch, ImageGenerate, PreviousGeneratedImagesResponse } from "./params";
import { ApiResponseHandler } from "./api-error-handler";
import { getApiUrl, resolveBackendAssetUrl } from "@/utils/api";
import {
  limitOutlines,
  MAX_NUMBER_OF_SLIDES,
} from "@/utils/presentationLimits";
import type { PresentationVersion } from "./dashboard";
import type { Slide } from "../../types/slide";

export type BlankPresentationResponse = {
  id: string;
  version: PresentationVersion;
  title: string | null;
  n_slides: number;
  language: string;
  fonts?: Record<string, string> | null;
  slides: Array<Record<string, unknown>>;
};

export type KindergartenDomain =
  | "science"
  | "language"
  | "math"
  | "health"
  | "social"
  | "art"
  | "comprehensive";

export type KindergartenVisualMode = "template" | "ai-background";

export type KindergartenPresentationCreateResponse = {
  presentation_id: string;
  outline_path: string;
  selected_template: string;
  template_selection_reason: string;
  template_scores: Record<string, number>;
  visual_mode: KindergartenVisualMode;
  visual_style_summary?: string | null;
  planning_attempts: number;
  quality: {
    passed: boolean;
    errors: unknown[];
    warnings: unknown[];
  };
  outline: {
    slides: Array<{ content: string; content_contract?: unknown }>;
  };
};

export class PresentationGenerationApi {
  static async uploadDoc(documents: File[]) {
    const formData = new FormData();

    documents.forEach((document) => {
      formData.append("files", document);
    });

    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/files/upload`),
        {
          method: "POST",
          headers: getHeaderForFormData(),
          body: formData,
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to upload documents");
    } catch (error) {
      console.error("Upload error:", error);
      throw error;
    }
  }

  static async decomposeDocuments(
    documentKeys: string[],
    language?: string | null
  ) {
    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/files/decompose`),
        {
          method: "POST",
          headers: getHeader(),
          body: JSON.stringify({
            file_paths: documentKeys,
            language: language ?? null,
          }),
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to decompose documents");
    } catch (error) {
      console.error("Error in Decompose Files", error);
      throw error;
    }
  }

  static async createPresentation({
    content,
    version = "v2-standard",
    n_slides,
    file_paths,
    language,
    tone,
    verbosity,
    instructions,
    include_table_of_contents,
    include_title_slide,
    web_search,
    generation_mode = "standard",
    community_design_ids,
    image_policy = "standard",

  }: {
    content: string;
    version?: PresentationVersion;
    n_slides: number | null;
    file_paths?: string[];
    language: string | null;
    tone?: string | null;
    verbosity?: string | null;
    instructions?: string | null;
    include_table_of_contents?: boolean;
    include_title_slide?: boolean;
    web_search?: boolean;
    generation_mode?: "standard" | "smart";
    community_design_ids?: number[];
    image_policy?: "disabled" | "minimal" | "standard";
  }) {
    try {
      const limitedSlideCount =
        typeof n_slides === "number"
          ? Math.min(Math.max(n_slides, 1), MAX_NUMBER_OF_SLIDES)
          : null;
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/presentation/create`),
        {
          method: "POST",
          headers: getHeader(),
          body: JSON.stringify({
            content,
            version,
            n_slides: limitedSlideCount,
            file_paths,
            language,
            tone,
            verbosity,
            instructions,
            include_table_of_contents,
            include_title_slide,
            web_search,
            generation_mode,
            community_design_ids,
            image_policy,
          }),
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to create presentation");
    } catch (error) {
      console.error("error in presentation creation", error);
      throw error;
    }
  }

  static async createKindergartenPresentation({
    topic,
    age_group = "4-5岁",
    domain = "comprehensive",
    duration_minutes = 20,
    n_slides,
    instructions,
    source_context,
    template = "auto",
    visual_mode = "template",
    visual_style,
    language = "Chinese",
    image_policy = "standard",
    file_paths = [],
    tone = "educational",
    verbosity = "standard",
  }: {
    topic: string;
    age_group?: string;
    domain?: KindergartenDomain;
    duration_minutes?: number;
    n_slides: number | null;
    instructions?: string | null;
    source_context?: string | null;
    template?: string;
    visual_mode?: KindergartenVisualMode;
    visual_style?: string | null;
    language?: string;
    image_policy?: "disabled" | "minimal" | "standard";
    file_paths?: string[];
    tone?: string | null;
    verbosity?: string | null;
  }): Promise<KindergartenPresentationCreateResponse> {
    try {
      const limitedSlideCount =
        typeof n_slides === "number"
          ? Math.min(Math.max(n_slides, 3), MAX_NUMBER_OF_SLIDES)
          : null;
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/kindergarten/presentation/create`),
        {
          method: "POST",
          headers: getHeader(),
          body: JSON.stringify({
            topic,
            age_group,
            domain,
            duration_minutes,
            n_slides: limitedSlideCount,
            instructions,
            source_context,
            template,
            visual_mode,
            visual_style,
            language,
            image_policy,
            file_paths,
            tone,
            verbosity,
          }),
          cache: "no-cache",
        }
      );

      return (await ApiResponseHandler.handleResponse(
        response,
        "Failed to create kindergarten presentation"
      )) as KindergartenPresentationCreateResponse;
    } catch (error) {
      console.error("error in kindergarten presentation creation", error);
      throw error;
    }
  }

  static async createBlankPresentation(): Promise<BlankPresentationResponse> {
    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/presentation/create/blank`),
        {
          method: "POST",
          headers: getHeader(),
          cache: "no-cache",
        }
      );
      const presentation = (await ApiResponseHandler.handleResponse(
        response,
        "Failed to create blank presentation"
      )) as BlankPresentationResponse;

      if (!presentation || typeof presentation.id !== "string") {
        throw new Error("Blank presentation response did not include an id");
      }

      return presentation;
    } catch (error) {
      console.error("error in blank presentation creation", error);
      throw error;
    }
  }

  static async editSlide(
    slide_id: string,
    prompt: string
  ) {
    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/slide/edit`),
        {
          method: "POST",
          headers: getHeader(),
          body: JSON.stringify({
            id: slide_id,
            prompt,
          }),
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to update slide");
    } catch (error) {
      console.error("error in slide update", error);
      throw error;
    }
  }

  static async updatePresentationContent(body: unknown) {
    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/presentation/update`),
        {
          method: "PATCH",
          headers: getHeader(),
          body: typeof body === "string" ? body : JSON.stringify(body),
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to update presentation content");
    } catch (error) {
      console.error("error in presentation content update", error);
      throw error;
    }
  }

  static async updatePresentationSlide(slide: Slide) {
    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/presentation/slide_update`),
        {
          method: "PATCH",
          headers: getHeader(),
          body: JSON.stringify({ slide }),
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(
        response,
        "Failed to update slide"
      );
    } catch (error) {
      console.error("error in presentation slide update", error);
      throw error;
    }
  }

  static async presentationPrepare(presentationData: any) {
    try {
      const body =
        Array.isArray(presentationData?.outlines)
          ? {
            ...presentationData,
            outlines: limitOutlines(presentationData.outlines),
          }
          : presentationData;
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/presentation/prepare`),
        {
          method: "POST",
          headers: getHeader(),
          body: JSON.stringify(body),
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to prepare presentation");
    } catch (error) {
      console.error("error in data generation", error);
      throw error;
    }
  }

  static async getOutlines(presentationId: string): Promise<{ slides: { content: string }[] }> {
    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/outlines/${presentationId}`),
        {
          method: "GET",
          headers: getHeader(),
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to fetch outlines");
    } catch (error) {
      console.error("error in outline fetch", error);
      throw error;
    }
  }

  static async updateOutlines(
    presentationId: string,
    outlines: { content: string; content_contract?: unknown }[]
  ): Promise<{ slides: { content: string; content_contract?: unknown }[] }> {
    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/outlines/${presentationId}`),
        {
          method: "PUT",
          headers: getHeader(),
          body: JSON.stringify({ slides: limitOutlines(outlines) }),
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to update outlines");
    } catch (error) {
      console.error("error in outline update", error);
      throw error;
    }
  }

  // IMAGE AND ICON SEARCH


  static async generateImage(imageGenerate: ImageGenerate) {
    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/images/generate?prompt=${imageGenerate.prompt}`),
        {
          method: "GET",
          headers: getHeader(),
          cache: "no-cache",
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to generate image");
    } catch (error) {
      console.error("error in image generation", error);
      throw error;
    }
  }

  static getPreviousGeneratedImages = async (): Promise<PreviousGeneratedImagesResponse[]> => {
    try {
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/images/generated`),
        {
          method: "GET",
          headers: getHeader(),
        }
      );

      return await ApiResponseHandler.handleResponse(response, "Failed to get previous generated images");
    } catch (error) {
      console.error("error in getting previous generated images", error);
      throw error;
    }
  }

  static async searchIcons(iconSearch: IconSearch) {
    try {
      const params = new URLSearchParams({
        query: iconSearch.query,
        limit: String(iconSearch.limit),
      });
      if (iconSearch.icon_type) {
        params.set("icon_type", iconSearch.icon_type);
      }
      if (iconSearch.icon_weight) {
        params.set("icon_weight", iconSearch.icon_weight);
      }
      const response = await fetch(
        getApiUrl(`/api/v1/ppt/icons/search?${params.toString()}`),
        {
          method: "GET",
          headers: getHeader(),
          cache: "no-cache",
        }
      );

      const icons = await ApiResponseHandler.handleResponse(response, "Failed to search icons");
      return Array.isArray(icons)
        ? icons.map((icon) =>
          typeof icon === "string" ? resolveBackendAssetUrl(icon) : icon
        )
        : icons;
    } catch (error) {
      console.error("error in icon search", error);
      throw error;
    }
  }

}