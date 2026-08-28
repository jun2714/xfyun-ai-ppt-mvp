/**
 * UploadPage Component
 *
 * This component handles the presentation generation upload process, allowing users to:
 * - Configure presentation settings (slides, language)
 * - Input prompts
 * - Upload supporting documents
 *
 * @component
 */

"use client";
import React, { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useDispatch, useSelector } from "react-redux";
import { clearOutlines, setPresentationId } from "@/store/slices/presentationGeneration";
import { PromptInput } from "./PromptInput";
import { LanguageType, PresentationConfig } from "../type";
import SupportingDoc from "./SupportingDoc";
import { notify } from "@/components/ui/sonner";
import {
  PresentationGenerationApi,
  type KindergartenDomain,
} from "../../services/api/presentation-generation";
import { OverlayLoader } from "@/components/ui/overlay-loader";
import Wrapper from "@/components/Wrapper";
import { setPptGenUploadState } from "@/store/slices/presentationGenUpload";
import { trackEvent, MixpanelEvent } from "@/utils/mixpanel";
import { ConfigurationSelects, LanguageSelectControl } from "./ConfigurationSelects";
import { RootState } from "@/store/store";
import { ImagesApi } from "../../services/api/images";
import CurrentConfig from "./CurrentConfig";
import { LLMConfig } from "@/types/llm_config";
import {
  clampSlideCountValue,
  parseLimitedSlideCount,
} from "@/utils/presentationLimits";
import { type TeachingContextState } from "../../presentation/components/chat/chat-prompts";
import Header from "@/app/(presentation-generator)/(dashboard)/dashboard/components/Header";
import {
  buildTeachnovaPrompt,
  createTeachnovaDefaultConfig,
  getTeachnovaWebOutlineUrl,
  TEACHNOVA_API_LANGUAGE,
} from "../product-defaults";
import { isTeachnovaEmbed } from "@/utils/teachnovaEmbed";
import { withBridgeSessionQuery } from "@/utils/teachnovaSession";
import UploadTemplateGallery from "./UploadTemplateGallery";
// 社区参考暂不对外开放
// import CommunityReferencePicker from "./CommunityReferencePicker";
// import {
//   CommunityPresentationApi,
//   type CommunityPresentation,
// } from "../../services/api/community";

type CreateFlowMode = "topic" | "template";
const CREATE_FLOW_TABS: Array<{ id: CreateFlowMode; label: string; hint: string }> = [
  {
    id: "topic",
    label: "主题生成",
    hint: "输入主题后先生成幼教课堂大纲，再自动推荐或手动选择模板排版",
  },
  {
    id: "template",
    label: "模板生成",
    hint: "先生成并确认幼教课堂大纲，再选择模板进行排版",
  },
];

const STOCK_IMAGE_PROVIDERS = new Set(["pexels", "pixabay"]);
const FILE_TYPE_WORD = new Set([".doc", ".docx", ".docm", ".odt", ".rtf"]);
const FILE_TYPE_PRESENTATION = new Set([".ppt", ".pptx", ".pptm", ".odp"]);
const FILE_TYPE_SPREADSHEET = new Set([".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv"]);
const FILE_TYPE_IMAGE = new Set([".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"]);
const FILE_MIME_IMAGE = new Set(["image/jpeg", "image/png", "image/gif", "image/bmp", "image/tiff", "image/webp"]);
const FILE_TYPE_PDF = new Set([".pdf"]);
const FILE_TYPE_TEXT = new Set([".txt"]);

interface LoadingState {
  isLoading: boolean;
  message: string;
  duration?: number;
  showProgress?: boolean;
  extra_info?: string;
}

const AGE_GROUP_MAP: Record<string, string> = {
  "托班 2—3 岁": "2-3岁",
  "小班 3—4 岁": "3-4岁",
  "中班 4—5 岁": "4-5岁",
  "大班 5—6 岁": "5-6岁",
  "混龄班": "3-6岁混龄",
};

const DOMAIN_TERMS: Array<[KindergartenDomain, string[]]> = [
  ["math", ["数学", "数字", "数量", "数数", "加减", "图形", "形状", "排序", "规律", "空间"]],
  ["science", ["科学", "自然", "动物", "植物", "昆虫", "天气", "四季", "实验", "观察", "种子", "叶子"]],
  ["language", ["语言", "绘本", "故事", "童话", "儿歌", "阅读", "表达", "讲述", "诗歌"]],
  ["health", ["健康", "卫生", "洗手", "刷牙", "营养", "饮食", "运动", "安全", "睡眠", "生活习惯"]],
  ["art", ["艺术", "美术", "绘画", "颜色", "色彩", "手工", "音乐", "律动", "节奏", "舞蹈"]],
  ["social", ["社会", "礼仪", "规则", "情绪", "朋友", "合作", "分享", "交往", "家园", "节日"]],
];

const normalizeAgeGroup = (age?: string): string => {
  const value = age?.trim() || "";
  if (!value) return "4-5岁";
  if (AGE_GROUP_MAP[value]) return AGE_GROUP_MAP[value];
  const range = value.match(/(\d)\s*[—–-]\s*(\d)\s*岁/);
  return range ? `${range[1]}-${range[2]}岁` : value;
};

const inferKindergartenDomain = (text: string): KindergartenDomain => {
  const normalized = text.trim();
  if (!normalized) return "comprehensive";
  let best: { domain: KindergartenDomain; score: number } = {
    domain: "comprehensive",
    score: 0,
  };
  for (const [domain, terms] of DOMAIN_TERMS) {
    const score = terms.reduce(
      (total, term) => total + (normalized.includes(term) ? 1 : 0),
      0,
    );
    if (score > best.score) best = { domain, score };
  }
  return best.domain;
};

const buildPlannerInstructions = (
  baseInstructions: string | null | undefined,
  context: TeachingContextState,
): string | null => {
  const lines = [
    baseInstructions?.trim() || "",
    context.audience?.trim() ? `目标观众：${context.audience.trim()}` : "",
    context.scene?.trim() ? `课堂场景：${context.scene.trim()}` : "",
    context.style?.trim() ? `视觉偏好：${context.style.trim()}` : "",
  ].filter(Boolean);
  return lines.length ? lines.join("\n") : null;
};

const getFileExtension = (fileName: string): string => {
  const index = fileName.lastIndexOf(".");
  if (index < 0) return "";
  return fileName.slice(index).toLowerCase();
};

const getFileCategory = (file: File): string => {
  const extension = getFileExtension(file.name || "");
  if (FILE_TYPE_WORD.has(extension)) return "word";
  if (FILE_TYPE_PRESENTATION.has(extension)) return "presentation";
  if (FILE_TYPE_SPREADSHEET.has(extension)) return "spreadsheet";
  if (FILE_TYPE_IMAGE.has(extension) || FILE_MIME_IMAGE.has((file.type || "").toLowerCase())) return "image";
  if (FILE_TYPE_PDF.has(extension) || file.type === "application/pdf") return "pdf";
  if (FILE_TYPE_TEXT.has(extension) || file.type === "text/plain") return "text";
  return "other";
};

const getSelectedTextModel = (config?: LLMConfig): string => {
  if (!config) return "";
  switch (config.LLM) {
    case "openai":
      return config.OPENAI_MODEL || "";
    case "deepseek":
      return config.DEEPSEEK_MODEL || "";
    case "google":
      return config.GOOGLE_MODEL || "";
    case "vertex":
      return config.VERTEX_MODEL || "";
    case "azure":
      return config.AZURE_OPENAI_MODEL || "";
    case "bedrock":
      return config.BEDROCK_MODEL || "";
    case "openrouter":
      return config.OPENROUTER_MODEL || "";
    case "fireworks":
      return config.FIREWORKS_MODEL || "";
    case "together":
      return config.TOGETHER_MODEL || "";
    case "cerebras":
      return config.CEREBRAS_MODEL || "";
    case "litellm":
      return config.LITELLM_MODEL || "";
    case "lmstudio":
      return config.LMSTUDIO_MODEL || "";
    case "anthropic":
      return config.ANTHROPIC_MODEL || "";
    case "ollama":
      return config.OLLAMA_MODEL || "";
    case "custom":
      return config.CUSTOM_MODEL || "";
    case "codex":
      return config.CODEX_MODEL || "";
    default:
      return "";
  }
};

const getSelectedImageQuality = (config?: LLMConfig): string => {
  if (!config) return "";
  if (config.IMAGE_PROVIDER === "dall-e-3") return config.DALL_E_3_QUALITY || "";
  if (config.IMAGE_PROVIDER === "gpt-image-1.5") return config.GPT_IMAGE_1_5_QUALITY || "";
  return "";
};

const getDocumentPaths = (files: unknown): string[] => {
  if (!Array.isArray(files)) return [];
  return files
    .flat()
    .map((file) =>
      file && typeof file === "object" && "file_path" in file
        ? (file as { file_path?: unknown }).file_path
        : null,
    )
    .filter((filePath): filePath is string => typeof filePath === "string");
};

const UploadPage = () => {
  const pathname = usePathname();
  const dispatch = useDispatch();
  const llmConfig = useSelector((state: RootState) => state.userConfig.llm_config);

  const [files, setFiles] = useState<File[]>([]);
  const generationMode = "standard" as const;
  const [createFlowMode, setCreateFlowMode] = useState<CreateFlowMode>("topic");
  const [teachingContext, setTeachingContext] = useState<TeachingContextState>({
    audience: "幼儿",
    age: "中班 4—5 岁",
    scene: "集体教学",
    style: "明亮童趣",
  });
  const [config, setConfig] = useState<PresentationConfig>(
    createTeachnovaDefaultConfig,
  );

  const continueToOutline = (presentationId: string, templateId?: string | null) => {
    const outlineUrl = new URL(
      getTeachnovaWebOutlineUrl(presentationId, {
        createMode: createFlowMode,
        templateId: templateId || undefined,
      }),
    );
    if (isTeachnovaEmbed()) outlineUrl.searchParams.set("embed", "teachnova");
    const destination = withBridgeSessionQuery(outlineUrl.toString());
    trackEvent(MixpanelEvent.Navigation, { from: pathname, to: destination });
    window.location.assign(destination);
  };

  const handleCreateFlowModeChange = (mode: CreateFlowMode) => {
    setCreateFlowMode(mode);
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedPrompt = params.get("prompt")?.trim();
    if (requestedPrompt) {
      setConfig((current) => ({ ...current, prompt: requestedPrompt }));
    }
  }, []);

  useEffect(() => {
    if (llmConfig?.WEB_GROUNDING !== undefined) {
      setConfig((current) => ({
        ...current,
        webSearch: !!llmConfig.WEB_GROUNDING,
      }));
    }
  }, [llmConfig?.WEB_GROUNDING]);

  const [loadingState, setLoadingState] = useState<LoadingState>({
    isLoading: false,
    message: "",
    duration: 4,
    showProgress: false,
    extra_info: "",
  });

  const getUploadSnapshotProps = () => {
    const trimmedPrompt = config.prompt.trim();
    const trimmedInstructions = (config.instructions || "").trim();
    const attachmentCategories = Array.from(new Set(files.map(getFileCategory))).sort();
    const imageGenerationEnabled = !llmConfig?.DISABLE_IMAGE_GENERATION;
    const parsedSlides = parseLimitedSlideCount(config.slides);

    return {
      pathname,
      generation_path: files.length > 0 ? "documents" : "prompt_only",
      slides_selected: parsedSlides,
      slides_mode: config.slides ? "selected" : "auto",
      language: config.language || "",
      tone: config.tone,
      verbosity: config.verbosity,
      include_table_of_contents: !!config.includeTableOfContents,
      include_title_slide: !!config.includeTitleSlide,
      web_search: !!config.webSearch,
      generation_mode: generationMode,
      create_flow_mode: createFlowMode,
      community_reference_id: null,
      has_prompt: Boolean(trimmedPrompt),
      prompt_char_count: trimmedPrompt.length,
      prompt_word_count: trimmedPrompt ? trimmedPrompt.split(/\s+/).filter(Boolean).length : 0,
      has_instructions: Boolean(trimmedInstructions),
      instructions_char_count: trimmedInstructions.length,
      has_attachments: files.length > 0,
      attachments_count: files.length,
      attachment_categories: attachmentCategories.join(","),
      text_provider: llmConfig?.LLM || "",
      text_model: getSelectedTextModel(llmConfig),
      image_generation_enabled: imageGenerationEnabled,
      image_provider: imageGenerationEnabled ? (llmConfig?.IMAGE_PROVIDER || "") : "disabled",
      image_quality: imageGenerationEnabled ? getSelectedImageQuality(llmConfig) : "",
    };
  };

  const trackUploadValidationFailure = (reason: string) => {
    trackEvent(MixpanelEvent.Upload_Configuration_Invalid, {
      ...getUploadSnapshotProps(),
      reason,
    });
  };

  const handleConfigChange = (key: keyof PresentationConfig, value: unknown) => {
    const nextValue =
      key === "slides" && typeof value === "string"
        ? clampSlideCountValue(value)
        : value;
    setConfig((prev) => ({ ...prev, [key]: nextValue } as PresentationConfig));
  };

  const ensureStockImageProviderReady = async (): Promise<boolean> => {
    if (llmConfig?.DISABLE_IMAGE_GENERATION) return true;

    const selectedProvider = (llmConfig?.IMAGE_PROVIDER || "").toLowerCase();
    if (!STOCK_IMAGE_PROVIDERS.has(selectedProvider)) return true;

    try {
      const providerApiKey =
        selectedProvider === "pexels"
          ? llmConfig?.PEXELS_API_KEY
          : llmConfig?.PIXABAY_API_KEY;
      await ImagesApi.searchStockImages("business", 1, {
        provider: selectedProvider,
        apiKey: providerApiKey,
        strictApiKey: true,
      });
      return true;
    } catch (error: any) {
      notify.error(
        "Image provider unavailable",
        error?.message ||
          `Unable to reach ${selectedProvider} right now. Please check your API key/settings and try again.`,
      );
      return false;
    }
  };

  const validateConfiguration = (): boolean => {
    if (!config.language) {
      trackUploadValidationFailure("language_missing");
      notify.warning("请选择语言", "请选择演示文稿语言。");
      return false;
    }

    if (files.length > 0 && config.language === LanguageType.Auto) {
      trackUploadValidationFailure("language_auto_with_documents");
      notify.warning("请选择语言", "处理上传文档前，请先选择演示文稿语言。");
      return false;
    }

    if (!config.prompt.trim() && files.length === 0) {
      trackUploadValidationFailure("prompt_or_document_missing");
      notify.warning("请输入内容", "请输入主题或上传文档后再生成。");
      return false;
    }
    return true;
  };

  const handleGeneratePresentation = async () => {
    if (!validateConfiguration()) return;
    trackEvent(MixpanelEvent.Upload_Generation_Started, getUploadSnapshotProps());

    const isStockProviderReady = await ensureStockImageProviderReady();
    if (!isStockProviderReady) {
      trackUploadValidationFailure("stock_image_provider_unreachable");
      return;
    }

    try {
      if (files.length > 0) await handleDocumentProcessing();
      else await handleDirectPresentationGeneration();
    } catch (error) {
      handleGenerationError(error);
    }
  };

  const createKindergartenOutline = async (documentPaths: string[]) => {
    const topic = config.prompt.trim() || "根据上传资料生成幼教课件";
    const requestContext = teachingContext;
    const requestContent = buildTeachnovaPrompt(topic, requestContext);
    const plannerInstructions = buildPlannerInstructions(
      config.instructions,
      requestContext,
    );
    const createResponse = await PresentationGenerationApi.createKindergartenPresentation({
      topic,
      age_group: normalizeAgeGroup(requestContext.age),
      domain: inferKindergartenDomain(`${topic}\n${plannerInstructions || ""}`),
      duration_minutes: 20,
      n_slides: parseLimitedSlideCount(config?.slides),
      instructions: plannerInstructions,
      template: "auto",
      language: TEACHNOVA_API_LANGUAGE,
      image_policy: llmConfig?.DISABLE_IMAGE_GENERATION ? "disabled" : "standard",
      file_paths: documentPaths,
      tone: config?.tone,
      verbosity: config?.verbosity,
    });

    dispatch(
      setPptGenUploadState({
        config,
        files: documentPaths,
        generationMode,
        requestContent,
        requestContext,
      }),
    );
    dispatch(clearOutlines());
    dispatch(setPresentationId(createResponse.presentation_id));

    return {
      createResponse,
      requestContent,
      requestContext,
      destination: getTeachnovaWebOutlineUrl(createResponse.presentation_id, {
        createMode: createFlowMode,
        templateId: createResponse.selected_template,
      }),
    };
  };

  const handleDocumentProcessing = async () => {
    setLoadingState({
      isLoading: true,
      message: "正在处理文档…",
      showProgress: true,
      duration: 90,
      extra_info: files.length > 0 ? "较大的文档可能需要几分钟。" : "",
    });

    let documents = [];
    if (files.length > 0) {
      documents = await PresentationGenerationApi.uploadDoc(files);
    }

    const promises: Promise<any>[] = [];
    if (documents.length > 0) {
      promises.push(
        PresentationGenerationApi.decomposeDocuments(
          documents,
          TEACHNOVA_API_LANGUAGE,
        ),
      );
    }
    const responses = await Promise.all(promises);
    const documentPaths = getDocumentPaths(responses);

    setLoadingState({
      isLoading: true,
      message: "AI 正在规划幼教课堂大纲…",
      showProgress: true,
      duration: 50,
      extra_info: "会先检查教学逻辑、互动答案和图片语义，再进入大纲确认。",
    });

    const { createResponse, destination } = await createKindergartenOutline(documentPaths);
    trackEvent(MixpanelEvent.Upload_Documents_Processed, {
      ...getUploadSnapshotProps(),
      uploaded_documents_count: documents.length,
      decompose_job_count: responses.length,
      extracted_document_count: documentPaths.length,
      selected_template: createResponse.selected_template,
      planning_attempts: createResponse.planning_attempts,
      destination,
    });
    trackEvent(MixpanelEvent.Upload_Outline_Generation_Requested, {
      ...getUploadSnapshotProps(),
      presentation_id: createResponse.presentation_id,
      selected_template: createResponse.selected_template,
      uploaded_documents_count: documents.length,
      extracted_document_count: documentPaths.length,
      destination,
    });
    continueToOutline(
      createResponse.presentation_id,
      createResponse.selected_template,
    );
  };

  const handleDirectPresentationGeneration = async () => {
    setLoadingState({
      isLoading: true,
      message: "AI 正在规划幼教课堂大纲…",
      showProgress: true,
      duration: 45,
      extra_info: "会先检查教学逻辑、互动答案和图片语义，再进入大纲确认。",
    });

    const { createResponse, destination } = await createKindergartenOutline([]);
    trackEvent(MixpanelEvent.Upload_Outline_Generation_Requested, {
      ...getUploadSnapshotProps(),
      presentation_id: createResponse.presentation_id,
      selected_template: createResponse.selected_template,
      planning_attempts: createResponse.planning_attempts,
      destination,
    });
    continueToOutline(
      createResponse.presentation_id,
      createResponse.selected_template,
    );
  };

  const handleGenerationError = (error: any) => {
    console.error("Error in upload page", error);
    setLoadingState({
      isLoading: false,
      message: "",
      duration: 0,
      showProgress: false,
    });
    notify.error(
      "生成失败",
      error.message || "启动演示文稿生成时发生错误。",
    );
  };

  return (
    <div className="relative min-h-dvh">
      <Header
        rightSlot={
          <LanguageSelectControl
            value={config.language}
            onValueChange={(value) => handleConfigChange("language", value)}
            compact
          />
        }
      />
      <div className="mb-8 flex flex-col items-center justify-center px-4 text-center">
        <h1 className="relative font-syne text-4xl font-semibold leading-[112%] text-[#101323] sm:text-5xl lg:text-[64px] min-[1920px]:text-[76px] min-[2560px]:text-[88px]">
          生成幼教PPT
          <svg className="absolute -left-6 -top-8 sm:-left-12 sm:-top-12 lg:-left-20 lg:-top-16" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 13 13" fill="none">
            <path d="M9.73497 5.85272C8.05237 5.69492 6.72098 4.39958 6.55904 2.76316L6.28582 0L6.0126 2.76316C5.85066 4.39985 4.51927 5.6952 2.83667 5.85272L0 6.11849L2.83667 6.38426C4.51927 6.54206 5.85066 7.8374 6.0126 9.47382L6.28582 12.237L6.55904 9.47382C6.72098 7.83713 8.05237 6.54178 9.73497 6.38426L12.5716 6.11849L9.73497 5.85272Z" fill="#09CCFE" />
          </svg>
          <svg className="absolute -left-2 -top-6 sm:-left-4 sm:-top-8" xmlns="http://www.w3.org/2000/svg" width="26" height="25" viewBox="0 0 26 25" fill="none">
            <path d="M19.4699 11.7054C16.1047 11.3898 13.442 8.79915 13.1181 5.52632L12.5716 0L12.0252 5.52632C11.7013 8.79971 9.03854 11.3904 5.67335 11.7054L0 12.237L5.67335 12.7685C9.03854 13.0841 11.7013 15.6748 12.0252 18.9476L12.5716 24.474L13.1181 18.9476C13.442 15.6743 16.1047 13.0836 19.4699 12.7685L25.1433 12.237L19.4699 11.7054Z" fill="#09CCFE" />
          </svg>
          <svg className="absolute -right-7 bottom-0 sm:-right-10" xmlns="http://www.w3.org/2000/svg" width="41" height="41" viewBox="0 0 41 41" fill="none">
            <path d="M31.6166 19.8734C26.275 19.3587 22.0484 15.134 21.5343 9.797L20.6669 0.785156L19.7995 9.797C19.2854 15.1349 15.0588 19.3596 9.71723 19.8734L0.711914 20.7401L9.71723 21.6069C15.0588 22.1216 19.2854 26.3462 19.7995 31.6833L20.6669 40.6951L21.5343 31.6833C22.0484 26.3453 26.275 22.1207 31.6166 21.6069L40.6219 20.7401L31.6166 19.8734Z" fill="#DF92FC" />
          </svg>
        </h1>
        <p className="mt-2 max-w-2xl font-syne text-base text-[#101323CC] sm:text-lg lg:text-xl min-[1920px]:text-2xl">
          先规划一节能上课的幼教活动，再确认大纲与模板
        </p>
      </div>

      <Wrapper className="w-full pb-10">
        <OverlayLoader
          show={loadingState.isLoading}
          text={loadingState.message}
          showProgress={loadingState.showProgress}
          duration={loadingState.duration}
          extra_info={loadingState.extra_info}
        />
        <div className="mx-auto mb-6 flex max-w-[760px] justify-center px-4 lg:max-w-[780px] xl:max-w-[900px] min-[1600px]:max-w-[1050px] min-[1920px]:max-w-[1280px]">
          <div
            role="tablist"
            aria-label="生成方式"
            className="inline-flex rounded-lg bg-[#F6F6F9] p-1"
          >
            {CREATE_FLOW_TABS.map((tab) => {
              const active = createFlowMode === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={`rounded-md px-4 py-2 font-syne text-sm font-semibold transition-colors ${
                    active
                      ? "bg-white text-[#6847F4] shadow-[0_1px_3px_rgba(16,19,35,0.08)]"
                      : "text-[#667085] hover:text-[#344054]"
                  }`}
                  onClick={() => handleCreateFlowModeChange(tab.id)}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="mx-auto mb-[40px] max-w-[760px] space-y-[18px] px-4 lg:max-w-[780px] xl:max-w-[900px] min-[1600px]:max-w-[1050px] min-[1920px]:max-w-[1280px]">
          <div className="flex min-h-[34px] w-full flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded-md bg-[#F4F1FF] px-3 py-1.5 font-syne text-xs font-semibold text-[#6847F4]">
              {createFlowMode === "template" ? "模板生成" : "主题生成"}
            </span>
            <CurrentConfig webSearchEnabled={config.webSearch} />
          </div>
          <p className="text-xs text-[#667085]">
            {CREATE_FLOW_TABS.find((tab) => tab.id === createFlowMode)?.hint}
          </p>

          <PromptInput
            value={config.prompt}
            variant={generationMode}
            onChange={(value) => handleConfigChange("prompt", value)}
            onSubmit={handleGeneratePresentation}
            hasAttachments={files.length > 0}
            teachingContext={teachingContext}
            onTeachingContextChange={setTeachingContext}
            teachingContextDisabled={loadingState.isLoading}
            toolbarRight={
              <ConfigurationSelects
                compact
                hideLanguage
                config={config}
                onConfigChange={handleConfigChange}
              />
            }
            footer={
              <SupportingDoc
                files={files}
                onFilesChange={setFiles}
                onSubmit={handleGeneratePresentation}
                disabled={loadingState.isLoading}
              />
            }
          />
        </div>

        {createFlowMode === "template" ? (
          <div className="px-0 pb-8">
            <UploadTemplateGallery />
          </div>
        ) : null}
      </Wrapper>
    </div>
  );
};

export default UploadPage;
