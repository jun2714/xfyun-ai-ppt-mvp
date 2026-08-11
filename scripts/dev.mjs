import { spawn } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
// Teachnova owns the product entry and flow; Presenton runs only as the
// template/editor/export engine behind it.
const commands = [
  ["pnpm", ["run", "dev:web"]],
  ["node", ["scripts/dev-engine.mjs"]]
];
const children = commands.map(([command, args]) => spawn(command, args, { cwd: root, stdio: "inherit", shell: process.platform === "win32" }));
const stop = () => children.forEach((child) => child.kill());
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
const exitCode = await Promise.race(children.map((child) => new Promise((done) => child.once("exit", (code) => done(code ?? 1)))));
stop();
process.exit(exitCode);
