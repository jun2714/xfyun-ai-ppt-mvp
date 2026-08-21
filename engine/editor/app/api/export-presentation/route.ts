import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

import {
  BundledPresentationExportFormat,
  bundledExportPackageAvailable,
  runBundledPresentationExport,
} from "@/lib/run-bundled-presentation-export";
import { authStatusForRequest } from "@/lib/server-auth-role";

function isValidFormat(value: unknown): value is BundledPresentationExportFormat {
  return value === "pdf" || value === "pptx";
}

async function readExportRequestBody(req: NextRequest): Promise<{
  format?: unknown;
  id?: unknown;
  title?: unknown;
}> {
  const rawBody = await req.text();
  if (!rawBody.trim()) {
    throw new Error("EMPTY_BODY");
  }

  const parsed = JSON.parse(rawBody) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("INVALID_BODY");
  }

  return parsed as { format?: unknown; id?: unknown; title?: unknown };
}

function buildExportDownloadUrl(outPath: string): string {
  const appDataDirectory = process.env.APP_DATA_DIRECTORY?.trim();
  if (!appDataDirectory) {
    throw new Error("APP_DATA_DIRECTORY is required to download exported files.");
  }

  const exportsDirectory = path.join(appDataDirectory, "exports");
  const relativePath = path.relative(exportsDirectory, outPath);
  if (
    !relativePath ||
    relativePath.startsWith("..") ||
    path.isAbsolute(relativePath)
  ) {
    throw new Error("Export finished outside the configured exports directory.");
  }

  return `/api/export-presentation/file?name=${encodeURIComponent(relativePath)}`;
}

function fastApiBase(): string {
  return (
    process.env.FAST_API_INTERNAL_URL?.trim() ||
    process.env.NEXT_PUBLIC_FAST_API?.trim() ||
    "http://127.0.0.1:8000"
  ).replace(/\/+$/, "");
}

async function persistExportToOss(
  outPath: string,
  cookie: string | null
): Promise<string | null> {
  try {
    const response = await fetch(`${fastApiBase()}/api/v1/ppt/oss/persist-export`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(cookie ? { cookie } : {}),
      },
      body: JSON.stringify({ path: outPath }),
      cache: "no-store",
    });
    if (!response.ok) {
      return null;
    }
    const data = (await response.json()) as { enabled?: boolean; url?: string | null };
    if (data.enabled && data.url) {
      return data.url;
    }
  } catch (error) {
    console.warn("[export-presentation] OSS persist skipped", error);
  }
  return null;
}

async function moveExportIntoOwnerDirectory(
  outPath: string,
  userId: string | null
): Promise<string> {
  if (!userId) {
    return outPath;
  }

  const appDataDirectory = process.env.APP_DATA_DIRECTORY?.trim();
  if (!appDataDirectory) {
    throw new Error("APP_DATA_DIRECTORY is required to scope exported files.");
  }

  const exportsDirectory = await fs.realpath(
    path.join(appDataDirectory, "exports")
  );
  const sourcePath = await fs.realpath(outPath);
  const ownerDirectory = path.join(exportsDirectory, "users", userId);
  await fs.mkdir(ownerDirectory, { recursive: true });

  const sourceParent = path.dirname(sourcePath);
  if (sourceParent === ownerDirectory) {
    return sourcePath;
  }
  if (sourceParent !== exportsDirectory) {
    throw new Error("Export finished outside the current user's export directory.");
  }

  const destination = path.join(ownerDirectory, path.basename(sourcePath));
  await fs.rename(sourcePath, destination);
  return destination;
}

export async function POST(req: NextRequest) {
  const auth = await authStatusForRequest(req);
  if (!auth.authenticated) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  let body: Awaited<ReturnType<typeof readExportRequestBody>>;
  try {
    body = await readExportRequestBody(req);
  } catch (error) {
    if (
      error instanceof SyntaxError ||
      (error instanceof Error &&
        (error.message === "EMPTY_BODY" || error.message === "INVALID_BODY"))
    ) {
      return NextResponse.json(
        { error: "Invalid export request JSON body" },
        { status: 400 }
      );
    }
    throw error;
  }

  const { format, id, title } = body;
  if (typeof id !== "string" || !id.trim()) {
    return NextResponse.json(
      { error: "Missing Presentation ID" },
      { status: 400 }
    );
  }

  if (!isValidFormat(format)) {
    return NextResponse.json(
      { error: "Invalid export format" },
      { status: 400 }
    );
  }

  try {
    if (!(await bundledExportPackageAvailable())) {
      throw new Error(
        "presentation-export runtime is not available. Run scripts/sync-presentation-export.cjs to install it."
      );
    }

    const presentationId = id.trim();

    const { path: unscopedOutPath } = await runBundledPresentationExport({
      format,
      presentationId,
      title: typeof title === "string" ? title : undefined,
      cookieHeader: req.headers.get("cookie") ?? "",
    });
    const outPath = await moveExportIntoOwnerDirectory(
      unscopedOutPath,
      auth.user_id
    );

    const ossUrl = await persistExportToOss(outPath, req.headers.get("cookie"));
    return NextResponse.json({
      success: true,
      path: ossUrl || buildExportDownloadUrl(outPath),
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    console.error(`[export-presentation:${format}]`, message);
    return NextResponse.json(
      { error: message, success: false },
      { status: 500 }
    );
  }
}
