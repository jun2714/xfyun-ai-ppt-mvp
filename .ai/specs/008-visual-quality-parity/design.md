# 008 详细设计

## 1. 架构策略

008 延续 007 的 Clean Architecture，不推翻 Scene Graph 和现有 Port。新增能力作为独立领域对象和服务接入：

```text
PresentationBrief
  → NarrativeArc + NarrativeOutline
  → DeckVisualGrammar + PageDesignIntent + CrossPageConstraint[]
  → CompositionGrammar → CandidateSet[] → DeckSelection
  → AssetBundlePlan → ResolvedAssets
  → SceneGraph
  → HighFidelityRender → QualityReport
  → RepairConstraints → 局部重新求解
  → Final PPTX + Render Evidence
```

AI 继续只输出语义；所有坐标、大小、换行、裁剪和导出由确定性代码处理。

## 2. 领域模型补充

### 2.1 NarrativeArc

```ts
type NarrativeArc = {
  centralOutcome: string;
  sections: NarrativeSection[];
  pageLinks: PageLink[];
};

type NarrativeSection = {
  id: string;
  purpose: string;
  pageIds: string[];
  transition: string;
};

type PageLink = {
  id: string;
  fromPageId: string;
  toPageId: string;
  predicates: PageRelationPredicate[];
};

type PageRelationPredicate =
  | { kind: "preserve"; sourceIds: string[]; properties: Array<"identity" | "relative-order" | "scale-family" | "visual-treatment"> }
  | { kind: "conceal"; sourceIds: string[]; onPageId: string }
  | { kind: "introduce"; sourceIds: string[]; onPageId: string }
  | { kind: "change"; sourceIds: string[]; properties: string[] }
  | { kind: "associate"; leftSourceIds: string[]; rightSourceIds: string[] }
  | { kind: "compare"; sourceIds: string[] }
  | { kind: "order"; sourceIds: string[] };
```

这里使用通用关系谓词，不使用“封面、目录、问答页、揭晓页”等页面角色。谓词只能被编译为 Constraint 和 ScoreFeature，禁止直接选择 Composition Tree、坐标或模板。

### 2.2 AudienceAction

每页可声明观众动作、教师提示和答案可见状态。观众动作是沟通语义，不是可见制作说明。教师提示默认进入 speaker notes，只有明确面向观众的指令才进入页面文字。

### 2.3 DeckVisualGrammar

```ts
type DeckVisualGrammar = {
  typographyScale: TypographyScale;
  semanticPalette: SemanticPalette;
  shapeVocabulary: ShapeVocabulary;
  motifRules: MotifRule[];
  mediaLanguage: MediaLanguage;
  spacingRhythm: SpacingRhythm;
  variationPolicy: VariationPolicy;
};
```

它描述“可以怎样设计”，不保存参考 PPT 的具体形状和坐标。

### 2.4 CrossPageConstraint

```ts
type CrossPageConstraint = {
  pageIds: string[];
  preserve: Array<"visual-identity" | "relative-order" | "baseline" | "scale-family" | "background-treatment">;
  changeSourceIds: string[];
  concealSourceIds: string[];
};
```

用于问题/揭晓、记忆/变化等状态页。求解器共同求解一组页面，而不是逐页孤立选择。

### 2.5 AssetIdentity

```ts
type AssetIdentity = {
  id: string;
  semanticEntityId: string;
  baseAssetId?: string;
  visualIdentityKey: string;
  role: "full-bleed-background" | "scene" | "subject" | "transparent-cutout" | "detail" | "evidence";
  variantIntent?: string;
  reusePolicy: "exact" | "controlled-variant" | "single-use";
};
```

AssetBundlePlanner 先按 `semanticEntityId + visualIdentityKey + role` 去重，再决定复用或生成。

## 3. 规划器改造

### 3.1 Narrative Planner

一次调用同时返回大纲、章节和跨页关系。新增确定性验证：

- 页数和引用完整性；
- 每页只承担一个主任务；
- 铺垫页和揭晓页成对；
- 问题页不含答案源；
- 章节首尾连贯；
- 可见文本不含教师制作指令、图片描述或占位符；
- 字数预算根据受众、画布和页数计算。

模型不满足验证时立即失败，不自动付费重试。

### 3.2 Design Planner

一次调用输出 DeckVisualGrammar、PageDesignIntent、CrossPageConstraint 和 AssetIdentity 草案。确定性代码完成：

- 字体存在性和 fallback；
- 色彩对比修正；
- 形状语法归一化；
- 媒体角色校验；
- 跨页约束与 NarrativeArc 对齐；
- 参考文件相关词和复制指令拒绝。

## 4. 构图语法

### 4.1 移除固定四策略上限

保留通用原语，但候选不再受四个枚举模板限制。候选由下列可组合决策生成：

- 视觉锚点：文字、媒体、数据或关系；
- 方向：水平、垂直、径向、环绕、自由重点；
- 分组：并列、层级、集合、序列、映射、覆盖；
- 主次比例：由内容权重和媒体角色求解；
- 装饰层：根据 DeckVisualGrammar 参数化生成；
- 跨页保持项与变化项。

候选的 `strategy` 改为特征集合、Constraint 来源和语法树哈希，避免重新形成四个隐形模板。每次选择必须产生 `LayoutDecisionTrace`，记录输入内容指标、应用约束、候选差异、淘汰原因和最终分数；无法解释来源的布局决策视为错误。

### 4.2 组级求解

对存在 PageLink 的页面建立共同变量：

- 共享实体的相对位置、比例和视觉身份；
- 揭晓页允许显示隐藏节点；
- 状态变化页只改变指定节点；
- 组内保持视觉连续，组间允许节奏变化。

### 4.3 评分

新增：

- focal clarity；
- relation legibility；
- cross-page continuity；
- reveal correctness；
- native-shape contribution；
- media-role fitness；
- silhouette diversity；
- audience-distance readability；
- decorative consistency。

硬约束失败的候选不得进入编辑器。

## 5. 素材解析

1. 收集最终候选中的全部 AssetIdentity。
2. 按视觉身份、用途和变体意图去重。
3. 优先用户素材、项目素材和缓存。
4. 生成背景时使用最终画幅和文字安全区。
5. 生成主体时保留足够留白；透明主体执行抠图或透明度验证。
6. 生成受控变体时必须引用基础身份，不得从纯文本重新创造同一角色。
7. 本地检查分辨率、长宽比、alpha、空白边缘和文件完整性。
8. 将全部新素材缩略图合并进一次视觉复核，检查风格和身份一致性。

## 6. 高保真渲染

新增 `RenderEvidencePort`：

```ts
interface RenderEvidencePort {
  renderScene(scene: SceneGraph): Promise<RenderedDeck>;
  renderPptx(bytes: Uint8Array): Promise<RenderedDeck>;
}
```

- 规则预检查可使用快速 Scene 渲染。
- 最终质量门必须使用 PPTX 实际渲染结果。
- 比较 Scene 渲染与 PPTX 渲染的感知差异；超阈值时阻止导出。
- 使用真实字体测量适配器替换 `ConservativeTextMeasurer`。
- PPTX 文本禁用无边界的自动 shrink；字体变化必须回写 Scene Graph 并重新质检。

## 7. 质量和修复

### 7.1 新增检查

- `ANSWER_LEAKED_BEFORE_REVEAL`
- `CROSS_PAGE_STATE_MISMATCH`
- `VISUAL_IDENTITY_DRIFT`
- `WRONG_MEDIA_ROLE`
- `CUTOUT_BACKGROUND_DIRTY`
- `IMAGE_TOO_LOW_RESOLUTION`
- `PPTX_RENDER_DIVERGENCE`
- `SILHOUETTE_MONOTONY`
- `VISUAL_ANCHOR_MISSING`
- `PRODUCTION_COPY_VISIBLE`

### 7.2 RepairConstraint

质量问题映射为结构化约束，例如“扩大标题区域”“保持三个共享实体不动”“隐藏答案节点”“替换低清素材”“将主体媒体改为背景角色”。

求解器基于旧候选和新增约束重新生成失败页候选。不得只选择已有候选中的下一项。

## 8. 编辑器

008 补齐：

- 8 个方向缩放手柄和旋转；
- 多选、对齐、等距分布和组合；
- 添加/替换/裁剪图片；
- 页面新增、复制、删除和排序；
- 主题字体、语义颜色和形状语言编辑；
- 单页重新设计、单素材重新生成；
- PageLink 页面组提示，避免误删揭晓依赖。

所有操作继续写入 Scene Command，支持 undo/redo 和 revision conflict。

## 9. 失败和成本处理

- Schema 或叙事验证失败：任务失败，保留模型原始响应摘要，不自动重试。
- 图片生成失败：保留可用资产，允许用户手动重试单一素材。
- 视觉复核失败：只生成 RepairConstraint；是否再次调用付费视觉模型由用户主动触发。
- PPTX 渲染失败：禁止交付，报告具体页面和节点。
- 所有缓存键必须包含模型、提示词版本、身份键、角色和目标比例。

## 10. 迁移策略

- 升级协议为 `008.0`，不向 007 模型塞兼容字段。
- Scene Graph 可保留通用节点结构，但新增页面组、资源身份和渲染证据引用。
- `editorial/stage/sequence/mosaic` 只用于读取 007 历史数据；008 新生成不依赖该枚举。
- 旧简化 SVG 联系表保留为快速诊断，不能作为最终质量证据。
- 007 数据通过显式迁移器转换，生产逻辑不得混用两个协议。

## 11. 状态一致性与失效传播

每个产物必须保存 `schemaVersion / revision / contentHash / upstreamHashes`。修改上游后按以下规则失效：

| 修改 | 必须失效 | 可以保留 |
|---|---|---|
| Brief | 大纲以后全部产物 | 用户上传原始素材 |
| 大纲可见内容 | 设计、候选、素材放置、Scene、质量、导出 | 未绑定内容的项目素材 |
| PageLink/约束 | 关联页候选、Scene、质量、导出 | 不受影响页素材 |
| 候选选择 | 对应素材放置、Scene、质量、导出 | 相同身份和角色的已解析素材 |
| 图片替换 | Scene、质量、导出 | 大纲、设计、候选 |
| Scene Command | 质量、RenderEvidence、导出 | 规划产物 |
| 主题 Token | 全页 Scene 样式、质量、RenderEvidence、导出 | 文案和素材身份 |

仓储更新必须原子提交。Job 失败时不能留下“部分新产物 + 旧质量报告”的混合状态。

## 12. 错误模型

所有错误使用稳定错误码并区分：

- `INPUT_*`：Brief 或用户素材不合法；
- `MODEL_*`：无效 JSON、引用错误、生产语言泄漏；
- `NARRATIVE_*`：页数、章节、关系、答案状态错误；
- `COMPOSITION_*`：无有效候选、约束冲突、无法放置；
- `ASSET_*`：生成、下载、透明度、分辨率、角色错误；
- `SCENE_*`：revision conflict、节点引用和命令错误；
- `QUALITY_*`：规则或视觉质量门失败；
- `EXPORT_*`：PPTX 写入、字体、渲染、WPS/PowerPoint 兼容问题；
- `BUDGET_*`：调用次数或预算上限超出。

错误必须包含 stage、presentationId、pageId/nodeId（适用时）、是否产生费用、是否允许用户手动重试。禁止用同一个 500 错误掩盖全部失败原因。

## 13. 可观察性

每个 Job 记录阶段耗时、输入/输出哈希、模型、token、图片调用数、缓存命中、人民币估算、失败码和最终产物引用。日志禁止包含 API Key、完整 `.env`、用户隐私文件内容和图片 base64。

`LayoutDecisionTrace`、`AssetResolutionTrace`、`QualityEvidence` 必须可在后台调试接口读取，但不作为观众可见文字进入 PPT。

## 14. 代码注释

实现必须遵守 `guardrails.md` 的注释合同：公开领域协议和 Port 使用 TSDoc；求解器、失效传播、成本控制、媒体角色和跨页约束必须解释不变量与取舍；禁止用注释掩盖过长函数或重复代码。
