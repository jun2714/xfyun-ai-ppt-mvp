import { createHash } from "node:crypto";
import { z } from "zod";

export const SCHEMA_VERSION = "007.2" as const;
export const IdSchema = z.string().trim().min(1);
export const HexColorSchema = z.string().regex(/^#[0-9a-f]{6}$/i);
export const VersionedSchema = z.object({
  schemaVersion: z.literal(SCHEMA_VERSION),
  revision: z.number().int().nonnegative(),
  contentHash: z.string().regex(/^[0-9a-f]{64}$/),
  upstreamHashes: z.record(z.string(), z.string().regex(/^[0-9a-f]{64}$/)).default({})
});
export type Versioned = z.infer<typeof VersionedSchema>;
export const hashContent = (value: unknown) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
export const versioned = <T>(value: T, revision = 0, upstreamHashes: Record<string, string> = {}) => ({
  ...value,
  schemaVersion: SCHEMA_VERSION,
  revision,
  contentHash: hashContent(value),
  upstreamHashes
});

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

export const ContentKindSchema = z.enum([
  "paragraph", "list", "comparison", "sequence", "quote", "metric", "question", "answer",
  "caption", "table", "chart-data", "annotation"
]);
export const ContentGroupSchema = z.object({
  id: IdSchema,
  kind: ContentKindSchema,
  label: z.string().trim().optional(),
  text: z.string().trim().optional(),
  items: z.array(z.string().trim().min(1)).optional(),
  rows: z.array(z.array(z.union([z.string(), z.number()]))).optional(),
  claimIds: z.array(IdSchema).default([]),
  required: z.boolean().default(true)
}).superRefine((group, ctx) => {
  if (!group.text && !group.items?.length && !group.rows?.length) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: "content group is empty" });
  }
});
export type ContentGroup = z.infer<typeof ContentGroupSchema>;

export const NarrativePageSchema = z.object({
  id: IdSchema,
  purpose: z.string().trim().min(1),
  headline: z.string().trim().min(1),
  message: z.string().trim().min(1),
  contentGroups: z.array(ContentGroupSchema).min(1),
  speakerNotes: z.array(z.string()).default([]),
  evidenceRequests: z.array(z.object({
    id: IdSchema,
    description: z.string().min(1),
    required: z.boolean().default(false)
  })).default([]),
  continuityLinks: z.array(IdSchema).default([])
});
export type NarrativePage = z.infer<typeof NarrativePageSchema>;
export const NarrativeOutlineSchema = VersionedSchema.extend({
  briefId: IdSchema,
  pages: z.array(NarrativePageSchema).min(1),
  confirmedAt: z.string().datetime().nullable().default(null)
}).superRefine((outline, ctx) => {
  const ids = outline.pages.map((page) => page.id);
  if (new Set(ids).size !== ids.length) ctx.addIssue({ code: z.ZodIssueCode.custom, message: "page ids must be unique" });
});
export type NarrativeOutline = z.infer<typeof NarrativeOutlineSchema>;

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
    mood: z.string().min(1),
    background: HexColorSchema,
    surface: HexColorSchema,
    text: HexColorSchema,
    primary: HexColorSchema,
    secondary: HexColorSchema,
    accent: HexColorSchema,
    muted: HexColorSchema
  }),
  shapeLanguage: z.object({
    character: z.string().min(1),
    cornerStyle: z.enum(["sharp", "soft", "round"]),
    strokeStyle: z.enum(["none", "subtle", "expressive"]),
    motif: z.string().trim().min(1)
  }),
  illustrationDirection: z.string().trim().optional(),
  densityTarget: z.enum(["airy", "balanced", "dense"]),
  rhythm: z.object({
    variation: z.enum(["subtle", "moderate", "strong"]),
    continuity: z.array(z.string()).min(1)
  }),
  consistencyRules: z.array(z.string()).min(1)
});
export type DeckDesignPlan = z.infer<typeof DeckDesignPlanSchema>;

export const MediaRequestSchema = z.object({
  id: IdSchema,
  claimIds: z.array(IdSchema),
  role: z.enum(["background", "subject", "cutout", "detail", "evidence"]),
  description: z.string().trim().min(1),
  fit: z.enum(["cover", "contain"]),
  focalPolicy: z.enum(["auto", "center", "face", "subject"]),
  textSafeArea: z.enum(["none", "left", "right", "top", "bottom", "center"]).optional(),
  required: z.boolean().default(true),
  continuityKey: z.string().trim().optional()
});
export type MediaRequest = z.infer<typeof MediaRequestSchema>;

export const PageDesignIntentSchema = z.object({
  pageId: IdSchema,
  focalMessage: z.string().min(1),
  hierarchy: z.array(z.object({ contentGroupId: IdSchema, priority: z.number().int().min(1).max(5) })).min(1),
  groups: z.array(z.object({
    id: IdSchema,
    contentGroupIds: z.array(IdSchema).min(1),
    treatment: z.enum(["plain", "emphasis", "paired", "progressive", "evidence", "callout"])
  })).min(1),
  relationships: z.array(z.object({
    from: IdSchema,
    to: IdSchema,
    kind: z.enum(["sequence", "contrast", "supports", "reveals", "belongs"])
  })).default([]),
  visualStrategy: z.enum(["none", "background", "subject", "evidence", "gallery", "diagram"]),
  balance: z.enum(["symmetric", "asymmetric", "centered", "directional"]),
  flow: z.enum(["vertical", "horizontal", "radial", "sequence", "free-emphasis"]),
  density: z.enum(["low", "medium", "high"]),
  emphasis: z.array(z.object({
    targetId: IdSchema,
    strength: z.enum(["low", "medium", "high"]),
    reason: z.string().min(1)
  })).default([]),
  mediaRequests: z.array(MediaRequestSchema).default([]),
  avoid: z.array(z.string()).default([])
}).strict().superRefine((value, ctx) => {
  const forbidden = /(^|[^a-z])(x|y|width|height|css|html|svg|tailwind|pptx|templateId|layoutId)([^a-z]|$)/i;
  if (forbidden.test(JSON.stringify(value))) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: "design intent contains production or coordinate language" });
  }
});
export type PageDesignIntent = z.infer<typeof PageDesignIntentSchema>;

export const PrimitiveKindSchema = z.enum([
  "Canvas", "SafeArea", "Stack", "Grid", "Flow", "Overlay", "Anchor", "Align", "Distribute",
  "Frame", "Group", "Text", "Shape", "Image", "Chart", "Connector"
]);
export type PrimitiveKind = z.infer<typeof PrimitiveKindSchema>;
export type CompositionNode = {
  id: string;
  kind: PrimitiveKind;
  sourceIds: string[];
  children?: CompositionNode[];
  props: Record<string, unknown>;
};
export const CompositionNodeSchema = z.lazy(() => z.object({
  id: IdSchema,
  kind: PrimitiveKindSchema,
  sourceIds: z.array(IdSchema),
  children: z.array(CompositionNodeSchema).optional(),
  props: z.record(z.string(), z.unknown()).default({})
})) as unknown as z.ZodType<CompositionNode>;
export const BoundsSchema = z.object({
  x: z.number().finite(),
  y: z.number().finite(),
  width: z.number().positive(),
  height: z.number().positive()
});
export type Bounds = z.infer<typeof BoundsSchema>;
export const CompositionCandidateSchema = z.object({
  id: IdSchema,
  pageId: IdSchema,
  strategy: z.enum(["editorial", "stage", "sequence", "mosaic"]),
  tree: CompositionNodeSchema,
  score: z.number(),
  hardFailures: z.array(z.string()),
  scoreBreakdown: z.record(z.string(), z.number()),
  silhouette: z.string().min(1),
  selected: z.boolean().default(false)
});
export type CompositionCandidate = z.infer<typeof CompositionCandidateSchema>;

export const MediaPlacementSchema = z.object({
  id: IdSchema,
  pageId: IdSchema,
  requestId: IdSchema,
  claimIds: z.array(IdSchema),
  role: z.enum(["background", "subject", "cutout", "detail", "evidence"]),
  boundsRef: IdSchema,
  targetAspectRatio: z.number().positive(),
  fit: z.enum(["cover", "contain"]),
  focalPolicy: z.enum(["auto", "center", "face", "subject"]),
  textSafeArea: z.enum(["none", "left", "right", "top", "bottom", "center"]).optional(),
  required: z.boolean().default(true),
  continuityKey: z.string().optional(),
  assetId: IdSchema.optional(),
  source: z.enum(["user", "project", "cache", "library", "generated", "none"]).default("none"),
  promptHash: z.string().regex(/^[0-9a-f]{64}$/).optional()
});
export type MediaPlacement = z.infer<typeof MediaPlacementSchema>;
export const AssetPlanSchema = VersionedSchema.extend({
  presentationId: IdSchema,
  selectedCompositionHashes: z.record(z.string(), z.string()),
  placements: z.array(MediaPlacementSchema),
  resolvedAssetIds: z.array(IdSchema).default([])
});
export type AssetPlan = z.infer<typeof AssetPlanSchema>;

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
  riskFlags: z.array(z.enum(["opening", "closing", "full-bleed", "comparison", "reveal", "low-confidence"])).default([])
});
export type ScenePage = z.infer<typeof ScenePageSchema>;
export const SceneGraphSchema = VersionedSchema.extend({
  presentationId: IdSchema,
  canvas: z.object({ width: z.number().positive(), height: z.number().positive(), unit: z.literal("pt") }),
  theme: z.record(z.string(), z.unknown()),
  pages: z.array(ScenePageSchema).min(1)
});
export type SceneGraph = z.infer<typeof SceneGraphSchema>;

export const QualityIssueSchema = z.object({
  code: z.string(),
  dimension: z.enum(["Content", "Design", "Coherence", "Export"]),
  severity: z.enum(["warning", "error"]),
  pageId: IdSchema.optional(),
  nodeIds: z.array(IdSchema),
  message: z.string(),
  repairIntent: z.string().optional()
});
export const QualityReportSchema = VersionedSchema.extend({
  presentationId: IdSchema,
  passed: z.boolean(),
  scores: z.object({ Content: z.number(), Design: z.number(), Coherence: z.number(), Export: z.number() }),
  issues: z.array(QualityIssueSchema),
  visualReviewPageIds: z.array(IdSchema),
  visualReviewStatus: z.enum(["not-required", "pending", "passed", "failed"]),
  repairCount: z.number().int().min(0).max(1)
});
export type QualityReport = z.infer<typeof QualityReportSchema>;
