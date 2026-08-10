# SparkDeck 007 架构

依赖方向：`Interfaces → Application → Domain/Ports`。Infrastructure 通过组合根实现 Port，领域层不引用 Fastify、DMX、Sharp、PptxGenJS 或文件系统类型。

核心数据流：

`PresentationBrief → NarrativeOutline → DeckDesignPlan + PageDesignIntent[] → CompositionCandidate[] → AssetPlan → SceneGraph → QualityReport → PPTX`

每个产物都带有 `schemaVersion`、`revision`、`contentHash` 和上游哈希，便于重放、并发检查和定位失效产物。

## 关键边界

- Narrative Planner：一次调用生成整份大纲，只写观众可见内容和讲者备注。
- Design Planner：一次调用生成整稿视觉语言和每页表达意图，不输出坐标。
- Composition Engine：用通用原语生成 2–4 个候选，先做硬约束，再做软评分和跨页重复惩罚。
- Asset Planning：候选选中后才建立 Media Placement；缓存键由最终提示词和连续性要求决定。
- Scene Graph：网页预览、编辑器、质量检查和 PPTX Adapter 的唯一输入。
- Quality：全部页面走规则检查；封面、结尾、全屏图、对比/揭晓和低分页组成一张联系表，最多进行一次多模态检查。
- PPTX Adapter：只翻译 Scene Graph，不参与布局决策；文本、形状、图表和图片保持独立对象。

生产停止线由测试扫描：不得出现具体场景到布局的分发、页面角色到坐标的映射、首块内容特判、模型代码执行或 vendored 第三方运行时。
