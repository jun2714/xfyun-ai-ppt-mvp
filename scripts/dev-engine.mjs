import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const parseEnv = (file) => Object.fromEntries(
  existsSync(file)
    ? readFileSync(file, "utf8").split(/\r?\n/).filter((line) => line && !line.trimStart().startsWith("#") && line.includes("=")).map((line) => {
        const split = line.indexOf("=");
        return [line.slice(0, split).trim(), line.slice(split + 1).trim()];
      })
    : []
);
const source = { ...parseEnv(resolve(root, ".env")), ...process.env };
const dataDirectory = resolve(root, source.ENGINE_DATA_DIRECTORY || ".data/engine");
const shared = {
  ...source,
  PYTHONDONTWRITEBYTECODE: "1",
  APP_DATA_DIRECTORY: dataDirectory,
  DISABLE_AUTH: "true",
  CAN_CHANGE_KEYS: "false",
  LLM: "custom",
  CUSTOM_LLM_URL: source.DMX_API_BASE_URL || "https://www.dmxapi.cn/v1",
  CUSTOM_LLM_API_KEY: source.DMX_API_KEY || "",
  CUSTOM_MODEL: source.DMX_TEXT_MODEL || "",
  IMAGE_PROVIDER: source.DMX_IMAGE_API_STYLE === "gemini" ? "gemini_flash" : "openai_compatible",
  GOOGLE_API_KEY: source.DMX_API_KEY || "",
  GEMINI_IMAGE_BASE_URL: source.DMX_GEMINI_BASE_URL || "https://www.dmxapi.cn",
  GEMINI_IMAGE_MODEL: source.DMX_IMAGE_MODEL || "gemini-2.5-flash-image",
  OPENAI_COMPAT_IMAGE_BASE_URL: source.DMX_API_BASE_URL || "https://www.dmxapi.cn/v1",
  OPENAI_COMPAT_IMAGE_API_KEY: source.DMX_API_KEY || "",
  OPENAI_COMPAT_IMAGE_MODEL: source.DMX_IMAGE_MODEL || "",
  ENGINE_MAX_SCHEMA_RETRIES: source.ENGINE_MAX_SCHEMA_RETRIES || "1",
  NEXT_PUBLIC_FAST_API: "http://127.0.0.1:8000",
  FAST_API_INTERNAL_URL: "http://127.0.0.1:8000",
  NEXT_PUBLIC_URL: "http://127.0.0.1:5001",
  EXPORT_PACKAGE_ROOT: resolve(root, "engine/export/runtime"),
  NODE_PATH: resolve(root, "engine/editor/node_modules")
};

const children = [
  spawn("python", ["-m", "uv", "run", "python", "server.py", "--port", "8000", "--reload", "false"], { cwd: resolve(root, "engine/api"), env: shared, stdio: "inherit", shell: process.platform === "win32" }),
  spawn("npm", ["run", "dev", "--", "-p", "5001"], { cwd: resolve(root, "engine/editor"), env: shared, stdio: "inherit", shell: process.platform === "win32" })
];

const stop = () => children.forEach((child) => child.kill());
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
const exitCode = await Promise.race(children.map((child) => new Promise((done) => child.once("exit", (code) => done(code ?? 1)))));
stop();
process.exit(exitCode);
