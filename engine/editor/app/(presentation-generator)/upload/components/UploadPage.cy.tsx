import React from "react";
import UploadPage from "./UploadPage";
import { mount } from "cypress/react";
import { store } from "@/store/store";
import { Provider } from "react-redux";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { Toaster } from "@/components/ui/sonner";

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

const kindergartenStartResponse = (overrides: Record<string, unknown> = {}) => ({
  presentation_id: "test-id",
  outline_path: "/presentations/test-id/outline",
  outline_stream_path:
    "/api/v1/ppt/kindergarten/presentation/outline/stream/test-id",
  n_slides: 10,
  visual_mode: "template",
  ...overrides,
});

const checkToast = (message: string) => {
  cy.get("[data-sonner-toast]", { timeout: 5000 }).should("contain", message);
};

const clickGenerate = () => {
  cy.get('button[aria-label="生成演示文稿"]').click({ force: true });
};

describe("<UploadPage /> kindergarten creation", () => {
  beforeEach(() => {
    cy.viewport(1440, 900);
    cy.intercept("POST", "**/ppt/kindergarten/presentation/start", {
      statusCode: 200,
      body: kindergartenStartResponse(),
    }).as("startKindergartenPresentation");

    cy.on("window:before:load", (win) => {
      cy.stub(win.location, "assign").as("locationAssign");
    });

    cy.mount(<UploadPage />);
  });

  it("keeps the teacher-facing configuration controls usable", () => {
    cy.get('[data-testid="slides-select"]').click({ force: true });
    cy.get('[role="option"]').contains("12").click({ force: true });
    cy.get('[data-testid="slides-select"]').should("contain", "12");

    cy.get('[data-testid="prompt-input"]').type("春天里的种子");
    cy.get('[data-testid="prompt-input"]').should("have.value", "春天里的种子");
  });

  it("sends template mode through the kindergarten planner", () => {
    cy.get('[data-testid="prompt-input"]').type("洗手好习惯");
    cy.contains("button", "智能模板").click();
    clickGenerate();

    cy.wait("@startKindergartenPresentation")
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
      /\/presentations\/test-id\/outline\?mode=topic/,
    );
  });

  it("sends AI free visual mode and carries the visual preference", () => {
    cy.intercept("POST", "**/ppt/kindergarten/presentation/start", {
      statusCode: 200,
      body: kindergartenStartResponse({
        visual_mode: "ai-background",
      }),
    }).as("createAiVisualPresentation");

    cy.get('[data-testid="prompt-input"]').type("森林动物大冒险");
    cy.contains("button", "AI 自由视觉").click();
    clickGenerate();

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
      /\/presentations\/test-id\/outline\?mode=topic/,
    );
  });

  it("forces template visual mode when entering explicit template flow", () => {
    cy.contains("button", "AI 自由视觉").click();
    cy.contains("button", "模板生成").click();
    cy.contains("AI 自由视觉").should("not.exist");

    cy.get('[data-testid="prompt-input"]').type("端午节亲子活动");
    clickGenerate();

    cy.wait("@startKindergartenPresentation")
      .its("request.body.visual_mode")
      .should("equal", "template");
  });

  it("still processes uploaded source documents before lesson planning", () => {
    cy.get('[data-testid="file-upload-input"]').selectFile(
      {
        contents: Cypress.Buffer.from("kindergarten source material"),
        fileName: "example.txt",
        mimeType: "text/plain",
      },
      { force: true },
    );

    cy.intercept("POST", "**/ppt/files/upload", {
      statusCode: 200,
      body: [{ file_path: "/tmp/uploads/example.txt" }],
    }).as("uploadDoc");
    cy.intercept("POST", "**/ppt/files/decompose", {
      statusCode: 200,
      body: [{ name: "example.txt", file_path: "/tmp/decomposed/example.txt" }],
    }).as("decomposeDoc");

    cy.get('[data-testid="prompt-input"]').type("根据资料设计科学活动");
    clickGenerate();

    cy.wait("@uploadDoc");
    cy.wait("@decomposeDoc");
    cy.wait("@startKindergartenPresentation")
      .its("request.body.file_paths")
      .should("deep.equal", ["/tmp/decomposed/example.txt"]);
  });

  it("shows validation when neither a topic nor a document exists", () => {
    clickGenerate();
    checkToast("请输入内容");
  });

  it("surfaces planner API failures without navigating", () => {
    cy.intercept("POST", "**/ppt/kindergarten/presentation/start", {
      statusCode: 422,
      body: { detail: { code: "KINDERGARTEN_PLAN_QUALITY_FAILED" } },
    }).as("plannerError");

    cy.get('[data-testid="prompt-input"]').type("测试课件");
    clickGenerate();
    cy.wait("@plannerError");
    checkToast("生成失败");
  });
});
