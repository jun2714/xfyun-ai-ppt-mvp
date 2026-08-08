import assert from "node:assert/strict";
import test from "node:test";
import { buildApp } from "./app.js";

test("zero baseline exposes only health in production", async () => {
  const previous = process.env.NODE_ENV;
  process.env.NODE_ENV = "production";
  const app = buildApp();
  const health = await app.inject({ method: "GET", url: "/api/v1/health" });
  const removedRoute = await app.inject({ method: "GET", url: "/api/v1/projects" });
  assert.equal(health.statusCode, 200);
  assert.equal(removedRoute.statusCode, 404);
  await app.close();
  if (previous === undefined) delete process.env.NODE_ENV;
  else process.env.NODE_ENV = previous;
});
