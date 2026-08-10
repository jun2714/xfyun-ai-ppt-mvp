# SparkDeck 007

面向幼儿园全部演示场景的 AI PPT 生成与编辑平台。项目使用自研 TypeScript 架构；Presenton、Gamma、PPTAgent 等只作为流程研究依据，不是运行时依赖。

## 产品流程

`基本信息 → 大纲生成/编辑/确认 → 整稿设计意图 → 每页 2–4 个构图候选 → 最终候选素材计划 → Scene Graph → 质量检查 → 在线编辑/PPTX`

- 模型只生成叙事内容和设计意图，不生成坐标、CSS、HTML、SVG 或 PPTX 代码。
- Stack、Grid、Flow、Overlay、Anchor 等通用原语负责候选构图和约束求解。
- 图片只在候选选中后生成，并按最终图片框比例选择横图、竖图或方图。
- 网页预览、编辑命令、质量检查和 PPTX 导出共同读取 Scene Graph。
- 规则检查覆盖全部页面；高风险页合成一张联系表，最多调用一次多模态模型。

## 目录

- `packages/presentation-model`：007 领域协议、Schema 和不变量。
- `packages/design-language`：设计意图到可读 Design Token。
- `packages/composition-engine`：通用原语、候选求解、硬约束和跨页评分。
- `packages/asset-planning`：候选后的素材放置、提示词与图片尺寸选择。
- `packages/scene-graph`：预览、编辑和导出的唯一事实来源。
- `packages/quality-engine`：Content、Design、Coherence、Export 检查及视觉复核协议。
- `packages/pptx-export`：Scene Graph 到原生可编辑 PPTX 对象。
- `apps/api`：应用用例、DMX Adapter、Job、成本与 HTTP 接口。
- `apps/web`：基本信息、大纲确认、生成状态和类 PPT 编辑器。

## 本地运行

复制并填写 `.env` 中的 `DMX_API_KEY`；模型可通过 `DMX_TEXT_MODEL`、`DMX_IMAGE_MODEL`、`DMX_VISION_MODEL` 调整。

```bash
pnpm install
pnpm dev
pnpm verify
```

浏览器打开 `http://127.0.0.1:5173/`。费用只记录在后台用量台账，不显示在生成流程里。

无付费 QA：

```bash
pnpm build
node scripts/qa-scene-export.mjs .runtime/qa
```
