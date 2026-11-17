const ERROR_TEXT: Record<number, string> = {
  400: "提交的内容有误，请检查后重试。", 401: "当前操作未获得授权。",
  403: "当前操作没有权限。", 404: "请求的项目不存在。",
  409: "项目状态已变化，请刷新后重试。", 422: "生成内容不符合页面要求，请修改后重试。",
  429: "请求过于频繁，请稍后重试。", 500: "生成服务暂时不可用，请稍后重试。",
  502: "模型服务暂时不可用，请稍后重试。", 503: "生成服务尚未启动，请稍后重试。",
  504: "服务响应超时，请确认当前状态后再继续。",
};

export function localizeError(value: unknown, status?: number): string {
  const message = value instanceof Error ? value.message : String(value ?? "");
  if (/[\u3400-\u9fff]/.test(message)) return message;
  if (/template layout not found|template not found/i.test(message)) {
    return "所选模板当前不可用，请重新选择模板；若内置模板全部缺失，请重启生成服务以重新加载模板。";
  }
  if (/presentation not found/i.test(message)) return "当前演示文稿不存在或还未保存完成，请刷新大纲页后重试。";
  if (/failed to fetch|networkerror|network error/i.test(message)) return "无法连接生成服务，请确认服务已启动。";
  if (/timed? out|timeout/i.test(message)) return "服务响应超时，请确认当前状态后再继续。";
  if (/abort/i.test(message)) return "本次请求已取消。";
  return (status && ERROR_TEXT[status]) || "操作失败，请稍后重试。";
}

export function errorMessage(body: unknown, status: number, fallback: string): string {
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return localizeError(detail, status);
    if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
      return localizeError(detail.message, status);
    }
  }
  return localizeError(fallback, status);
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
