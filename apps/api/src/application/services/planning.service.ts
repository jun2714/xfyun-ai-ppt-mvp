import { z } from "zod";
import {
  DeckDesignPlanSchema,
  NarrativeArcSchema,
  NarrativeOutlineSchema,
  NarrativePageSchema,
  PageDesignIntentSchema,
  hashContent,
  versioned,
  type DeckDesignPlan,
  type NarrativeOutline,
  type PageDesignIntent,
  type PageRelationPredicate,
  type PresentationBrief
} from "@sparkdeck/presentation-model";
import type { PromptCatalogPort, PromptContract } from "../ports/prompt-catalog.port.js";
import type { GenerateTextUseCase } from "../use-cases/generate-text.use-case.js";
import { AppError } from "../../shared/errors/app-error.js";

const productionLanguage = /(?:\b(?:x|y|width|height)\b|css|html|svg|tailwind|pptx|template\s*id|layout\s*id|coordinate|placeholder|negative\s*prompt)/i;
const normalizedCopy = (value: string) => value.normalize("NFKC").toLocaleLowerCase().replace(/[\p{P}\p{S}\s]+/gu, "");
const jsonOf = (content: string): unknown => {
  try { return JSON.parse(content); }
  catch { throw new AppError("MODEL_JSON_INVALID", "Model did not return valid JSON", 502); }
};
const contractFailure = (error: unknown, content: string, resultTelemetry: PlanningTelemetry) => {
  const issues = error instanceof z.ZodError
    ? error.issues.map(({ path, code, message }) => ({ path, code, message }))
    : [{ path: [], code: error instanceof AppError ? error.code : "MODEL_CONTRACT_INVALID", message: error instanceof Error ? error.message : "Model response failed validation" }];
  return new AppError("MODEL_CONTRACT_INVALID", "Model response does not match the narrative contract", 502, issues, {
    stage: "planning", incurredCost: true, manualRetryAllowed: true, modelTelemetry: resultTelemetry,
    modelResponseEvidence: { contentHash: hashContent(content), characterCount: content.length, validationIssues: issues }
  });
};
const VersionKeys = { schemaVersion: true, revision: true, contentHash: true, upstreamHashes: true } as const;
const NarrativeModelOutputSchema = z.object({ pages: z.array(NarrativePageSchema).min(1), arc: NarrativeArcSchema }).strict();
const DesignPlanPayloadSchema = DeckDesignPlanSchema.omit(VersionKeys);
const DesignModelOutputSchema = z.object({ plan: DesignPlanPayloadSchema, intents: z.array(PageDesignIntentSchema).min(1) }).strict();

export type PlanningTelemetry = {
  model: string;
  inputTokens: number;
  outputTokens: number;
  estimatedCostRmb: number;
  prompt: Pick<PromptContract, "id" | "version" | "contentHash">;
};
export type PlanningResult<T> = { value: T; telemetry: PlanningTelemetry };

const telemetry = (result: Awaited<ReturnType<GenerateTextUseCase["execute"]>>, prompt: PromptContract): PlanningTelemetry => ({
  model: result.model,
  inputTokens: result.usage.inputTokens,
  outputTokens: result.usage.outputTokens,
  estimatedCostRmb: result.usage.estimatedCostRmb,
  prompt: { id: prompt.id, version: prompt.version, contentHash: prompt.contentHash }
});

const predicateSourceIds = (predicate: PageRelationPredicate): string[] => {
  if (predicate.kind === "associate") return [...predicate.leftSourceIds, ...predicate.rightSourceIds];
  return predicate.sourceIds;
};

/** Validates narrative references and state visibility without deciding any page layout. */
export function validateNarrative(outline: NarrativeOutline, brief: PresentationBrief): void {
  if (outline.pages.length !== brief.pageCount) throw new AppError("NARRATIVE_PAGE_COUNT_INVALID", `Expected ${brief.pageCount} pages, received ${outline.pages.length}`, 422);
  const pageIds = outline.pages.map((page) => page.id);
  const groupIds = outline.pages.flatMap((page) => page.contentGroups.map((group) => group.id));
  if (new Set(pageIds).size !== pageIds.length || new Set(groupIds).size !== groupIds.length) throw new AppError("NARRATIVE_ID_DUPLICATE", "Narrative page and content group IDs must be unique", 422);
  const allSources = new Set([...pageIds, ...groupIds]);
  const pageSources = new Map(outline.pages.map((page) => [page.id, new Set([page.id, ...page.contentGroups.map((group) => group.id)])]));
  const sectionPages = outline.arc.sections.flatMap((section) => section.pageIds);
  if (sectionPages.length !== pageIds.length || new Set(sectionPages).size !== pageIds.length || sectionPages.some((id) => !pageSources.has(id))) {
    throw new AppError("NARRATIVE_SECTION_COVERAGE_INVALID", "Narrative sections must cover every page exactly once", 422);
  }
  const linkIds = new Set<string>();
  for (const link of outline.arc.pageLinks) {
    if (linkIds.has(link.id)) throw new AppError("NARRATIVE_LINK_DUPLICATE", `Duplicate page link: ${link.id}`, 422);
    linkIds.add(link.id);
    if (link.fromPageId === link.toPageId || !pageSources.has(link.fromPageId) || !pageSources.has(link.toPageId)) throw new AppError("NARRATIVE_LINK_REFERENCE_INVALID", `Invalid page link: ${link.id}`, 422);
    for (const predicate of link.predicates) {
      if (predicateSourceIds(predicate).some((id) => !allSources.has(id))) throw new AppError("NARRATIVE_SOURCE_REFERENCE_INVALID", `Unknown source in page link: ${link.id}`, 422);
      if (predicate.kind === "conceal") {
        const sources = pageSources.get(predicate.onPageId);
        if (!sources || ![link.fromPageId, link.toPageId].includes(predicate.onPageId) || predicate.sourceIds.some((id) => sources.has(id))) {
          throw new AppError("NARRATIVE_CONCEALMENT_INVALID", `Concealed content is visible or references the wrong page: ${link.id}`, 422);
        }
      }
      if (predicate.kind === "introduce") {
        const sources = pageSources.get(predicate.onPageId);
        if (!sources || ![link.fromPageId, link.toPageId].includes(predicate.onPageId) || predicate.sourceIds.some((id) => !sources.has(id))) {
          throw new AppError("NARRATIVE_INTRODUCTION_INVALID", `Introduced content is absent or references the wrong page: ${link.id}`, 422);
        }
      }
    }
  }
  const visibleCopy = outline.pages.flatMap((page) => [
    page.headline,
    page.message,
    ...(page.audienceAction?.visible ? [page.audienceAction.instruction] : []),
    ...page.contentGroups.flatMap((group) => [group.label, group.text, ...(group.items ?? []), ...(group.rows?.flat().map(String) ?? [])].filter((value): value is string => Boolean(value)))
  ]).join("\n");
  if (productionLanguage.test(visibleCopy)) throw new AppError("NARRATIVE_PRODUCTION_COPY_VISIBLE", "Audience-facing copy contains production language", 422);
  const normalizedHeadlines = outline.pages.map((page) => normalizedCopy(page.headline));
  if (normalizedHeadlines.some((headline) => headline.length < 3)) throw new AppError("NARRATIVE_HEADLINE_VAGUE", "Every headline must communicate a specific audience-facing idea", 422);
  if (new Set(normalizedHeadlines).size !== normalizedHeadlines.length) throw new AppError("NARRATIVE_HEADLINE_DUPLICATE", "Page headlines must not repeat", 422);
  for (const page of outline.pages) {
    const headline = normalizedCopy(page.headline);
    const visibleBodies = [page.message, ...page.contentGroups.flatMap((group) => [group.label, group.text, ...(group.items ?? [])].filter((value): value is string => Boolean(value)))].map(normalizedCopy);
    if (visibleBodies.some((body) => body.length >= 3 && body === headline)) throw new AppError("NARRATIVE_HEADLINE_BODY_DUPLICATE", `Headline repeats body copy on ${page.id}`, 422);
  }
}

/** Plans one complete narrative using a versioned external prompt contract. */
export class NarrativePlanner {
  constructor(private readonly text: GenerateTextUseCase, private readonly prompts: PromptCatalogPort) {}

  async plan(brief: PresentationBrief): Promise<PlanningResult<NarrativeOutline>> {
    const prompt = this.prompts.get("narrative");
    const result = await this.text.execute({
      systemPrompt: prompt.content,
      userPrompt: JSON.stringify({ brief: { title: brief.title, audience: brief.audience, ageRange: brief.ageRange, usageContext: brief.usageContext, objective: brief.objective, pageCount: brief.pageCount, constraints: brief.constraints, language: brief.language } }),
      responseFormat: "json_object"
    });
    const resultTelemetry = telemetry(result, prompt);
    try {
      if (productionLanguage.test(result.content)) throw new AppError("MODEL_PRODUCTION_LANGUAGE_LEAK", "Narrative model returned production language", 422);
      const raw = NarrativeModelOutputSchema.parse(jsonOf(result.content));
      const outline = NarrativeOutlineSchema.parse(versioned({ briefId: brief.id, pages: raw.pages, arc: raw.arc, confirmedAt: null }, 0, { brief: brief.contentHash }));
      validateNarrative(outline, brief);
      return { value: outline, telemetry: resultTelemetry };
    } catch (error) { throw contractFailure(error, result.content, resultTelemetry); }
  }
}

/** Validates design references, asset identities, and cross-page constraints before composition. */
export function validateDesign(brief: PresentationBrief, outline: NarrativeOutline, plan: DeckDesignPlan, intents: PageDesignIntent[]): void {
  if (plan.briefId !== brief.id) throw new AppError("DESIGN_BRIEF_REFERENCE_INVALID", "Design plan references a different brief", 422);
  if (intents.length !== outline.pages.length) throw new AppError("DESIGN_PAGE_COUNT_INVALID", "Design intent count does not match narrative pages", 422);
  const pageIds = new Set(outline.pages.map((page) => page.id));
  if (new Set(intents.map((intent) => intent.pageId)).size !== intents.length || intents.some((intent) => !pageIds.has(intent.pageId))) throw new AppError("DESIGN_PAGE_REFERENCE_INVALID", "Design intent page references are invalid", 422);
  const identityById = new Map(plan.assetIdentities.map((identity) => [identity.id, identity]));
  if (identityById.size !== plan.assetIdentities.length) throw new AppError("ASSET_IDENTITY_DUPLICATE", "Asset identity IDs must be unique", 422);
  const requestIds = new Set<string>();
  const audienceCopy = normalizedCopy(outline.pages.flatMap((page) => [page.headline, page.message, ...page.contentGroups.flatMap((group) => [group.label, group.text, ...(group.items ?? [])])]).filter((value): value is string => Boolean(value)).join("\n"));
  for (const page of outline.pages) {
    const intent = intents.find((item) => item.pageId === page.id)!;
    const groupIds = new Set(page.contentGroups.map((group) => group.id));
    const referenced = new Set([...intent.hierarchy.map((item) => item.contentGroupId), ...intent.groups.flatMap((group) => group.contentGroupIds)]);
    if ([...referenced].some((id) => !groupIds.has(id))) throw new AppError("DESIGN_CONTENT_REFERENCE_INVALID", `Unknown content group on ${page.id}`, 422);
    for (const group of page.contentGroups.filter((item) => item.required)) if (!referenced.has(group.id)) throw new AppError("DESIGN_REQUIRED_CONTENT_MISSING", `Required content group is not designed: ${group.id}`, 422);
    for (const request of intent.mediaRequests) {
      if (requestIds.has(request.id)) throw new AppError("DESIGN_MEDIA_REQUEST_DUPLICATE", `Duplicate media request: ${request.id}`, 422);
      requestIds.add(request.id);
      const identity = identityById.get(request.identityId);
      if (!identity || identity.semanticEntityId !== request.semanticEntityId || identity.visualIdentityKey !== request.visualIdentityKey || identity.role !== request.role || identity.reusePolicy !== request.reusePolicy) {
        throw new AppError("ASSET_IDENTITY_REFERENCE_INVALID", `Media request does not match its asset identity: ${request.id}`, 422);
      }
      const privateDescription = normalizedCopy(request.description);
      if (privateDescription.length >= 6 && audienceCopy.includes(privateDescription)) throw new AppError("DESIGN_MEDIA_DESCRIPTION_LEAK", `Private media description leaks into audience copy: ${request.id}`, 422);
    }
  }
  const narrativeSources = new Set(outline.pages.flatMap((page) => [page.id, ...page.contentGroups.map((group) => group.id)]));
  for (const constraint of plan.crossPageConstraints) {
    if (constraint.pageIds.some((id) => !pageIds.has(id))) throw new AppError("DESIGN_CROSS_PAGE_REFERENCE_INVALID", `Unknown page in constraint: ${constraint.id}`, 422);
    for (const predicate of constraint.predicates) if (predicateSourceIds(predicate).some((id) => !narrativeSources.has(id) && !identityById.has(id))) throw new AppError("DESIGN_CROSS_PAGE_SOURCE_INVALID", `Unknown source in constraint: ${constraint.id}`, 422);
  }
}

/** Plans deck-wide visual semantics without returning geometry or renderer code. */
export class DesignPlanner {
  constructor(private readonly text: GenerateTextUseCase, private readonly prompts: PromptCatalogPort) {}

  async plan(brief: PresentationBrief, outline: NarrativeOutline): Promise<PlanningResult<{ plan: DeckDesignPlan; intents: PageDesignIntent[] }>> {
    const prompt = this.prompts.get("design");
    const result = await this.text.execute({
      systemPrompt: prompt.content,
      userPrompt: JSON.stringify({ brief, outline }),
      responseFormat: "json_object"
    });
    if (productionLanguage.test(result.content)) throw new AppError("MODEL_PRODUCTION_LANGUAGE_LEAK", "Design model returned production language", 422);
    const raw = DesignModelOutputSchema.parse(jsonOf(result.content));
    const plan = DeckDesignPlanSchema.parse(versioned(raw.plan, 0, { outline: outline.contentHash }));
    validateDesign(brief, outline, plan, raw.intents);
    return { value: { plan, intents: raw.intents }, telemetry: telemetry(result, prompt) };
  }
}

/** Includes protocol version so caches cannot cross prompt or schema boundaries silently. */
export const promptHash = (value: unknown) => hashContent({ version: "008.0", value });
