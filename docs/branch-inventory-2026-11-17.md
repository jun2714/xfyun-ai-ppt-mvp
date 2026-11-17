# 分支用途核对（2026-11-17）

当前开发应继续围绕 `fix/kindergarten-generation-stability`；`main` 是用户指定的线上主分支。本次核对时修复分支包含 main，另有 44 个提交，分支顶端为 `2ac32b5`。以下为其余远端分支，依据提交历史归纳，未进行删除或合并。

| 分支 | 用途 |
| --- | --- |
| `feat/auto-template-router` | 按模板元数据自动选择适合主题与内容的模板 |
| `feat/kindergarten-planner-v1` | 较早的一套幼教规划集成分支，含教案、教学契约、模板与编辑器适配、生产配置及 Cypress/CI 工作；不只是一个小功能补丁 |
| `feat/kindergarten-template-routing` | 幼教模板匹配的历史分支；当前分支头已是 main 的祖先，没有 main 之外的独有提交 |
| `fix/dmx-runtime-v2` | DMX 运行时及 Gemini 环境变量桥接修复 |
| `fix/dmx-shared-kimi-key` | DMX 共享凭据、文本/图片模型与语义图片检查的配置修复 |
| `fix/enforce-kindergarten-fast-planner` | 强制早期 K2.7 幼教规划路径与等待上限 |
| `fix/kindergarten-creation-pipeline` | 修复幼教创建流程和配图链路 |
| `fix/kindergarten-planner-fast-path` | 保持早期 Kimi 快速大纲路径 |
| `fix/local-editor-sse-cors` | 本地编辑器流式连接、跨域以及错误响应的 CORS 处理 |

除已经完全落后于 main 的模板路由分支外，其余分支在 Git 提交图中仍有独有提交；其中的功能也可能通过重写或拣选提交进入当前代码，不能只凭分支名认定“没用”或直接合并。若要清理，应逐个比较实际差异，不要把旧模型配置重新带入当前 DeepSeek 规划路径。

本机正在运行的 `D:\Work\zhiyi_edg\xfyun-ai-ppt-mvp` 当时位于本地 main 的 `d38725a`，并有未提交的导出相关改动。它并不是远端修复分支的 `2ac32b5`，因此早上新增的审核入口不会因远端已经提交而自动出现在该进程中。
