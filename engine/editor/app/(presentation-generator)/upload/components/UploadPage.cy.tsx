import React from "react";
import UploadPage from "./UploadPage";
import { mount } from "cypress/react";
import { store } from "@/store/store";
import { Provider } from "react-redux";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { Toaster } from "@/components/ui/sonner";

import "@/app/globals.css";

const createRouter = (push = cy.stub().as("router.push")) => ({
  push,
  back: cy.stub(),
  forward: cy.stub(),
  refresh: cy.stub(),
  replace: cy.stub(),
  prefetch: cy.stub(),
  route: "/",
  pathname: "/",
  query: {},
  asPath: "/",
});

interface RouterWrapperProps {
  children: React.ReactNode;
}

Cypress.Commands.add("mount", (component, options = {}) => {
  const router = createRouter();
  const RouterWrapper = ({ children }: RouterWrapperProps) => (
    <AppRouterContext.Provider value={router}>
      <Provider store={store}>
        {children}
        <Toaster position="top-center" />
      </Provider>
    </AppRouterContext.Provider>
  );

  return mount(<RouterWrapper>{component}</RouterWrapper>, options);
});

const kindergartenResponse = (overrides: Record<string, unknown> = {}) => ({
  presentation_id: "test-id",
  outline_path: "/presentations/test-id/outline",
  selected_template: "standard",
  template_selection_reason: "domain:health+9",
  template_scores: { standard: 9 },
  visual_mode: "template",
  visual_style_summary: null,
  planning_attempts: 1,
  quality: { passed: true, errors: [], warnings: [] },
  outline: { slides: [{ content: "# 测试", content_contract: null }] },
  plan: {
    meta: {
      topic: "测试",
      age_group: "4-5岁",
      domain: "comprehensive",
      duration_minutes: 20,
    },
    lesson_goals: ["参与课堂活动"],
    lesson_arc: ["观察", "互动"],
    slides: [],
  },
  ...overrides,
});

const checkToast = (message: string) => {
  cy.get("[data-sonner-toast]", { timeout: 5000 }).should("contain", message);
};

describe("<UploadPage /> kindergarten creation", () => {
  beforeEach(() => {
    cy.viewport(1440, 900);
    cy.intercept("POST", "**/ppt/kindergarten/presentation/create", {
      statusCode: 200,
      body: kindergartenResponse(),
    }).as("createKindergartenPresentation");

    cy.on("window:before:load", (win) => {
      cy.stub(win.location, "assign").as("locationAssign");
    });

    cy.mount(<UploadPage />);
  });

  it("keeps the teacher-facing configuration controls usable", () => {
    cy.get('[data-testid="slides-select"]').click({ force: true });
    cy.get('[role="option"]').contains("12").click();
    cy.get('[data-testid="slides-select"]').should("contain", "12");

    cy.get('[data-testid="prompt-input"]').type("春天里的种子");
    cy.get('[data-testid="prompt-input"]').should("have.value", "春天里的种子");
  });

  it("sends template mode through the kindergarten planner", () => {
    cy.get('[data-testid="prompt-input"]').type("洗手好习惯");
    cy.contains("button", "智能模板").click();
    cy.contains("button", "Get Started").click();

    cy.wait("@createKindergartenPresentation")
      .its("request.body")
      .should("include", {
        topic: "洗手好习惯",
        age_group: "4-5岁",
        visual_mode: "template",
        template: "auto",
        language: "Chinese",
      });

    cy.get("@locationAssign").should(
      "be.calledWithMatch",
      /\/presentations\/test-id\/outline\?mode=topic.*template=standard/,
    );
  });

  it("sends AI free visual mode and carries the visual preference", () => {
    cy.intercept("POST", "**/ppt/kindergarten/presentation/create", {
      statusCode: 200,
      body: kindergartenResponse({
        selected_template: "ai-visual",
        template_selection_reason:
          "visual-mode:ai-background;neutral-skeleton+generated-backgrounds",
        template_scores: { "ai-visual": 100 },
        visual_mode: "ai-background",
        visual_style_summary: "清新自然儿童绘本插画",
      }),
    }).as("createAiVisualPresentation");

    cy.get('[data-testid="prompt-input"]').type("森林动物大冒险");
    cy.contains("button", "AI 自由视觉").click();
    cy.contains("button", "Get Started").click();

    cy.wait("@createAiVisualPresentation")
      .its("request.body")
      .should("include", {
        topic: "森林动物大冒险",
        visual_mode: "ai-background",
        visual_style: "明亮童趣",
        image_policy: "standard",
      });

    cy.get("@locationAssign").should(
      "be.calledWithMatch",
      /\/presentations\/test-id\/outline\?mode=topic.*template=ai-visual/,
    );
  });

  it("forces template visual mode when entering explicit template flow", () => {
    cy.contains("button", "AI 自由视觉").click();
    cy.contains("button", "模板生成").click();
    cy.contains("AI 自由视觉").should("not.exist");

    cy.get('[data-testid="prompt-input"]').type("端午节亲子活动");
    cy.contains("button", "Get Started").click();

    cy.wait("@createKindergartenPresentation")
      .its("request.body.visual_mode")
      .should("equal", "template");
  });

  it("still processes uploaded source documents before lesson planning", () => {
    cy.fixture("example.txt").as("testFile");
    cy.get('[data-testid="file-upload-input"]').selectFile("@testFile", { force: true });

    cy.intercept("POST", "**/ppt/files/upload", {
      statusCode: 200,
      body: [{ file_path: "/tmp/uploads/example.txt" }],
    }).as("uploadDoc");
    cy.intercept("POST", "**/ppt/files/decompose", {
      statusCode: 200,
      body: [{ name: "example.txt", file_path: "/tmp/decomposed/example.txt" }],
    }).as("decomposeDoc");

    cy.get('[data-testid="prompt-input"]').type("根据资料设计科学活动");
    cy.contains("button", "Get Started").click();

    cy.wait("@uploadDoc");
    cy.wait("@decomposeDoc");
    cy.wait("@createKindergartenPresentation")
      .its("request.body.file_paths")
      .should("deep.equal", ["/tmp/decomposed/example.txt"]);
  });

  it("shows validation when neither a topic nor a document exists", () => {
    cy.contains("button", "Get Started").click();
    checkToast("请输入内容");
  });

  it("surfaces planner API failures without navigating", () => {
    cy.intercept("POST", "**/ppt/kindergarten/presentation/create", {
      statusCode: 422,
      body: { detail: { code: "KINDERGARTEN_PLAN_QUALITY_FAILED" } },
    }).as("plannerError");

    cy.get('[data-testid="prompt-input"]').type("测试课件");
    cy.contains("button", "Get Started").click();
    cy.wait("@plannerError");
    checkToast("生成失败");
  });
});
