import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";
import { NextRequest } from "next/server.js";

const editorRoot = process.cwd();

async function bundleModule(entryPoint) {
  // Keep the temporary bundle under the editor package so Node can resolve
  // package exports such as next/server.js from the package's node_modules.
  const directory = await mkdtemp(path.join(editorRoot, ".test-build-"));
  const outfile = path.join(directory, "module.mjs");
  await build({
    entryPoints: [path.join(editorRoot, entryPoint)],
    outfile,
    bundle: true,
    format: "esm",
    platform: "node",
    target: "node20",
    tsconfig: path.join(editorRoot, "tsconfig.json"),
    alias: { "next/server": "next/server.js" },
    external: ["next/server.js"],
    logLevel: "silent",
  });
  return {
    module: await import(`${pathToFileURL(outfile).href}?v=${Date.now()}`),
    dispose: () => rm(directory, { recursive: true, force: true }),
  };
}

test("server auth accepts local requests when authentication is disabled", async () => {
  const original = process.env.DISABLE_AUTH;
  process.env.DISABLE_AUTH = "true";
  const bundled = await bundleModule("lib/server-auth-role.ts");
  try {
    const status = await bundled.module.authStatusForRequest(
      new Request("http://127.0.0.1/api/export-presentation")
    );
    assert.equal(status.authenticated, true);
    assert.equal(status.role, "admin");
  } finally {
    if (original === undefined) delete process.env.DISABLE_AUTH;
    else process.env.DISABLE_AUTH = original;
    await bundled.dispose();
  }
});

test("export data route does not require a cookie in disabled-auth mode", async () => {
  const originalAuth = process.env.DISABLE_AUTH;
  const originalApi = process.env.FAST_API_INTERNAL_URL;
  const originalFetch = globalThis.fetch;
  process.env.DISABLE_AUTH = "true";
  process.env.FAST_API_INTERNAL_URL = "http://127.0.0.1:8000";
  let forwardedHeaders;
  globalThis.fetch = async (_url, init) => {
    forwardedHeaders = init?.headers;
    return new Response(JSON.stringify({ id: "presentation-id" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const bundled = await bundleModule(
    "app/api/export-presentation-data/[id]/route.ts"
  );
  try {
    const response = await bundled.module.GET(
      new NextRequest("http://127.0.0.1/api/export-presentation-data/presentation-id"),
      { params: Promise.resolve({ id: "presentation-id" }) }
    );
    assert.equal(response.status, 200);
    assert.equal(forwardedHeaders, undefined);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalAuth === undefined) delete process.env.DISABLE_AUTH;
    else process.env.DISABLE_AUTH = originalAuth;
    if (originalApi === undefined) delete process.env.FAST_API_INTERNAL_URL;
    else process.env.FAST_API_INTERNAL_URL = originalApi;
    await bundled.dispose();
  }
});

test("bundled export runtime is detected on Windows", async (context) => {
  if (process.platform !== "win32" || process.arch !== "x64") {
    context.skip("Windows x64 runtime check");
    return;
  }

  const originalRoot = process.env.EXPORT_PACKAGE_ROOT;
  process.env.EXPORT_PACKAGE_ROOT = path.resolve(editorRoot, "..", "export", "runtime");
  const bundled = await bundleModule("lib/run-bundled-presentation-export.ts");
  try {
    assert.equal(await bundled.module.bundledExportPackageAvailable(), true);
  } finally {
    if (originalRoot === undefined) delete process.env.EXPORT_PACKAGE_ROOT;
    else process.env.EXPORT_PACKAGE_ROOT = originalRoot;
    await bundled.dispose();
  }
});
