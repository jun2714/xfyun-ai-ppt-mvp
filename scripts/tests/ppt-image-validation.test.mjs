import assert from "node:assert/strict";
import test from "node:test";
import { collectUnresolvedImageSlots } from "../lib/ppt-image-validation.mjs";

test("one successful image cannot conceal a remaining black placeholder", () => {
  const slots = [
    { type: "image", data: "http://localhost:18000/static/images/placeholder.jpg" },
    { type: "image", data: "http://localhost:18000/app_data/images/real.png" },
  ];
  const failures = collectUnresolvedImageSlots(slots, 8, "ui");
  assert.equal(failures.length, 1);
  assert.equal(failures[0].page, 8);
  assert.deepEqual(failures[0].path, ["0"]);
});

test("checks legacy and template content fields including empty URLs", () => {
  assert.equal(collectUnresolvedImageSlots({
    first: { image_url: "" },
    second: { __image_url__: "/static/images/placeholder.jpg" },
    third: { image_url: "/app_data/images/real.png" },
  }, 1, "content").length, 2);
});

test("rejects a missing UI image without treating icons as generated pictures", () => {
  assert.equal(collectUnresolvedImageSlots([
    { type: "image", required: true },
    { type: "image", is_icon: true, data: "/static/icons/placeholder.svg" },
  ], 1, "ui").length, 1);
});
