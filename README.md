# SparkDeck

面向幼儿园全部演示场景的 AI PPT 生成与编辑平台。项目由 React 产品前端、本地生成 API 和在线编辑器组成，生成结果可编辑并导出 PPTX/PDF。

## 生成流程

`输入需求 → AI 生成大纲 → 用户修改确认 → 选择模板族 → AI 逐页选择布局 → 生成页面与素材 → 在线编辑 → 导出`

- 页面数量由用户指定或模型根据需求决定，生产代码不枚举固定页数和固定页面顺序。
- 模板提供布局能力，不把家长会、认知课或互动课映射到固定构图。
- 大纲和页面内容使用同一份引擎持久化数据，不维护第二套业务数据库。
- 编辑、预览和导出全部读取同一份幻灯片数据，不再转换到自研 Scene Graph。
- DMX 密钥只存在本地 `.env`；费用在模型网关和后台日志中记录，不打断前台流程。

## 目录

- `web`：扁平化产品前端，负责输入、大纲确认、生成状态和嵌入编辑器。
- `engine/api`：生成、大纲、模板、素材和导出 API。
- `engine/editor`：在线 PPT 编辑器。
- `engine/export`：PPTX/PDF 导出运行时。
- `templates`：项目使用的模板资产。
- `scripts/validate-pptx.py`：PPTX 文件结构与内容检查工具。
- `licenses/open-source-engine`：开源引擎许可证和第三方声明。

## 本地运行

在保留现有 `.env` 的前提下填写 `DMX_API_KEY`、文本模型和图片模型配置：

```bash
pnpm install
pnpm setup:engine
pnpm dev
```

浏览器打开 `http://127.0.0.1:5173/`。开发端口：React `5173`、编辑器 `5001`、生成 API `8000`。

## 验证

```bash
pnpm typecheck
pnpm build
pnpm test
pnpm audit:recognition-template
```
