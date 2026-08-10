import {
  DeckDesignPlanSchema,
  NarrativeOutlineSchema,
  PageDesignIntentSchema,
  hashContent,
  versioned,
  type DeckDesignPlan,
  type NarrativeOutline,
  type PageDesignIntent,
  type PresentationBrief
} from "@sparkdeck/presentation-model";
import type { GenerateTextUseCase } from "../use-cases/generate-text.use-case.js";
import { AppError } from "../../shared/errors/app-error.js";

const productionLanguage = /(?:\b(?:x|y|width|height)\b|css|html|svg|tailwind|pptx|template\s*id|layout\s*id|coordinate)/i;
const jsonOf = (content: string): unknown => {
  try { return JSON.parse(content); }
  catch { throw new AppError("MODEL_JSON_INVALID", "Model did not return valid JSON", 502); }
};

const narrativeContract = {
  pages: [{
    id: "unique page id", purpose: "communication purpose", headline: "audience-facing slide title",
    message: "single core message", contentGroups: [{
      id: "unique group id", kind: "paragraph|list|comparison|sequence|quote|metric|question|answer|caption|table|chart-data|annotation",
      label: "optional short audience-facing label", text: "optional audience-facing copy", items: ["optional item"],
      rows: [["optional table or chart cell"]], claimIds: ["claim id"], required: true
    }], speakerNotes: ["presenter note, never visible on slide"], evidenceRequests: [], continuityLinks: ["related page id"]
  }]
};

const designContract = {
  plan: {
    briefId: "same brief id", designSeed: "stable creative seed", tone: ["tone"],
    typography: { character: "character", headingFamily: "installed/common font family", bodyFamily: "installed/common font family", headingWeight: 700, bodyWeight: 400 },
    palette: { mood: "mood", background: "#RRGGBB", surface: "#RRGGBB", text: "#RRGGBB", primary: "#RRGGBB", secondary: "#RRGGBB", accent: "#RRGGBB", muted: "#RRGGBB" },
    shapeLanguage: { character: "character", cornerStyle: "sharp|soft|round", strokeStyle: "none|subtle|expressive", motif: "reusable visual motif" },
    illustrationDirection: "optional consistent art direction", densityTarget: "airy|balanced|dense",
    rhythm: { variation: "subtle|moderate|strong", continuity: ["deck consistency rule"] }, consistencyRules: ["rule"]
  },
  intents: [{
    pageId: "existing page id", focalMessage: "primary communication", hierarchy: [{ contentGroupId: "existing group id", priority: 1 }],
    groups: [{ id: "new design group id", contentGroupIds: ["existing group id"], treatment: "plain|emphasis|paired|progressive|evidence|callout" }],
    relationships: [{ from: "existing id", to: "existing id", kind: "sequence|contrast|supports|reveals|belongs" }],
    visualStrategy: "none|background|subject|evidence|gallery|diagram", balance: "symmetric|asymmetric|centered|directional",
    flow: "vertical|horizontal|radial|sequence|free-emphasis", density: "low|medium|high",
    emphasis: [{ targetId: "existing id", strength: "low|medium|high", reason: "communication reason" }],
    mediaRequests: [{ id: "new media id", claimIds: ["existing claim id"], role: "background|subject|cutout|detail|evidence", description: "visual content only", fit: "cover|contain", focalPolicy: "auto|center|face|subject", textSafeArea: "none|left|right|top|bottom|center", required: true, continuityKey: "optional reuse key" }],
    avoid: ["communication risk"]
  }]
};

export type PlanningTelemetry = { model: string; inputTokens: number; outputTokens: number; estimatedCostRmb: number };
export type PlanningResult<T> = { value: T; telemetry: PlanningTelemetry };

export class NarrativePlanner {
  constructor(private readonly text: GenerateTextUseCase) {}

  async plan(brief: PresentationBrief): Promise<PlanningResult<NarrativeOutline>> {
    const result = await this.text.execute({
      systemPrompt: [
        "Return one JSON narrative outline for the complete presentation.",
        "Write only copy intended for the stated audience in visible fields.",
        "Put presenter guidance only in speakerNotes.",
        "Never put image prompts, production instructions, timing scaffolds, layout language, or placeholder copy into headline, message, label, text, items, or rows.",
        "Use multiple content groups whenever a page contains multiple ideas; do not collapse a page into one generic block.",
        "Do not describe coordinates, templates, CSS, HTML, SVG, or PPTX code."
      ].join(" "),
      userPrompt: JSON.stringify({
        brief: { title: brief.title, audience: brief.audience, ageRange: brief.ageRange, usageContext: brief.usageContext, objective: brief.objective, pageCount: brief.pageCount, constraints: brief.constraints, language: brief.language },
        exactPageCount: brief.pageCount,
        requiredOutput: narrativeContract
      }),
      responseFormat: "json_object"
    });
    if (productionLanguage.test(result.content)) throw new AppError("PRODUCTION_LANGUAGE_LEAK", "Narrative contains production language", 422);
    const raw = jsonOf(result.content) as { pages?: unknown };
    const outline = NarrativeOutlineSchema.parse(versioned({ briefId: brief.id, pages: raw.pages, confirmedAt: null }, 0, { brief: brief.contentHash }));
    if (outline.pages.length !== brief.pageCount) throw new AppError("OUTLINE_PAGE_COUNT_INVALID", `Expected ${brief.pageCount} pages, received ${outline.pages.length}`, 422);
    const groupIds = outline.pages.flatMap((page) => page.contentGroups.map((group) => group.id));
    if (new Set(groupIds).size !== groupIds.length) throw new AppError("OUTLINE_REFERENCE_INVALID", "Content group ids must be unique across the deck", 422);
    return { value: outline, telemetry: { model: result.model, inputTokens: result.usage.inputTokens, outputTokens: result.usage.outputTokens, estimatedCostRmb: result.usage.estimatedCostRmb } };
  }
}

export class DesignPlanner {
  constructor(private readonly text: GenerateTextUseCase) {}

  async plan(brief: PresentationBrief, outline: NarrativeOutline): Promise<PlanningResult<{ plan: DeckDesignPlan; intents: PageDesignIntent[] }>> {
    const result = await this.text.execute({
      systemPrompt: [
        "Return one JSON design plan for the complete deck and one communication intent for every existing page.",
        "Express hierarchy, grouping, relationships, rhythm, native typography, native shapes, and media purpose.",
        "Media descriptions are generation metadata and must never be copied into visible slide content.",
        "Reference every required content group at least once.",
        "Never return coordinates, sizes, CSS, HTML, SVG, PPTX code, template IDs, layout IDs, or executable code."
      ].join(" "),
      userPrompt: JSON.stringify({ brief, outline, requiredOutput: designContract }),
      responseFormat: "json_object"
    });
    if (productionLanguage.test(result.content)) throw new AppError("PRODUCTION_LANGUAGE_LEAK", "Design plan contains production language", 422);
    const raw = jsonOf(result.content) as { plan?: unknown; intents?: unknown };
    const plan = DeckDesignPlanSchema.parse(versioned(raw.plan, 0, { outline: outline.contentHash }));
    const intents = PageDesignIntentSchema.array().length(outline.pages.length).parse(raw.intents);
    if (plan.briefId !== brief.id) throw new AppError("DESIGN_REFERENCE_INVALID", "Design plan references a different brief", 422);
    const pageIds = new Set(outline.pages.map((page) => page.id));
    if (new Set(intents.map((intent) => intent.pageId)).size !== intents.length || intents.some((intent) => !pageIds.has(intent.pageId))) throw new AppError("DESIGN_REFERENCE_INVALID", "Design intent page references are invalid", 422);
    for (const page of outline.pages) {
      const intent = intents.find((item) => item.pageId === page.id);
      if (!intent) throw new AppError("DESIGN_REFERENCE_INVALID", `Missing design intent for ${page.id}`, 422);
      const groupIds = new Set(page.contentGroups.map((group) => group.id));
      const referenced = new Set([...intent.hierarchy.map((item) => item.contentGroupId), ...intent.groups.flatMap((group) => group.contentGroupIds)]);
      if ([...referenced].some((id) => !groupIds.has(id))) throw new AppError("DESIGN_REFERENCE_INVALID", `Unknown content group on ${page.id}`, 422);
      for (const group of page.contentGroups.filter((item) => item.required)) if (!referenced.has(group.id)) throw new AppError("DESIGN_REFERENCE_INVALID", `Required content group is not designed: ${group.id}`, 422);
    }
    return { value: { plan, intents }, telemetry: { model: result.model, inputTokens: result.usage.inputTokens, outputTokens: result.usage.outputTokens, estimatedCostRmb: result.usage.estimatedCostRmb } };
  }
}

export const promptHash = (value: unknown) => hashContent({ version: "007.2", value });
