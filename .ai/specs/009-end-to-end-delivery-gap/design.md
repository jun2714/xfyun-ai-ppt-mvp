# 009 目标设计与边界

## 1. 设计目的

009 不再以增加模块数量为目标，而以建立一条可持续交付正常 PPT 的产品主链为目标。所有设计改动必须回答两个问题：

1. 它是否直接提高从用户输入到可用 PPTX 的成功率或质量？
2. 它是否有真实端到端证据，而不只是新的接口、Schema 或测试替身？

如果两个答案都是否定的，不进入 009。

## 2. 端到端主链

```text
Preflight
  → Brief
  → Narrative Draft
  → User-confirmed Outline
  → Design Intent
  → Adaptive Composition
  → Selected Asset Plan
  → Asset Resolution
  → Scene Graph
  → Rule Quality
  → PPTX Export
  → WPS/PowerPoint Render Evidence
  → One Visual Review
  → Online Edit
  → Final Export
```

每个箭头都必须定义输入哈希、输出哈希、revision、失败码、是否产生费用和失效范围。

## 3. 冷启动预检

任何真实模型调用前必须验证：

- 当前 Node/pnpm 版本符合 workspace 要求；
- 验收执行器的每个直接 import 都在其自身 package manifest 声明；
- API 构建产物和 Prompt Contract 可读取；
- `.env` 存在且只检查配置是否存在，不回显密钥；
- DMX Base URL、模型名和 API 风格组合合法；
- 数据目录、输出目录和临时目录可写；
- WPS 和 PowerPoint COM 分别可创建、打开空白演示并退出；
- 需要的中文字体存在，fallback 清单可用；
- 测试 Brief 来自仓库外部输入，输入哈希已记录；
- 预估最大调用次数不超过后台策略上限。

预检失败时真实模型调用数必须为零。

## 4. Prompt Contract 设计

Prompt Contract 继续作为外部版本化资源，不进入 TypeScript 字符串。

合同只允许包含：

- 输出 JSON 协议；
- 通用叙事和设计质量要求；
- 引用与身份约束；
- 可见文案和生产元数据边界；
- 禁止坐标、模板、代码和图片文字；
- 失败时返回方式。

合同禁止包含：

- 特定幼儿园主题；
- 固定标题、固定正文和固定图片描述；
- 封面、目录、章节、家长会等角色到布局的映射；
- 参考 PPT 的内容、顺序、颜色、字体和构图；
- 为某个验收用例准备的答案。

真实模型验证必须保存脱敏的协议级统计，不保存 API Key，也不把完整用户隐私输入写入日志。

## 5. 构图设计方向

009 不引入页面模板库。构图由以下可组合能力产生：

- 语义节点：headline、claim、question、answer、step、comparison item、metric、media、annotation、action；
- 关系：group、associate、compare、order、introduce、conceal、preserve、change；
- 原语：Stack、Grid、Flow、Overlay、Anchor、Frame、Text、Shape、Image、Chart、Connector；
- 约束：安全区、最小字号、内容覆盖、相对层级、对齐、邻近、跨页身份、媒体角色、裁剪焦点；
- 视觉语法：字体层级、色彩角色、形状词汇、图片处理、装饰频率和跨页节奏。

标题不得自动拥有固定标题带。它和其他节点一起进入层级与关系求解，但必须满足可读性和首要信息约束。

候选搜索上限可以配置，不能按业务主题选择构图。候选必须记录其结构来源、被淘汰原因和与其他候选的真实差异。

## 6. 原生设计系统

009 需要可组合的演示设计组件，不需要业务模板：

- Typography Scale；
- Surface、Band、Badge、Marker、Divider、Connector；
- Semantic Group、Comparison、Sequence、Metric Group、Chart Annotation；
- Image Mask、Scrim、Crop Focus、Caption Association；
- Deck Motif、Section Marker、Page Continuity Marker。

组件只表达视觉和语义关系，不知道“动物认知”“家长会”或具体页码。

## 7. 素材质量设计

素材解析分成四个独立阶段：

1. Identity：同一实体是否复用或受控变化。
2. Technical Validation：格式、尺寸、比例、alpha、MIME 和下载安全。
3. Semantic Validation：图片是否表达请求的实体、动作和环境。
4. Placement Validation：角色、裁剪、焦点、安全区和页面语义是否正确。

一次视觉复核同时接收：整稿联系表、高风险页高清图、同一身份的素材对照条和必要的页面意图摘要。任何素材描述仍不得进入观众可见节点。

## 8. 状态和并发设计

每个长任务使用三段式提交：

1. Capture：记录输入 revision 和输入哈希。
2. Execute：在不可变输入快照上执行模型、图片或渲染。
3. Commit：以 compare-and-swap 验证当前 revision 和依赖哈希；不一致则拒绝提交。

usage 账本独立追加，不能因业务提交冲突而丢失已经产生的费用。任务失败不能把旧聚合整体写回覆盖用户新编辑。

## 9. 编辑 override 设计

系统必须区分：

- generated base scene；
- user override operations；
- regenerated candidate scene；
- merge conflict。

单页重设计只替换允许重新生成的节点，用户锁定、手动改字、替换图片和明确保留的对象不得消失。无法无损合并时必须向用户报告冲突，不能静默覆盖。

## 10. 质量与交付设计

质量结果分为：

- deterministic rules；
- local render checks；
- asset checks；
- cross-page checks；
- visual model review；
- human acceptance。

规则通过只能进入下一门，不能直接宣布成品通过。局部严重错误不能被全页平均差异分数掩盖；Render Evidence 必须保留每页截图和可定位的节点证据。

视觉模型最多一次付费调用。失败后不得自动重试、自动换模型或自动整稿重跑。修复必须由用户确认后进入新的显式 Job。

## 11. 不重做原则

009 应复用已经验证的领域 Schema、Scene Graph、PPTX 原生对象导出和 Office Render Adapter。只有当前证据证明某部分阻碍主链或违反宪法时才允许修改。

禁止再次以“架构更漂亮”为理由推翻整个项目。

