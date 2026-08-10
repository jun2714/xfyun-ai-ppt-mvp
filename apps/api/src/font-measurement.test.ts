import assert from "node:assert/strict";
import test from "node:test";
import { FontkitTextMeasurerAdapter } from "./infrastructure/typography/fontkit-text-measurer.adapter.js";

test("installed-font measurement wraps deterministically at the supplied width", () => {
  const measurer = new FontkitTextMeasurerAdapter();
  const input = { text: "真实字体测量必须识别一行放不下的内容", fontFamily: "Microsoft YaHei", fontSize: 24, fontWeight: 400, maxWidth: 120, lineHeight: 1.2 };
  const first = measurer.measure(input);
  const second = measurer.measure(input);
  assert.deepEqual(first, second);
  assert.ok(first.lines > 1);
  assert.ok(first.height > input.fontSize * input.lineHeight);
});
