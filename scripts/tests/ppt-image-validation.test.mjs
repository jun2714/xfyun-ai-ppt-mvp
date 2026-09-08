import assert from "node:assert/strict";
import test from "node:test";
import {
  collectEmptyVisualCards,
  collectClassroomMappingErrors,
  collectUnreadableAudienceText,
  collectUnresolvedImageSlots,
} from "../lib/ppt-image-validation.mjs";

test("classroom audit catches a correct caption paired with the wrong image prompt", () => {
  const text = (name, value) => ({ type: "text", name, runs: [{ text: value }] });
  const slide = {
    layout: "classroom_cards_2",
    content: {
      __content_contract__: { classroom_mapping_version: 1, screen_title: "观察春天",
        screen_points: ["太阳暖暖的"], screen_instruction: "",
        asset_contracts: [{ audience_text: "太阳暖暖的", semantic_label: "暖暖太阳" }] },
      card_0: { visual: { image_prompt: "雨滴落下" } },
    },
    ui: { components: [
      { id: "heading", elements: [text("title", "观察春天")] },
      { id: "invitation", elements: [text("cue", "")] },
      { id: "card_0", elements: [text("text", "太阳暖暖的")] },
    ] },
  };
  assert.match(collectClassroomMappingErrors(slide, 1).join(""), /semantic binding/);
  slide.content.card_0.visual.image_prompt = "暖暖太阳";
  assert.deepEqual(collectClassroomMappingErrors(slide, 1), []);
  slide.ui.components[0].elements[0].runs[0].text = "标题被放错了";
  assert.match(collectClassroomMappingErrors(slide, 1).join(""), /heading/);
});

test("empty image cards are also detected in component element arrays", () => {
  const card = { id: "card_0", elements: [
    { type: "image", data: "/app_data/images/a.png", decorative: false },
    { type: "text", decorative: false, runs: [] },
  ] };
  assert.equal(collectEmptyVisualCards(card, 1).length, 1);
});

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


test("rejects projected preschool copy below eighteen pixels", () => {
  const result = collectUnreadableAudienceText([
    { type: "text", decorative: false, font: { size: 17 }, runs: [{ text: "太小了", font: { size: 17 } }] },
    { type: "text", decorative: false, font: { size: 18 }, runs: [{ text: "可以阅读", font: { size: 18 } }] },
    { type: "text", decorative: false, font: { size: 14 }, runs: [] },
  ], 2);
  assert.deepEqual(result.map((item) => item.text), ["太小了"]);
});

test("rejects an image card whose audience labels are all empty", () => {
  const empty = {
    type: "group",
    name: "third-card",
    children: [
      { type: "image", decorative: false, data: "/app_data/images/real.png" },
      { type: "text", decorative: false, runs: [] },
      { type: "text", decorative: false, runs: [{ text: "" }] },
    ],
  };
  const filled = {
    ...empty,
    children: [
      empty.children[0],
      { type: "text", decorative: false, runs: [{ text: "等待发芽" }] },
    ],
  };
  assert.equal(collectEmptyVisualCards([empty, filled], 8).length, 1);
});
