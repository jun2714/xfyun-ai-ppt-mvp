# 007 实施顺序与停止线

## Phase 0：冻结错误架构

- 禁止继续向 `layout-core` 增加 role 分支、比例或渲染函数。
- 修复会破坏现有数据的入口，保留最基础项目、模型和仓储代码。
- 建立 007 ADR，所有新代码只能依赖新领域协议。

验收：生产 diff 中不再出现新的 `role ===` 布局判断。

## Phase 1：领域协议

- 建立 presentation-model。
- 实现 NarrativeOutline、DeckDesignPlan、PageDesignIntent、CompositionTree、SceneGraph schema。
- 添加 schema migration policy，但不添加 006 legacy 字段。
- 使用任意内容夹具验证多个 ContentGroup 不丢失。

验收：一页包含标题、说明、三个标注和两张图时，全部能进入领域模型。

## Phase 2：设计规划

- 新增 DesignPlannerPort。
- DMX 文本模型一次返回整份 Deck Design Plan 和 Page Design Intent。
- 添加结构化校验、引用校验、制作语言隔离。
- 保存设计计划，允许查看但不要求用户二次确认。

验收：三个陌生主题产生不同 design intent，生产代码无主题分支。

## Phase 3：构图原语与求解器

- 实现 Stack、Grid、Overlay、Flow、Anchor、Group。
- 实现真实字体测量适配器。
- 实现 2–4 个候选生成、硬约束淘汰和软评分。
- 实现跨页重复惩罚和候选保存。

验收：宽屏、方形、竖屏均无固定坐标；同页可切换候选。

## Phase 4：Scene Graph 与无图垂直切片

- 将选中候选编译为 Scene Graph。
- 网页预览读取 Scene Graph。
- PPTX adapter 读取同一 Scene Graph。
- 先完成纯文本、形状、表格、流程和图表页面。

验收：预览和 PPTX 指纹一致，文本与形状可编辑。

## Phase 5：素材规划

- 建立 MediaRequest、MediaPlacement 和 AssetPlan。
- 实现用户素材、缓存、图片模型的解析优先级。
- 背景、主体、抠图、细节和证据分别处理。
- 图片调用发生在候选选中之后。

验收：未放置候选不调用模型；每个生成图片都被 Scene Graph 引用。

## Phase 6：质量闭环

- 规则检查全部页面。
- 渲染联系表。
- 高风险/低分页面批量发送视觉模型。
- 实现最多一次的结构化局部修复。

验收：遮挡、低对比、错误裁剪、页面过度相似可以被发现；无自动付费重试。

## Phase 7：编辑器

- 类 PPT 三栏界面。
- Command、undo/redo、revision conflict。
- 文本编辑、元素移动缩放、换图、候选换版、单页重新设计。

验收：用户不用重新生成整份 PPT 即可修正一页。

## Phase 8：真实验收

- 使用至少三类外部测试 Brief，其中至少一类开发时未知。
- 每类生成完整 Deck、联系表和 PPTX。
- 在 WPS 与 PowerPoint 打开检查。
- 记录模型调用数、图片数、缓存命中和费用。

## 停止线

以下任一出现立即停止实现并回到 Design：

- 新增具体场景判断；
- 新增 role 到坐标映射；
- 模型输出代码直接执行；
- 构图前批量生图；
- 预览和导出使用不同布局模型；
- 只用越界检查宣布视觉合格；
- 为通过案例测试而增加案例关键词。
