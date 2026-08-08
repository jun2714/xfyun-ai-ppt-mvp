import assert from "node:assert/strict";
import test from "node:test";
import { buildApp } from "./app.js";

test("007 baseline exposes health and presentation resources", async () => {
  const previous = process.env.NODE_ENV;
  process.env.NODE_ENV = "production";
  const app = buildApp();
  const health = await app.inject({ method: "GET", url: "/api/v1/health" });
  const presentations = await app.inject({ method: "GET", url: "/api/v1/presentations" });
  assert.equal(health.statusCode, 200);
  assert.equal(presentations.statusCode, 200);
  await app.close();
  if (previous === undefined) delete process.env.NODE_ENV;
  else process.env.NODE_ENV = previous;
});
