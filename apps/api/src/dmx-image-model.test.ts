import assert from "node:assert/strict";
import test from "node:test";
import { DmxImageModelAdapter } from "./infrastructure/dmx/dmx-image-model.adapter.js";
import { DmxAuth } from "./infrastructure/dmx/dmx-auth.js";
import type { JsonHttpClient } from "./infrastructure/http/json-http-client.js";

test("qwen-image-2.0 uses DMX responses API and preserves requested landscape size", async () => {
  let call: { url: string; body: unknown } | undefined;
  const http = { post: async (url: string, _headers: Record<string, string>, body: unknown) => {
    call = { url, body };
    return { output: [{ type: "message", content: [{ type: "image", text: "https://example.com/generated.png" }] }] };
  } } as unknown as JsonHttpClient;
  const result = await new DmxImageModelAdapter(http, new DmxAuth("test-key"), "https://www.dmxapi.cn/v1", "qwen-image-2.0").generate({ prompt: "幼儿园春天插画", size: "1536x1024" });
  assert.equal(call?.url, "https://www.dmxapi.cn/v1/responses");
  assert.equal((call?.body as { input: { parameters: { size: string } } }).input.parameters.size, "1536*1024");
  assert.equal(result.url, "https://example.com/generated.png");
});
