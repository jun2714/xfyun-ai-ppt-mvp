"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Download, Loader2, Pencil, Plus, Search, Trash2, Upload, ChevronLeft, ChevronRight, X, Presentation } from "lucide-react";
import { notify } from "@/components/ui/sonner";
import { resolveBackendAssetUrl } from "@/utils/api";
import { isTeachnovaEmbed } from "@/utils/teachnovaEmbed";
import {
  LIBRARY_AGE_GROUPS,
  LIBRARY_CATEGORIES,
  LIBRARY_SCENES,
  LIBRARY_SEASONS,
  LibraryService,
  guessLibraryTags,
  type LibraryItem,
} from "../../../services/api/library";

type UploadQueueItem = {
  key: string;
  file: File;
  title: string;
  category: string;
  age_group: string;
  season: string;
  scene: string;
  status: "queued" | "uploading" | "done" | "error";
  error?: string;
};

function isCoverPending(item: LibraryItem) {
  if (item.preview_status === "failed") return false;
  if (item.preview_status === "pending" || item.preview_status === "generating") {
    return !item.thumbnail;
  }
  return !item.thumbnail;
}

function isPreviewWaiting(item: LibraryItem) {
  if (item.preview_status === "failed") return false;
  if (item.preview_status === "pending" || item.preview_status === "generating") return true;
  return !(item.slide_image_urls || []).length;
}

function mergeLibraryItems(current: LibraryItem[], incoming: LibraryItem[]) {
  const incomingIds = new Set(incoming.map((item) => item.id));
  const pendingLocal = current.filter((item) => !incomingIds.has(item.id));
  const mergedIncoming = incoming.map((item) => {
    const local = current.find((row) => row.id === item.id);
    if (!local) return item;
    return {
      ...local,
      ...item,
      thumbnail: item.thumbnail || local.thumbnail,
      slide_image_urls:
        item.slide_image_urls && item.slide_image_urls.length
          ? item.slide_image_urls
          : local.slide_image_urls,
      preview_status: item.preview_status || local.preview_status,
    };
  });
  return [...pendingLocal, ...mergedIncoming];
}

export default function LibraryPanel() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<(typeof LIBRARY_CATEGORIES)[number]>("全部");
  const [ageGroup, setAgeGroup] = useState<(typeof LIBRARY_AGE_GROUPS)[number]>("全部");
  const [season, setSeason] = useState<(typeof LIBRARY_SEASONS)[number]>("全部");
  const [scene, setScene] = useState<(typeof LIBRARY_SCENES)[number]>("全部");
  const [queue, setQueue] = useState<UploadQueueItem[]>([]);
  const [uploadProgress, setUploadProgress] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const queueRef = useRef<UploadQueueItem[]>([]);
  const uploadingRef = useRef(false);
  queueRef.current = queue;
  const [canManage, setCanManage] = useState(false);
  const [previewItem, setPreviewItem] = useState<LibraryItem | null>(null);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(false);

  const loadItems = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await LibraryService.list({
        q: query.trim() || undefined,
        category,
        age_group: ageGroup,
        season,
        scene,
      });
      setItems((currentItems) => mergeLibraryItems(currentItems, data.items || []));
      setCanManage(Boolean(data.can_manage));
    } catch (error) {
      if (!silent) {
        notify.error("加载失败", error instanceof Error ? error.message : "无法加载素材库");
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, [ageGroup, category, query, scene, season]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  const pendingCovers = items.some(
    (item) =>
      item.preview_status === "pending" ||
      item.preview_status === "generating" ||
      isCoverPending(item),
  );
  const forcePollUntilRef = useRef(0);
  const shouldPollCovers = pendingCovers || Date.now() < forcePollUntilRef.current;

  useEffect(() => {
    if (!shouldPollCovers) return undefined;
    const timer = window.setInterval(() => {
      void loadItems(true);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [shouldPollCovers, loadItems]);

  const handleSelectFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    const pptxFiles = files.filter((file) => file.name.toLowerCase().endsWith(".pptx"));
    if (!pptxFiles.length) {
      notify.error("文件格式不正确", "请上传 .pptx 文件");
      return;
    }
    if (uploadingRef.current) {
      notify.warning("正在上传", "请等当前队列完成后再选新的文件");
      return;
    }
    const nextQueue: UploadQueueItem[] = pptxFiles.map((file, index) => {
      const guessed = guessLibraryTags(file.name);
      return {
        key: `${file.name}-${file.size}-${file.lastModified}-${index}`,
        file,
        title: guessed.title,
        category: guessed.category,
        age_group: guessed.age_group,
        season: guessed.season,
        scene: guessed.scene,
        status: "queued",
      };
    });
    queueRef.current = nextQueue;
    setQueue(nextQueue);
    setShowUpload(true);
    setUploadProgress(`已选 ${nextQueue.length} 个文件，正在保存原件`);
    void runUpload(nextQueue);
  };

  const updateQueueItem = (key: string, patch: Partial<UploadQueueItem>) => {
    setQueue((current) => {
      const next = current.map((item) => (item.key === key ? { ...item, ...patch } : item));
      queueRef.current = next;
      return next;
    });
  };

  const runUpload = async (list?: UploadQueueItem[]) => {
    const snapshot = list ?? queueRef.current;
    if (!snapshot.length) {
      notify.warning("请选择文件", "请先选择要上传的 PPTX");
      return;
    }
    if (uploadingRef.current) return;
    uploadingRef.current = true;
    setUploading(true);
    try {
      for (let index = 0; index < snapshot.length; index += 1) {
        const item = snapshot[index];
        const latest = queueRef.current.find((row) => row.key === item.key) || item;
        if (latest.status === "done") continue;
        setUploadProgress(`正在保存原件 ${index + 1}/${snapshot.length}：《${latest.title}》`);
        updateQueueItem(item.key, { status: "uploading", error: "" });
        try {
          const current = queueRef.current.find((row) => row.key === item.key) || latest;
          const created = await LibraryService.upload({
            file: current.file,
            title: current.title.trim() || current.file.name.replace(/\.pptx$/i, ""),
            category: current.category,
            age_group: current.age_group,
            season: current.season,
            scene: current.scene,
          });
          updateQueueItem(item.key, { status: "done" });
          forcePollUntilRef.current = Date.now() + 180000;
          if (created?.id) {
            setItems((currentItems) => {
              if (currentItems.some((row) => row.id === created.id)) {
                return currentItems.map((row) => (row.id === created.id ? { ...row, ...created } : row));
              }
              return [created, ...currentItems];
            });
          }
          void loadItems(true);
        } catch (error) {
          updateQueueItem(item.key, {
            status: "error",
            error: error instanceof Error ? error.message : "上传失败",
          });
        }
      }
      const succeeded = queueRef.current.filter((item) => item.status === "done").length;
      const failed = queueRef.current.filter((item) => item.status === "error").length;
      setUploadProgress(`完成：成功 ${succeeded} 个，失败 ${failed} 个。失败项可点「开始上传」重试。`);
      notify.success("批量上传完成", `成功 ${succeeded} 个，失败 ${failed} 个`);
      if (succeeded) {
        forcePollUntilRef.current = Date.now() + 180000;
        await loadItems(true);
      }
    } finally {
      uploadingRef.current = false;
      setUploading(false);
    }
  };

  const handleUpload = async () => {
    await runUpload();
  };

  const handleDownload = async (item: LibraryItem) => {
    setBusyId(item.id);
    try {
      await LibraryService.download(item.id, item.title);
    } catch (error) {
      notify.error("下载失败", error instanceof Error ? error.message : "请稍后重试");
    } finally {
      setBusyId(null);
    }
  };

  const handleEdit = async (item: LibraryItem) => {
    if (!item.editable) {
      notify.warning("暂不支持编辑", "该案例解析未完成，请直接下载原件");
      return;
    }
    setBusyId(item.id);
    try {
      const cloned = await LibraryService.cloneForEdit(item.id);
      if (!cloned.presentation_id) {
        throw new Error("未返回有效项目编号");
      }
      const params = new URLSearchParams();
      if (isTeachnovaEmbed()) params.set("embed", "teachnova");
      params.set("id", cloned.presentation_id);
      params.set("type", "standard");
      notify.success("已加入我的项目", "正在打开可编辑文稿");
      router.push(`/presentation?${params.toString()}`);
    } catch (error) {
      notify.error("无法打开编辑", error instanceof Error ? error.message : "请稍后重试");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (item: LibraryItem) => {
    if (!window.confirm(`确定删除「${item.title}」？这会删除素材库原件。`)) return;
    setBusyId(item.id);
    try {
      await LibraryService.remove(item.id);
      notify.success("已删除", "案例已从素材库移除");
      await loadItems();
    } catch (error) {
      notify.error("删除失败", error instanceof Error ? error.message : "请稍后重试");
    } finally {
      setBusyId(null);
    }
  };

  const previewSlides = previewItem?.slide_image_urls?.filter(Boolean) || [];

  const openPreview = async (item: LibraryItem) => {
    setPreviewItem(item);
    setPreviewIndex(0);
    const existing = item.slide_image_urls?.filter(Boolean) || [];
    setPreviewLoading(!existing.length);
    try {
      const detail = await LibraryService.get(item.id);
      setPreviewItem(detail);
      setItems((current) =>
        current.map((entry) => (entry.id === detail.id ? { ...entry, ...detail } : entry)),
      );
    } catch (error) {
      if (!existing.length) {
        notify.error("无法预览", error instanceof Error ? error.message : "请稍后重试");
        setPreviewItem(null);
      }
    } finally {
      setPreviewLoading(false);
    }
  };

  useEffect(() => {
    if (!previewItem || !isPreviewWaiting(previewItem)) return undefined;
    const itemId = previewItem.id;
    const timer = window.setInterval(() => {
      void LibraryService.get(itemId)
        .then((detail) => {
          setPreviewItem(detail);
          setItems((current) =>
            current.map((entry) => (entry.id === detail.id ? { ...entry, ...detail } : entry)),
          );
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [previewItem?.id, previewItem?.preview_status, previewSlides.length]);

  useEffect(() => {
    if (!previewItem) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewItem(null);
        return;
      }
      if (event.key === "ArrowRight") {
        setPreviewIndex((index) =>
          previewSlides.length ? (index + 1) % previewSlides.length : 0,
        );
      }
      if (event.key === "ArrowLeft") {
        setPreviewIndex((index) =>
          previewSlides.length ? (index - 1 + previewSlides.length) % previewSlides.length : 0,
        );
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [previewItem, previewSlides.length]);

  useEffect(() => {
    document.getElementById(`library-preview-thumb-${previewIndex}`)?.scrollIntoView({
      block: "nearest",
    });
  }, [previewIndex]);

  return (
    <div className="min-h-screen font-syne">
      <div className="sticky top-0 z-50 px-6 py-[28px] backdrop-blur">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 flex-col gap-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#7A5AF8]">
              Case Library
            </p>
            <h3 className="bg-[linear-gradient(105deg,#1F163B_0%,#5146E5_58%,#7A5AF8_100%)] bg-clip-text text-[28px] font-semibold tracking-[-0.04em] text-transparent">
              素材库
            </h3>
            <p className="text-sm text-[#667085]">
              点封面可浏览全部页。下载的是官方原件；点编辑会复制一份到你的项目，不会覆盖素材库文件。
            {canManage ? "" : " 仅管理员可以上传和维护案例。"}
            </p>
          </div>
          {canManage ? (
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-semibold text-black shadow-sm"
              style={{
                background:
                  "linear-gradient(270deg, #D5CAFC 2.4%, #E3D2EB 27.88%, #F4DCD3 69.23%, #FDE4C2 100%)",
              }}
            >
              <Upload className="h-4 w-4" />
              批量上传
            </button>
          ) : null}
          {canManage ? (
          <input
            ref={fileInputRef}
            type="file"
            accept=".pptx"
            multiple
            className="hidden"
            onChange={handleSelectFile}
          />
          ) : null}
        </div>
      </div>

      <div className="mx-auto px-6 py-6">
        <div className="mb-8 flex flex-wrap items-center gap-3">
          <label className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#98A2B3]" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索案例标题"
              className="h-10 w-full rounded-full border border-[#EDEEEF] bg-white pl-9 pr-4 text-sm outline-none focus:border-[#7A5AF8]"
            />
          </label>
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value as typeof category)}
            className="h-10 rounded-full border border-[#EDEEEF] bg-white px-3 text-sm"
          >
            {LIBRARY_CATEGORIES.map((item) => (
              <option key={item} value={item}>
                {item === "全部" ? "全部分类" : item}
              </option>
            ))}
          </select>
          <select
            value={ageGroup}
            onChange={(event) => setAgeGroup(event.target.value as typeof ageGroup)}
            className="h-10 rounded-full border border-[#EDEEEF] bg-white px-3 text-sm"
          >
            {LIBRARY_AGE_GROUPS.map((item) => (
              <option key={item} value={item}>
                {item === "全部" ? "全部班级" : item}
              </option>
            ))}
          </select>
          <select
            value={season}
            onChange={(event) => setSeason(event.target.value as typeof season)}
            className="h-10 rounded-full border border-[#EDEEEF] bg-white px-3 text-sm"
          >
            {LIBRARY_SEASONS.map((item) => (
              <option key={item} value={item}>
                {item === "全部" ? "全部学期" : item}
              </option>
            ))}
          </select>
          <select
            value={scene}
            onChange={(event) => setScene(event.target.value as typeof scene)}
            className="h-10 rounded-full border border-[#EDEEEF] bg-white px-3 text-sm"
          >
            {LIBRARY_SCENES.map((item) => (
              <option key={item} value={item}>
                {item === "全部" ? "全部课型" : item}
              </option>
            ))}
          </select>
        </div>

        {showUpload && canManage ? (
          <div className="mb-8 rounded-[22px] border border-[#EDEEEF] bg-white p-5">
            <div className="mb-1 text-sm font-semibold text-[#191919]">批量发布到素材库</div>
            <p className="mb-4 text-xs text-[#667085]">
              已识别班级、学期和课型，可逐条改。先保存原件，封面在后台生成，老师访问时只加载封面图，不会下载原 PPT。
              {uploadProgress ? ` 进度 ${uploadProgress}` : ""}
            </p>
            <div className="max-h-[360px] space-y-3 overflow-auto">
              {queue.map((item) => (
                <div
                  key={item.key}
                  className={`grid gap-2 rounded-xl border p-3 md:grid-cols-6 ${
                    item.status === "uploading"
                      ? "border-[#C9C6FF] bg-[#F7F6FF]"
                      : item.status === "done"
                        ? "border-[#B7E4C7] bg-[#F3FBF6]"
                        : item.status === "error"
                          ? "border-[#F3C0C0] bg-[#FFF6F6]"
                          : "border-[#EDEEEF]"
                  }`}
                >
                  <input
                    value={item.title}
                    onChange={(event) => updateQueueItem(item.key, { title: event.target.value })}
                    className="h-9 rounded-lg border border-[#EDEEEF] px-2 text-sm md:col-span-2"
                  />
                  <select className="h-9 rounded-lg border border-[#EDEEEF] px-2 text-sm" value={item.age_group} onChange={(event) => updateQueueItem(item.key, { age_group: event.target.value })}>
                    {LIBRARY_AGE_GROUPS.filter((value) => value !== "全部").map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                  <select className="h-9 rounded-lg border border-[#EDEEEF] px-2 text-sm" value={item.season} onChange={(event) => updateQueueItem(item.key, { season: event.target.value })}>
                    {LIBRARY_SEASONS.filter((value) => value !== "全部").map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                  <select className="h-9 rounded-lg border border-[#EDEEEF] px-2 text-sm" value={item.scene} onChange={(event) => updateQueueItem(item.key, { scene: event.target.value })}>
                    {LIBRARY_SCENES.filter((value) => value !== "全部").map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                  <div className="flex items-center text-xs text-[#667085]">
                    {item.status === "uploading" ? "正在保存原件…" : item.status === "done" ? "已进入素材库" : item.status === "error" ? item.error : "等待上传"}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                disabled={uploading}
                onClick={() => void handleUpload()}
                className="inline-flex h-10 items-center gap-2 rounded-full bg-[#7A5AF8] px-4 text-sm font-semibold text-white disabled:opacity-60"
              >
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                {uploading ? `正在保存 ${uploadProgress}` : `开始上传 ${queue.length} 个文件`}
              </button>
              <button
                type="button"
                onClick={() => {
                  if (uploading) return;
                  setShowUpload(false);
                  setQueue([]);
                }}
                className="h-10 rounded-full border border-[#EDEEEF] px-4 text-sm"
              >
                {queue.some((item) => item.status === "done") ? "完成" : "取消"}
              </button>
            </div>
          </div>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-20 text-sm text-[#667085]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中…
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-[22px] border border-dashed border-[#EDEEEF] py-16 text-center text-sm text-[#667085]">
            {canManage ? "还没有案例。点击右上角上传 PPTX。" : "暂无官方案例。"}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {items.map((item) => {
              const thumbnail = item.thumbnail ? resolveBackendAssetUrl(item.thumbnail) : "";
              const busy = busyId === item.id;
              const coverPending = isCoverPending(item);
              return (
                <article
                  key={item.id}
                  className="overflow-hidden rounded-[22px] border border-[#EDEEEF] bg-white"
                >
                  <button
                    type="button"
                    className="relative block aspect-video w-full overflow-hidden bg-[#F7F8FB] text-left"
                    onClick={() => void openPreview(item)}
                    title="查看全部页面"
                  >
                    {thumbnail ? (
                      <img
                        src={thumbnail}
                        alt={item.title}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <span className="flex h-full flex-col items-center justify-center gap-1 text-xs text-[#98A2B3]">
                        {coverPending ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            封面生成中
                          </>
                        ) : (
                          "点击查看课件"
                        )}
                      </span>
                    )}
                    {coverPending && thumbnail ? (
                      <span className="absolute inset-0 flex items-center justify-center bg-black/35 text-xs font-semibold text-white">
                        封面生成中
                      </span>
                    ) : null}
                    <span className="absolute bottom-2 right-2 rounded-full bg-black/55 px-2 py-0.5 text-[11px] font-semibold text-white">
                      {item.page_count || 0} 页
                    </span>
                  </button>
                  <div className="border-t border-[#EDEEEF] px-5 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h4
                          className="cursor-pointer truncate text-[15px] font-semibold text-[#191919] hover:text-[#7A5AF8]"
                          onClick={() => void openPreview(item)}
                        >
                          {item.title}
                        </h4>
                        <p className="mt-1 text-xs text-[#667085]">
                          {item.age_group} · {item.season || "不限"} · {item.scene || item.category} · {item.page_count || 0} 页 · 下载 {item.download_count}
                        </p>
                      </div>
                      {canManage ? (
                      <button
                        type="button"
                        className="text-[#D64545]"
                        title="删除案例原件"
                        onClick={() => void handleDelete(item)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                      ) : null}
                    </div>
                    <div className="mt-4 flex gap-2">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void handleDownload(item)}
                        className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-full border border-[#EDEEEF] text-xs font-semibold text-[#191919] disabled:opacity-60"
                      >
                        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                        下载原件
                      </button>
                      <button
                        type="button"
                        disabled={busy || !item.editable}
                        onClick={() => void handleEdit(item)}
                        className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-full bg-[#7A5AF8] text-xs font-semibold text-white disabled:opacity-50"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        加入我的项目
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>

      {previewItem ? (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-3 sm:p-5"
          onClick={() => setPreviewItem(null)}
        >
          <div
            className="flex h-[92vh] w-[min(1440px,96vw)] flex-col overflow-hidden rounded-[20px] bg-white shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-[#EDEEEF] px-5 py-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#F4F1FF] text-[#7A5AF8]">
                  <Presentation className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-[#191919]">{previewItem.title}</div>
                  <div className="text-xs text-[#667085]">
                    {previewItem.age_group} · {previewItem.category} · {previewItem.page_count || previewSlides.length} 页
                  </div>
                </div>
                <span className="shrink-0 rounded-md bg-[#5B8DEF] px-2 py-0.5 text-[11px] font-semibold text-white">
                  官方
                </span>
              </div>
              <button
                type="button"
                className="rounded-full p-1.5 text-[#667085] hover:bg-[#F7F8FB]"
                onClick={() => setPreviewItem(null)}
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="flex min-h-0 flex-1">
              {previewSlides.length ? (
                <aside className="flex w-[240px] shrink-0 flex-col border-r border-[#EDEEEF] bg-[#F7F8FB]">
                  <div className="overflow-y-auto px-3 py-3">
                    {previewSlides.map((url, index) => {
                      const active = index === previewIndex;
                      return (
                        <button
                          key={`${url}-${index}`}
                          id={`library-preview-thumb-${index}`}
                          type="button"
                          className="mb-2 flex w-full items-start gap-2 text-left last:mb-0"
                          onClick={() => setPreviewIndex(index)}
                        >
                          <span
                            className={`w-4 shrink-0 pt-6 text-right text-[11px] font-medium ${
                              active ? "text-[#7A5AF8]" : "text-[#98A2B3]"
                            }`}
                          >
                            {index + 1}
                          </span>
                          <span
                            className={`block flex-1 overflow-hidden rounded-md border-2 ${
                              active ? "border-[#7A5AF8] shadow-[0_0_0_2px_rgba(122,90,248,0.18)]" : "border-[#EDEEEF]"
                            }`}
                          >
                            <img
                              src={resolveBackendAssetUrl(url)}
                              alt={`第 ${index + 1} 页`}
                              className="aspect-video w-full bg-white object-cover"
                            />
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </aside>
              ) : null}
              <div className="relative flex min-w-0 flex-1 items-center justify-center bg-white p-5">
                {previewLoading ? (
                  <div className="flex items-center text-sm text-[#667085]">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    正在按源文件生成预览…
                  </div>
                ) : previewSlides.length ? (
                  <>
                    <img
                      src={resolveBackendAssetUrl(previewSlides[previewIndex])}
                      alt={`${previewItem.title} 第 ${previewIndex + 1} 页`}
                      className="max-h-full max-w-full object-contain shadow-[0_8px_28px_rgba(16,24,40,0.08)]"
                    />
                    {previewItem.preview_status === "generating" ? (
                      <div className="absolute top-5 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full bg-black/65 px-3 py-1 text-xs text-white">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        正在按源文件重新截图
                      </div>
                    ) : null}
                    {previewSlides.length > 1 ? (
                      <div className="absolute bottom-5 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full border border-[#EDEEEF] bg-white px-2 py-1 text-[#191919] shadow-sm">
                        <button
                          type="button"
                          className="rounded-full p-1.5 hover:bg-[#F7F8FB]"
                          onClick={() =>
                            setPreviewIndex(
                              (index) => (index - 1 + previewSlides.length) % previewSlides.length,
                            )
                          }
                        >
                          <ChevronLeft className="h-4 w-4" />
                        </button>
                        <span className="min-w-[52px] text-center text-xs font-medium">
                          {previewIndex + 1} / {previewSlides.length}
                        </span>
                        <button
                          type="button"
                          className="rounded-full p-1.5 hover:bg-[#F7F8FB]"
                          onClick={() =>
                            setPreviewIndex((index) => (index + 1) % previewSlides.length)
                          }
                        >
                          <ChevronRight className="h-4 w-4" />
                        </button>
                      </div>
                    ) : (
                      <div className="absolute bottom-5 left-1/2 -translate-x-1/2 rounded-full border border-[#EDEEEF] bg-white px-3 py-1 text-xs text-[#191919] shadow-sm">
                        1 / 1
                      </div>
                    )}
                  </>
                ) : previewLoading || isPreviewWaiting(previewItem) ? (
                  <div className="flex items-center text-sm text-[#667085]">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    正在生成预览…
                  </div>
                ) : (
                  <div className="text-sm text-[#667085]">暂无页面预览，请直接下载原件</div>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
