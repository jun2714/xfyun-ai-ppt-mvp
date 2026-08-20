/**
 * 生产构建编辑器：读取根目录 .env / .env.production，注入 NEXT_PUBLIC_* 后 next build
 * 用法：node scripts/build-editor-prod.mjs
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const editor = resolve(root, "engine/editor");

function parseEnv(file) {
  if (!existsSync(file)) return {};
  return Object.fromEntries(
    readFileSync(file, "utf8")
      .split(/\r?\n/)
      .filter((line) => line && !line.trimStart().startsWith("#") && line.includes("="))
      .map((line) => {
        const i = line.indexOf("=");
        return [line.slice(0, i).trim(), line.slice(i + 1).trim()];
      }),
  );
}

const fileEnv = {
  ...parseEnv(resolve(root, ".env")),
  ...parseEnv(resolve(root, ".env.production")),
};

const env = {
  ...process.env,
  ...fileEnv,
  NODE_ENV: "production",
  NEXT_PUBLIC_URL: fileEnv.NEXT_PUBLIC_URL || process.env.NEXT_PUBLIC_URL || "https://ppt.teachnova.com",
  NEXT_PUBLIC_FAST_API:
    fileEnv.NEXT_PUBLIC_FAST_API || process.env.NEXT_PUBLIC_FAST_API || "https://teachnova.com/ppt-api",
  FAST_API_INTERNAL_URL: fileEnv.FAST_API_INTERNAL_URL || "http://127.0.0.1:8000",
  CAN_CHANGE_KEYS: "false",
};

console.log("[build-editor-prod] NEXT_PUBLIC_URL =", env.NEXT_PUBLIC_URL);
console.log("[build-editor-prod] NEXT_PUBLIC_FAST_API =", env.NEXT_PUBLIC_FAST_API);
console.log("[build-editor-prod] NEXT_PUBLIC_WEB_APP_URL =", env.NEXT_PUBLIC_WEB_APP_URL || "(default http://127.0.0.1:5173)");

const child = spawn("npm", ["run", "build"], {
  cwd: editor,
  env,
  stdio: "inherit",
  shell: process.platform === "win32",
});

child.on("exit", (code) => process.exit(code ?? 1));
