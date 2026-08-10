# 008 防硬编码与代码注释规范

## 1. 目的

本文件用于防止 008 在实现过程中再次退化为固定模板、固定页面槽或业务分支。所有生产代码、测试和评审必须使用同一判断标准。

## 2. 什么是禁止的写死

### 2.1 业务到布局的直接映射

以下形式一律禁止：

```ts
if (brief.usageContext.includes("家长会")) return parentMeetingLayout;
if (pageIndex === 0) return coverCoordinates;
switch (page.purpose) { case "reveal": return revealTemplate; }
const layouts = { animal: [...], safety: [...], report: [...] };
```

禁止条件包括但不限于：主题、受众、年龄、班级、场景、标题关键词、章节名称、页码、页面角色、测试用例名称和参考 PPT 页码。

### 2.2 固定页面答案

禁止在生产代码保存：

- 完整页面坐标数组；
- 固定标题区、正文区和图片区三槽结构；
- “第 N 页使用某构图”的映射；
- 某一种关系对应一棵固定 Composition Tree；
- 从参考文件提取的颜色、字体、尺寸、媒体、母版或布局；
- 为通过基准测试专门增加的关键词、分支或 fixture 数据。

### 2.3 隐形模板

即使没有 `templateId`，下列实现仍属于模板：

- 有限枚举策略内部各自返回固定树；
- `setup/reveal/profile/agenda` 等语义名称直接调用固定构图函数；
- 仅替换文字和图片，元素数量与几何结构永久不变；
- 用多个固定坐标集合随机挑选制造“多样性”；
- 把参考 PPT 截图作为背景后覆盖可编辑文字。

## 3. 允许固定的工程约束

以下内容可以集中配置并测试：

- PPTX 画布规范和单位换算；
- 支持的图片尺寸网格、MIME 和文件大小；
- 字号、边距、对比度、清晰度和可点击区域下限；
- API 超时、最大页数、候选搜索上限和并发上限；
- Stack、Grid、Flow、Overlay、Anchor 等原语的确定性算法；
- Scene Graph、错误码和协议版本；
- PowerPoint/WPS 兼容性规则；
- 付费调用次数上限和禁止自动重试。

这些约束必须与具体主题、场景、页码和文案无关。

## 4. 正确的排版决策路径

唯一允许的生产路径：

```text
内容长度/数量/层级
  + 内容关系谓词
  + 媒体角色/比例/焦点
  + 画布/字体/安全边距
  + Deck Visual Grammar
  + 跨页保持与变化约束
  → 通用原语组合搜索
  → 硬约束淘汰
  → 软评分与 Deck 级选择
  → LayoutDecisionTrace
```

任何布局结果都必须能从上述输入追溯。无法生成 Trace 的候选不得入选。

## 5. 关系谓词隔离

`PageRelationPredicate` 只能被下列接口消费：

```ts
interface RelationConstraintCompiler {
  compile(predicate: PageRelationPredicate): Constraint[];
}

interface RelationScoreFeatureFactory {
  create(predicate: PageRelationPredicate): ScoreFeature[];
}
```

禁止关系编译器返回 Bounds、CompositionNode、SceneNode、模板名称或坐标。通过 TypeScript 类型和架构测试同时限制。

## 6. 几何代码位置

生产环境允许出现几何计算的目录只有：

- `packages/design-language`：通用 token 和可读性阈值；
- `packages/composition-engine`：原语求解和约束；
- `packages/scene-graph`：已求解几何的版本化存储与编辑命令；
- `packages/pptx-export`：单位转换，不做布局决定；
- 编辑器交互层：用户拖拽产生的坐标。

Application、Planner、模型 Adapter、HTTP Route 和业务领域对象中禁止出现页面坐标决策。

测试 fixture 可以包含坐标，但必须位于测试文件或 fixture 目录，并明确标注仅用于验证。

## 7. AST 架构守卫

仅使用正则扫描不够。008 必须增加 TypeScript AST 检查：

- 检测场景/标题/页码/关系字段参与布局函数分派；
- 检测生产代码中的坐标对象数组和固定 Composition Tree 常量；
- 检测 Planner 返回 Bounds 或 CompositionNode；
- 检测 RelationConstraintCompiler 返回布局对象；
- 检测 renderer/exporter 调用 candidate selection 或修改 bounds；
- 检测 Domain/Application 依赖 Infrastructure、Web 框架、数据库或 PPTX 库；
- 检测参考文件名、测试主题和禁止业务词进入生产代码；
- 检测 `eval`、`new Function`、动态执行模型输出和 HTML/SVG 生产代码注入。

架构守卫失败必须使 CI 失败。

## 8. 防过拟合测试

### 8.1 属性测试

随机改变以下变量后，系统仍应产生合法且不同的求解结果：

- 标题和正文长度；
- 内容组数量和顺序；
- 图片比例和是否存在图片；
- 画布比例；
- 字体和字号下限；
- 关系谓词组合；
- 页面顺序和章节数量。

### 8.2 变形测试

- 仅改变主题词，布局不能因为关键词命中而突变。
- 同一内容增加一项后，系统必须重新求解，而不是溢出旧槽位。
- 同一 Brief 改成竖版后，不能沿用横版坐标。
- 删除图片后，页面应重排为无图方案，而不是留下空槽。
- 问题页与揭晓页交换状态后，可见节点必须按谓词变化。

### 8.3 未见 Brief

真实验收 Brief 只能存在于测试输入和验收记录，不能提交进生产分支判断。每次发布至少增加一个此前未使用的 Brief。

## 9. 代码注释合同

用户要求代码包含注释，但注释必须提高可维护性，不能制造噪音。

### 9.1 必须注释

- 所有导出的领域 Schema、领域服务、Use Case、Port 和 Adapter 公共入口使用 TSDoc，说明职责、输入不变量、输出和失败方式。
- 约束求解、候选停止条件、评分归一化、跨页共同变量和失效传播必须说明“为什么这样做”。
- 付费调用边界、幂等、缓存键、禁止自动重试和费用记录必须说明成本不变量。
- 媒体角色转换、透明素材处理、图片复用和身份一致性必须说明不可违反的规则。
- PPTX 与网页渲染存在兼容性取舍时必须说明原因和验证方法。
- 临时 workaround 必须包含原因、影响范围、移除条件和关联 issue/spec。

### 9.2 禁止的注释

```ts
// i 加一
i += 1;

// 如果是家长会就用家长会模板
if (...) { ... }

// TODO 后面再修
```

禁止：

- 重复代码字面含义；
- 用注释合理化业务硬编码；
- 没有责任人、条件或规格引用的永久 TODO；
- 大段注释掉的旧代码；
- 与实现不一致的过期注释；
- 给每一行机械生成注释。

### 9.3 注释格式

```ts
/**
 * 将跨页关系编译为纯约束，不返回任何布局树。
 * 这样可以防止“页面语义 → 固定模板”的隐形映射。
 * @throws RelationReferenceError 当谓词引用不存在的页面或内容源。
 */
```

同一文件使用一致语言。名称表达“做什么”，注释解释“为什么、约束和风险”。

### 9.4 注释验收

- 自动检查导出公共 API 是否有 TSDoc；
- Code Review 抽查求解器、成本、并发、错误和渲染代码的注释准确性；
- 修改行为时必须同步修改相关注释和测试；
- 注释错误与代码错误同等处理。

## 10. 合并门槛

涉及规划、构图、素材、Scene、质检或导出的 PR 必须附带：

- 对应 008 requirement/task；
- 新增或修改的不变量；
- 防硬编码说明；
- 单元/属性/集成测试证据；
- 是否影响付费调用；
- 是否改变最终 PPTX 渲染；
- 必要代码注释。

缺少任何一项不得合并。
