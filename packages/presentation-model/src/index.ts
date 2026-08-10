import { createHash } from "node:crypto";
import { z } from "zod";

/** 008 uses a clean protocol boundary; production objects never mix with 007 fields. */
export const SCHEMA_VERSION = "008.0" as const;
/** Validates stable non-empty protocol identifiers. */
export const IdSchema = z.string().trim().min(1);
/** Validates six-digit semantic color tokens. */
export const HexColorSchema = z.string().regex(/^#[0-9a-f]{6}$/i);
/** Carries revision, content identity, and upstream invalidation evidence. */
export const VersionedSchema = z.object({
  schemaVersion: z.literal(SCHEMA_VERSION),
  revision: z.number().int().nonnegative(),
  contentHash: z.string().regex(/^[0-9a-f]{64}$/),
  upstreamHashes: z.record(z.string(), z.string().regex(/^[0-9a-f]{64}$/)).default({})
});
export type Versioned = z.infer<typeof VersionedSchema>;

/** Creates a deterministic content identity used by invalidation and idempotency checks. */
export const hashContent = (value: unknown) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
export const versioned = <T>(value: T, revision = 0, upstreamHashes: Record<string, string> = {}) => ({
  ...value,
  schemaVersion: SCHEMA_VERSION,
  revision,
  contentHash: hashContent(value),
  upstreamHashes
});

/** Defines user intent without any layout or provider-specific fields. */
export const PresentationBriefSchema = VersionedSchema.extend({
  id: IdSchema,
  title: z.string().trim().min(1),
  audience: z.string().trim().min(1),
  ageRange: z.string().trim().optional(),
  usageContext: z.string().trim().min(1),
  objective: z.string().trim().min(1),
  pageCount: z.number().int().min(1).max(80),
  constraints: z.array(z.string().trim().min(1)).default([]),
  sourceAssetIds: z.array(IdSchema).default([]),
  language: z.string().trim().default("zh-CN")
});
export type PresentationBrief = z.infer<typeof PresentationBriefSchema>;

/** Enumerates audience-content structures independently of visual layout. */
export const ContentKindSchema = z.enum([
  "paragraph", "list", "comparison", "sequence", "quote", "metric", "question", "answer",
  "caption", "table", "chart-data", "annotation"
]);
/** Preserves one semantic unit so composition cannot silently discard copy. */
export const ContentGroupSchema = z.object({
  id: IdSchema,
  kind: ContentKindSchema,
  label: z.string().trim().optional(),
  text: z.string().trim().optional(),
  items: z.array(z.string().trim().min(1)).optional(),
  rows: z.array(z.array(z.union([z.string(), z.number()]))).optional(),
  claimIds: z.array(IdSchema).default([]),
  required: z.boolean().default(true)
}).superRefine((group, context) => {
  if (!group.text && !group.items?.length && !group.rows?.length) context.addIssue({ code: z.ZodIssueCode.custom, message: "content group is empty" });
});
export type ContentGroup = z.infer<typeof ContentGroupSchema>;

/** Separates an optional audience interaction from presenter-only notes. */
export const AudienceActionSchema = z.object({
  mode: z.enum(["observe", "respond", "choose", "match", "recall", "discuss", "perform", "reflect"]),
  instruction: z.string().trim().min(1),
  visible: z.boolean().default(false)
});

/** Defines one narrative step; it deliberately contains no page-role template. */
export const NarrativePageSchema = z.object({
  id: IdSchema,
  purpose: z.string().trim().min(1),
  headline: z.string().trim().min(1),
  message: z.string().trim().min(1),
  contentGroups: z.array(ContentGroupSchema).min(1),
  audienceAction: AudienceActionSchema.optional(),
  speakerNotes: z.array(z.string()).default([]),
  evidenceRequests: z.array(z.object({ id: IdSchema, description: z.string().min(1), required: z.boolean().default(false) })).default([])
});
export type NarrativePage = z.infer<typeof NarrativePageSchema>;

/** Generic page predicates describe state and relationships, never page roles or layouts. */
export const PageRelationPredicateSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("preserve"), sourceIds: z.array(IdSchema).min(1), properties: z.array(z.enum(["identity", "relative-order", "scale-family", "visual-treatment"])).min(1) }),
  z.object({ kind: z.literal("conceal"), sourceIds: z.array(IdSchema).min(1), onPageId: IdSchema }),
  z.object({ kind: z.literal("introduce"), sourceIds: z.array(IdSchema).min(1), onPageId: IdSchema }),
  z.object({ kind: z.literal("change"), sourceIds: z.array(IdSchema).min(1), properties: z.array(z.string().trim().min(1)).min(1) }),
  z.object({ kind: z.literal("associate"), leftSourceIds: z.array(IdSchema).min(1), rightSourceIds: z.array(IdSchema).min(1) }),
  z.object({ kind: z.literal("compare"), sourceIds: z.array(IdSchema).min(2) }),
  z.object({ kind: z.literal("order"), sourceIds: z.array(IdSchema).min(2) })
]);
export type PageRelationPredicate = z.infer<typeof PageRelationPredicateSchema>;
/** Links pages through generic state predicates rather than stored layouts. */
export const PageLinkSchema = z.object({
  id: IdSchema,
  fromPageId: IdSchema,
  toPageId: IdSchema,
  predicates: z.array(PageRelationPredicateSchema).min(1)
});
export type PageLink = z.infer<typeof PageLinkSchema>;
/** Groups pages for narrative pacing while remaining geometry-free. */
export const NarrativeSectionSchema = z.object({
  id: IdSchema,
  purpose: z.string().trim().min(1),
  pageIds: z.array(IdSchema).min(1),
  transition: z.string().trim().min(1)
});
/** Describes deck-wide outcome, sections, and cross-page state. */
export const NarrativeArcSchema = z.object({
  centralOutcome: z.string().trim().min(1),
  sections: z.array(NarrativeSectionSchema).min(1),
  pageLinks: z.array(PageLinkSchema).default([])
});
export type NarrativeArc = z.infer<typeof NarrativeArcSchema>;
/** Versioned narrative contract consumed by design and composition. */
export const NarrativeOutlineSchema = VersionedSchema.extend({
  briefId: IdSchema,
  pages: z.array(NarrativePageSchema).min(1),
  arc: NarrativeArcSchema,
  confirmedAt: z.string().datetime().nullable().default(null)
});
export type NarrativeOutline = z.infer<typeof NarrativeOutlineSchema>;

/** Roles define media behavior and validation, never a fixed coordinate slot. */
export const MediaRoleSchema = z.enum(["full-bleed-background", "scene", "subject", "transparent-cutout", "detail", "evidence"]);
export type MediaRole = z.infer<typeof MediaRoleSchema>;
/** Declares one private generation need and its reusable visual identity. */
export const MediaRequestSchema = z.object({
  id: IdSchema,
  identityId: IdSchema,
  semanticEntityId: IdSchema,
  claimIds: z.array(IdSchema),
  role: MediaRoleSchema,
  description: z.string().trim().min(1),
  audienceAlt: z.string().trim().min(1).optional(),
  fit: z.enum(["cover", "contain"]),
  focalPolicy: z.enum(["auto", "center", "face", "subject"]),
  textSafeArea: z.enum(["none", "left", "right", "top", "bottom", "center"]).optional(),
  required: z.boolean().default(true),
  visualIdentityKey: z.string().trim().min(1),
  variantIntent: z.string().trim().optional(),
  reusePolicy: z.enum(["exact", "controlled-variant", "single-use"])
});
export type MediaRequest = z.infer<typeof MediaRequestSchema>;

/** Carries design-level continuity predicates for joint deck selection. */
export const CrossPageConstraintSchema = z.object({
  id: IdSchema,
  pageIds: z.array(IdSchema).min(2),
  predicates: z.array(PageRelationPredicateSchema).min(1)
});
export type CrossPageConstraint = z.infer<typeof CrossPageConstraintSchema>;

/** Defines a composable visual language without storing finished page answers. */
export const DeckVisualGrammarSchema = z.object({
  typographyCharacter: z.string().trim().min(1),
  shapeVocabulary: z.object({
    character: z.string().trim().min(1),
    forms: z.array(z.enum(["rectangle", "rounded-rectangle", "circle", "line", "arc", "freeform"])).min(1),
    strokeStyle: z.enum(["none", "subtle", "expressive"]),
    cornerStyle: z.enum(["sharp", "soft", "round"])
  }),
  motifRules: z.array(z.object({
    id: IdSchema,
    intent: z.string().trim().min(1),
    frequency: z.enum(["rare", "occasional", "recurring"]),
    layer: z.enum(["background", "support", "accent"])
  })).default([]),
  mediaLanguage: z.object({
    rendering: z.string().trim().min(1),
    backgroundTreatment: z.string().trim().min(1),
    subjectTreatment: z.string().trim().min(1),
    consistencyRule: z.string().trim().min(1)
  }),
  variationPolicy: z.object({
    continuityStrength: z.enum(["low", "medium", "high"]),
    diversityStrength: z.enum(["low", "medium", "high"])
  })
});
export type DeckVisualGrammar = z.infer<typeof DeckVisualGrammarSchema>;

/** Gives reusable media one stable semantic and visual identity. */
export const AssetIdentitySchema = z.object({
  id: IdSchema,
  semanticEntityId: IdSchema,
  visualIdentityKey: z.string().trim().min(1),
  role: MediaRoleSchema,
  variantIntent: z.string().trim().optional(),
  reusePolicy: z.enum(["exact", "controlled-variant", "single-use"])
});
export type AssetIdentity = z.infer<typeof AssetIdentitySchema>;

/** Versioned deck-wide design plan used to derive tokens and constraints. */
export const DeckDesignPlanSchema = VersionedSchema.extend({
  briefId: IdSchema,
  designSeed: z.string().min(1),
  tone: z.array(z.string()).min(1),
  typography: z.object({
    character: z.string().min(1),
    headingFamily: z.string().trim().min(1),
    bodyFamily: z.string().trim().min(1),
    headingWeight: z.number().int().min(300).max(900),
    bodyWeight: z.number().int().min(300).max(900)
  }),
  palette: z.object({
    mood: z.string().min(1), background: HexColorSchema, surface: HexColorSchema, text: HexColorSchema,
    primary: HexColorSchema, secondary: HexColorSchema, accent: HexColorSchema, muted: HexColorSchema
  }),
  visualGrammar: DeckVisualGrammarSchema,
  densityTarget: z.enum(["airy", "balanced", "dense"]),
  rhythm: z.object({ variation: z.enum(["subtle", "moderate", "strong"]), continuity: z.array(z.string()).min(1) }),
  consistencyRules: z.array(z.string()).min(1),
  crossPageConstraints: z.array(CrossPageConstraintSchema).default([]),
  assetIdentities: z.array(AssetIdentitySchema).default([])
});
export type DeckDesignPlan = z.infer<typeof DeckDesignPlanSchema>;

/** Semantic page design request; strict validation rejects coordinate leakage. */
export const PageDesignIntentSchema = z.object({
  pageId: IdSchema,
  focalMessage: z.string().min(1),
  hierarchy: z.array(z.object({ contentGroupId: IdSchema, priority: z.number().int().min(1).max(5) })).min(1),
  groups: z.array(z.object({
    id: IdSchema,
    contentGroupIds: z.array(IdSchema).min(1),
    treatment: z.enum(["plain", "emphasis", "paired", "progressive", "evidence", "callout"])
  })).min(1),
  relationships: z.array(z.object({ from: IdSchema, to: IdSchema, kind: z.enum(["sequence", "contrast", "supports", "reveals", "belongs"]) })).default([]),
  visualStrategy: z.enum(["none", "full-bleed-background", "scene", "subject", "collection", "relationship"]),
  balance: z.enum(["symmetric", "asymmetric", "centered", "directional"]),
  flow: z.enum(["vertical", "horizontal", "radial", "sequence", "free-emphasis"]),
  density: z.enum(["low", "medium", "high"]),
  emphasis: z.array(z.object({ targetId: IdSchema, strength: z.enum(["low", "medium", "high"]), reason: z.string().min(1) })).default([]),
  mediaRequests: z.array(MediaRequestSchema).default([]),
  avoid: z.array(z.string()).default([])
}).strict().superRefine((value, context) => {
  const forbidden = /(^|[^a-z])(x|y|width|height|css|html|svg|tailwind|pptx|templateId|layoutId)([^a-z]|$)/i;
  if (forbidden.test(JSON.stringify(value))) context.addIssue({ code: z.ZodIssueCode.custom, message: "design intent contains production or coordinate language" });
});
export type PageDesignIntent = z.infer<typeof PageDesignIntentSchema>;

/** Enumerates generic composition primitives available to the solver. */
export const PrimitiveKindSchema = z.enum(["Canvas", "SafeArea", "Stack", "Grid", "Flow", "Overlay", "Anchor", "Align", "Distribute", "Frame", "Group", "Text", "Shape", "Image", "Chart", "Connector"]);
export type PrimitiveKind = z.infer<typeof PrimitiveKindSchema>;
export type CompositionNode = { id: string; kind: PrimitiveKind; sourceIds: string[]; children?: CompositionNode[]; props: Record<string, unknown> };
/** Recursively validates an unsolved composition grammar tree. */
export const CompositionNodeSchema = z.lazy(() => z.object({
  id: IdSchema,
  kind: PrimitiveKindSchema,
  sourceIds: z.array(IdSchema),
  children: z.array(CompositionNodeSchema).optional(),
  props: z.record(z.string(), z.unknown()).default({})
})) as unknown as z.ZodType<CompositionNode>;
/** Validates finite solved geometry in Scene point units. */
export const BoundsSchema = z.object({ x: z.number().finite(), y: z.number().finite(), width: z.number().positive(), height: z.number().positive() });
export type Bounds = z.infer<typeof BoundsSchema>;

/** Records orthogonal grammar decisions used to produce candidate diversity. */
export const CompositionFeaturesSchema = z.object({
  anchor: z.enum(["text", "media", "relation", "mixed"]),
  direction: z.enum(["horizontal", "vertical", "radial", "layered"]),
  grouping: z.enum(["hierarchy", "parallel", "sequence", "association", "collection"]),
  emphasis: z.enum(["single-focus", "balanced", "progressive", "contrast"])
});
/** Makes every layout selection auditable back to metrics and constraints. */
export const LayoutDecisionTraceSchema = z.object({
  inputMetrics: z.record(z.string(), z.number()),
  constraintIds: z.array(IdSchema),
  differences: z.array(z.string().trim().min(1)),
  rejectedReasons: z.array(z.string()).default([])
});
export type LayoutDecisionTrace = z.infer<typeof LayoutDecisionTraceSchema>;
/** Stores one scored grammar candidate and its trace, not a named template. */
export const CompositionCandidateSchema = z.object({
  id: IdSchema,
  pageId: IdSchema,
  features: CompositionFeaturesSchema,
  grammarHash: z.string().regex(/^[0-9a-f]{64}$/),
  tree: CompositionNodeSchema,
  trace: LayoutDecisionTraceSchema,
  score: z.number(),
  hardFailures: z.array(z.string()),
  scoreBreakdown: z.record(z.string(), z.number()),
  silhouette: z.string().min(1),
  selected: z.boolean().default(false)
});
export type CompositionCandidate = z.infer<typeof CompositionCandidateSchema>;

/** Binds one selected image leaf to an asset identity and solved bounds. */
export const MediaPlacementSchema = z.object({
  id: IdSchema,
  pageId: IdSchema,
  requestId: IdSchema,
  identityId: IdSchema,
  claimIds: z.array(IdSchema),
  role: MediaRoleSchema,
  boundsRef: IdSchema,
  targetAspectRatio: z.number().positive(),
  fit: z.enum(["cover", "contain"]),
  focalPolicy: z.enum(["auto", "center", "face", "subject"]),
  textSafeArea: z.enum(["none", "left", "right", "top", "bottom", "center"]).optional(),
  required: z.boolean().default(true),
  assetId: IdSchema.optional(),
  source: z.enum(["user", "project", "cache", "library", "generated", "none"]).default("none"),
  promptHash: z.string().regex(/^[0-9a-f]{64}$/).optional()
});
export type MediaPlacement = z.infer<typeof MediaPlacementSchema>;
/** Deck-wide, post-selection asset plan that prevents unused paid generation. */
export const AssetBundlePlanSchema = VersionedSchema.extend({
  presentationId: IdSchema,
  selectedCompositionHashes: z.record(z.string(), z.string()),
  identities: z.array(AssetIdentitySchema),
  placements: z.array(MediaPlacementSchema),
  resolvedAssetIds: z.array(IdSchema).default([])
});
export type AssetBundlePlan = z.infer<typeof AssetBundlePlanSchema>;

/** Canonical editable node consumed identically by preview and export. */
export const SceneNodeSchema = z.object({
  id: IdSchema,
  kind: z.enum(["text", "shape", "image", "chart", "connector", "group"]),
  sourceIds: z.array(IdSchema),
  bounds: BoundsSchema,
  zIndex: z.number().int(),
  style: z.record(z.string(), z.unknown()),
  content: z.record(z.string(), z.unknown()),
  locked: z.boolean().default(false),
  contentHash: z.string().regex(/^[0-9a-f]{64}$/)
});
export type SceneNode = z.infer<typeof SceneNodeSchema>;
/** Canonical editable page with candidate and relation evidence. */
export const ScenePageSchema = z.object({
  id: IdSchema,
  width: z.number().positive(),
  height: z.number().positive(),
  background: HexColorSchema,
  speakerNotes: z.array(z.string()).default([]),
  nodes: z.array(SceneNodeSchema),
  requiredSourceIds: z.array(IdSchema),
  selectedCandidateId: IdSchema,
  alternativeCandidateIds: z.array(IdSchema),
  pageLinkIds: z.array(IdSchema).default([]),
  riskFlags: z.array(z.enum(["opening", "closing", "full-bleed", "comparison", "reveal", "low-confidence"])).default([])
});
export type ScenePage = z.infer<typeof ScenePageSchema>;
/** Versioned presentation aggregate used as the sole render source. */
export const SceneGraphSchema = VersionedSchema.extend({
  presentationId: IdSchema,
  canvas: z.object({ width: z.number().positive(), height: z.number().positive(), unit: z.literal("pt") }),
  theme: z.record(z.string(), z.unknown()),
  pages: z.array(ScenePageSchema).min(1)
});
export type SceneGraph = z.infer<typeof SceneGraphSchema>;

/** Records actual-office and Scene pixel identities for one page. */
export const RenderedPageEvidenceSchema = z.object({
  pageId: IdSchema,
  sceneImageHash: z.string().regex(/^[0-9a-f]{64}$/),
  pptxImageHash: z.string().regex(/^[0-9a-f]{64}$/),
  differenceScore: z.number().min(0).max(1),
  width: z.number().positive(),
  height: z.number().positive()
});
/** Proves the exported PPTX was rendered and compared page by page. */
export const RenderEvidenceSchema = VersionedSchema.extend({
  presentationId: IdSchema,
  pages: z.array(RenderedPageEvidenceSchema).min(1),
  passed: z.boolean(),
  pptxHash: z.string().regex(/^[0-9a-f]{64}$/)
});
export type RenderEvidence = z.infer<typeof RenderEvidenceSchema>;

/** Normalizes rule and vision failures into repairable semantic issues. */
export const QualityIssueSchema = z.object({
  code: z.string(),
  dimension: z.enum(["Content", "Design", "Coherence", "Export"]),
  severity: z.enum(["warning", "error"]),
  pageId: IdSchema.optional(),
  nodeIds: z.array(IdSchema),
  message: z.string(),
  repairIntent: z.string().optional()
});
/** Versioned delivery gate spanning content, design, coherence, and export. */
export const QualityReportSchema = VersionedSchema.extend({
  presentationId: IdSchema,
  passed: z.boolean(),
  scores: z.object({ Content: z.number(), Design: z.number(), Coherence: z.number(), Export: z.number() }),
  issues: z.array(QualityIssueSchema),
  visualReviewPageIds: z.array(IdSchema),
  visualReviewStatus: z.enum(["not-required", "pending", "passed", "failed"]),
  renderEvidenceHash: z.string().regex(/^[0-9a-f]{64}$/).optional(),
  repairCount: z.number().int().min(0).max(1)
});
export type QualityReport = z.infer<typeof QualityReportSchema>;
