# 007 API 与作业协议

## 1. 核心资源

- `Presentation`
- `NarrativeOutline`
- `DeckDesignPlan`
- `CompositionSet`
- `SceneGraphRevision`
- `Asset`
- `QualityReport`
- `Export`
- `UsageLedger`

## 2. 生成接口

```text
POST /api/v1/presentations
POST /api/v1/presentations/:id/outline-jobs
PUT  /api/v1/presentations/:id/outline
POST /api/v1/presentations/:id/outline/confirm
POST /api/v1/presentations/:id/design-jobs
GET  /api/v1/presentations/:id/design
POST /api/v1/presentations/:id/composition-jobs
GET  /api/v1/presentations/:id/compositions
POST /api/v1/presentations/:id/asset-jobs
POST /api/v1/presentations/:id/quality-jobs
GET  /api/v1/presentations/:id/scene
POST /api/v1/presentations/:id/exports
```

设计、构图、素材、质量不得合并为一个不可观察的黑盒 job。

## 3. 编辑接口

```text
POST /api/v1/presentations/:id/commands
POST /api/v1/presentations/:id/undo
POST /api/v1/presentations/:id/redo
POST /api/v1/presentations/:id/pages/:pageId/select-composition
POST /api/v1/presentations/:id/pages/:pageId/redesign-jobs
POST /api/v1/presentations/:id/media/:placementId/regenerate-jobs
```

每个写接口携带 `expectedRevision` 和 `idempotencyKey`。

## 4. Job 状态

```ts
type JobStage =
  | "queued"
  | "planning"
  | "generating_candidates"
  | "scoring"
  | "resolving_assets"
  | "rendering"
  | "rule_quality"
  | "visual_quality"
  | "repairing"
  | "exporting"
  | "completed"
  | "failed";
```

失败结果必须包含阶段、错误码、是否产生费用、可否无费用重试。服务端禁止自动发起付费重试。

## 5. 用量账本

每次模型请求记录：

- provider/model；
- purpose；
- project/page/placement；
- request hash；
- input/output tokens；
- 图片数量与尺寸；
- 估算和实际费用；
- cache hit；
- success/failure；
- parent job。

账本只进入后台统计，不在用户生成流程展示费用确认。

## 6. 版本规则

- 所有资源包含 `schemaVersion`、`revision`、`contentHash`。
- 上游 revision 改变时，下游资源显式 stale。
- stale 资源不得导出，也不得静默升级。
- 单页修改只失效该页 Scene/Quality 和依赖素材，不失效无关页面。
