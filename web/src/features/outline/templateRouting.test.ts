import { describe, expect, it } from "vitest";
import type { Presentation, PresentationOutline, TemplateItem } from "../../entities/types";
import { resolveAutoTemplateId } from "./templateRouting";

function presentation(title: string, content = ""): Presentation {
  return {
    id: "presentation-1",
    title,
    content,
    n_slides: 1,
    language: "zh-CN",
    created_at: "2026-08-27T00:00:00Z",
    updated_at: "2026-08-27T00:00:00Z",
    slides: [],
  };
}

function outline(...contents: string[]): PresentationOutline {
  return { slides: contents.map((content) => ({ content })) };
}

function template(
  id: string,
  routingTerms: string[],
  options: {
    priority?: number;
    fallback?: boolean;
    isDefault?: boolean;
    audiences?: string[];
  } = {},
): TemplateItem {
  return {
    id,
    name: id,
    layout_count: 8,
    is_default: options.isDefault ?? true,
    routing_metadata: {
      auto_match: true,
      auto_priority: options.priority ?? 50,
      fallback: options.fallback ?? false,
      routing_terms: routingTerms,
      ...(options.audiences ? { audiences: options.audiences } : {}),
    },
  };
}

const builtins = [
  template("dynamic", ["科学", "植物", "观察"], { priority: 20 }),
  template("modern", ["绘本", "故事"], { priority: 30 }),
  template("swift", ["游戏", "互动"], { priority: 40 }),
  template("momentum", ["亲子", "音乐", "端午"], { priority: 50 }),
  template("standard", ["安全", "礼仪"], { priority: 60, fallback: true }),
  template("executive", ["家长会", "教研"], {
    priority: 10,
    audiences: ["adult"],
  }),
];

describe("resolveAutoTemplateId", () => {
  it("matches a science lesson to its tagged template", () => {
    expect(
      resolveAutoTemplateId(
        presentation("认识植物朋友"),
        outline("活动目标", "观察植物的叶子"),
        builtins,
      ),
    ).toBe("dynamic");
  });

  it("does not treat generic activity wording as a template signal", () => {
    expect(
      resolveAutoTemplateId(
        presentation("我的幼儿园"),
        outline("活动目标", "活动准备", "活动过程"),
        builtins,
      ),
    ).toBe("standard");
  });

  it("weights the reviewed topic more strongly than incidental outline text", () => {
    expect(
      resolveAutoTemplateId(
        presentation("科学主题家长会"),
        outline("分享孩子的观察记录"),
        builtins,
      ),
    ).toBe("executive");
  });

  it("does not automatically select a personal template", () => {
    const custom = template("custom-story", ["绘本"], {
      priority: 1,
      isDefault: false,
    });

    expect(
      resolveAutoTemplateId(
        presentation("绘本故事"),
        outline("故事内容"),
        [custom, ...builtins],
      ),
    ).toBe("modern");
  });

  it("keeps the legacy general fallback before metadata is imported", () => {
    expect(
      resolveAutoTemplateId(
        presentation("未分类课件"),
        outline("普通内容"),
        [{ id: "general", name: "基础通用", layout_count: 1, is_default: true }],
      ),
    ).toBe("general");
  });
});
