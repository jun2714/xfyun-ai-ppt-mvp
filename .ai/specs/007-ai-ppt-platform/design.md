# 007 详细架构设计

## 1. 架构结论

停止扩展当前 `layout-core`。新系统使用 Clean Architecture，依赖方向为：

`Domain ← Application ← Adapters/Infrastructure ← Interfaces`

核心拆成六个独立能力：

1. Narrative Planning
2. Design Planning
3. Composition Solving
4. Asset Planning
5. Scene Rendering
6. Quality Evaluation

任何模块不得同时负责两种以上主要能力。

## 2. 领域数据流

```text
PresentationBrief
  → NarrativeOutline
  → DeckDesignPlan + PageDesignIntent[]
  → CompositionCandidate[]
  → SelectedComposition
  → AssetPlan
  → ResolvedSceneGraph
  → QualityReport
  → ExportArtifact
```

每一步单独版本化、可持久化、可重放。下游产物必须记录上游内容哈希。

## 3. Narrative Outline

大纲只表达叙事，不表达布局：

```ts
type NarrativePage = {
  id: string;
  purpose: string;
  headline: string;
  message: string;
  contentGroups: ContentGroup[];
  speakerNotes: string[];
  evidenceRequests: EvidenceRequest[];
  continuityLinks: string[];
};
```

`ContentGroup` 支持 paragraph、list、comparison、sequence、quote、metric、question、answer、caption、table、chart-data、annotation。页面允许多个 group，不再压成一个 block。

## 4. Deck Design Plan

Deck 级别统一视觉语言：

```ts
type DeckDesignPlan = {
  designSeed: string;
  tone: string[];
  typography: TypographyIntent;
  palette: PaletteIntent;
  shapeLanguage: ShapeLanguageIntent;
  illustrationDirection?: IllustrationDirection;
  densityTarget: "airy" | "balanced" | "dense";
  rhythm: RhythmIntent;
  consistencyRules: ConsistencyRule[];
};
```

模型给出意图；Design Token Resolver 将其转换为满足对比度和可读性的确定性 token。

## 5. Page Design Intent

模型不选模板，只描述这一页如何沟通：

```ts
type PageDesignIntent = {
  pageId: string;
  focalMessage: string;
  hierarchy: HierarchyItem[];
  groups: DesignGroup[];
  relationships: Relationship[];
  visualStrategy: "none" | "background" | "subject" | "evidence" | "gallery" | "diagram";
  balance: "symmetric" | "asymmetric" | "centered" | "directional";
  flow: "vertical" | "horizontal" | "radial" | "sequence" | "free-emphasis";
  density: "low" | "medium" | "high";
  emphasis: EmphasisInstruction[];
  mediaRequests: MediaRequest[];
  avoid: string[];
};
```

该协议不得出现 x/y/width/height、CSS class 或模板 ID。

## 6. 通用布局原语

构图树只使用通用排版原语：

- Canvas
- SafeArea
- Stack
- Flow
- Grid
- Overlay
- Anchor
- Align
- Distribute
- Frame
- Text
- Shape
- Image
- Chart
- Connector
- Group

原语相当于 PPT/WPS 的基础排版能力，不对应家长会、动物课或任何页面模板。

```ts
type CompositionNode =
  | StackNode
  | GridNode
  | OverlayNode
  | FlowNode
  | AnchorNode
  | TextLeaf
  | ShapeLeaf
  | MediaLeaf;
```

## 7. 候选构图与评分

每页根据 Design Intent 生成 2–4 个候选。候选差异来自原语组合、视觉位置、主次比例和内容分组，不来自业务模板。

评分分两层：

### 7.1 硬约束

- 无越界；
- 无不可接受重叠；
- 字号不低于 token 下限；
- 所有必需内容和媒体都被放置；
- 背景与文字对比达标；
- 图片比例和裁剪满足 Media Request；
- 问题与答案状态正确；
- 不出现制作说明。

硬约束失败直接淘汰。

### 7.2 软评分

- 视觉层级；
- 对齐和间距一致性；
- 留白；
- 视觉平衡；
- 内容密度；
- 图片与论点关联；
- 全 Deck 重复惩罚；
- Deck 风格一致性；
- 阅读顺序；
- 页面功能与表达方式匹配度。

选择最高分候选，同时保留其他候选供编辑器一键换版。

## 8. 素材规划

素材规划在候选确定之后执行。

```ts
type MediaPlacement = {
  id: string;
  pageId: string;
  claimIds: string[];
  role: "background" | "subject" | "cutout" | "detail" | "evidence";
  boundsRef: string;
  targetAspectRatio: number;
  fit: "cover" | "contain";
  focalPolicy: FocalPolicy;
  textSafeArea?: SafeAreaIntent;
};
```

解析顺序：

1. 用户绑定素材；
2. 当前项目已有素材；
3. 相同 prompt/continuity 哈希缓存；
4. 合法图库适配器；
5. 图片模型生成；
6. 无图仍能成立的原生形状方案。

背景图必须附带安全区、文字遮罩和焦点信息。前景图不得自动升级为背景；背景图不得自动缩成小卡片。

## 9. Scene Graph

Scene Graph 是唯一渲染真相：

```ts
type SceneGraph = {
  deckId: string;
  revision: number;
  canvas: CanvasSpec;
  theme: ResolvedDesignTokens;
  pages: ScenePage[];
};
```

每个节点包含独立 ID、语义来源、边界、样式、层级、编辑锁和内容哈希。网页预览、编辑器、PNG 渲染、质量检测和 PPTX 导出全部读取它。

## 10. 渲染与导出

- 文本：原生文本框；
- 形状、线条、连接器：原生 PPTX；
- 表格、图表：优先原生对象；
- AI 图片：独立 media；
- 整页位图：只允许作为用户明确选择的不可编辑模式，不作为默认路径。

PPTX adapter 不做布局决策，只翻译 Scene Graph。

## 11. 质量闭环

### 11.1 全页规则检查

字体度量使用真实字体测量，不使用字符数近似作为最终判断。检查边界、碰撞、对比、密度、裁剪、引用完整性、重复度和导出能力。

### 11.2 视觉模型检查

进入视觉复核的页面：

- 封面和结束页；
- 章节切换；
- 全屏背景；
- 对比、问题/揭晓；
- 规则评分低于阈值；
- 与前后页构图相似度过高。

将这些页面组成联系表，一次请求评价 Content、Design、Coherence，不逐页调用。

### 11.3 修复

视觉模型只能返回结构化问题和修复意图，不能返回坐标。系统重新生成失败页候选，最多一次。图片不受影响时不得重新生图。

## 12. 编辑器

界面采用主流 PPT 结构：

- 顶部：撤销/重做、文本、形状、图片、主题、导出；
- 左侧：页面缩略图与排序；
- 中间：固定比例画布；
- 右侧：所选元素属性、页面设计意图、候选版式；
- 底部：缩放、页码、质量状态。

支持：文本编辑、拖拽缩放、层级、换图、裁剪、重新生成单图、切换候选布局、重新设计单页、复制/删除/新增页面。

所有操作使用 Command 记录，支持 undo/redo 和 revision conflict。

## 13. 包与目录

```text
packages/
  presentation-model/      # 领域协议和不变量
  design-language/         # Design Intent、token 解析
  composition-engine/      # 原语、候选生成、约束求解
  scene-graph/             # 唯一渲染模型
  quality-engine/          # 规则评分与视觉复核协议
  pptx-export/             # Scene Graph → PPTX

apps/api/src/
  domain/
    presentation/
    design/
    composition/
    assets/
    quality/
  application/
    use-cases/
    ports/
  infrastructure/
    models/dmx/
    persistence/
    rendering/
    pptx/
  interfaces/http/

apps/web/src/
  features/brief/
  features/outline/
  features/editor/
  features/export/
  entities/scene/
  shared/
```

## 14. 现有代码处置

- `packages/layout-core`：停止扩展；新 composition engine 通过验收后删除。
- `storyboard-planner.service.ts`：由 Narrative → Design Planning 用例替代。
- `design-system`：迁移为 design-language；删除 children/adults 两分支 token。
- `preview-page.tsx`：替换为 Scene Graph 编辑器。
- `pptxgenjs-exporter.adapter.ts`：保留技术适配价值，但输入改为 Scene Graph。
- DMX adapters、项目仓储、任务框架、成本策略可以保留并通过 Port 接入。

禁止为了兼容 006 在新领域模型中加入 legacy 字段。
