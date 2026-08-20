# TeachNova × SparkDeck 用户隔离落地文档

> 状态：P0 进行中  
> 更新：2026-08-13

## 1. 复盘：从登录到 PPT 历史

### 目标链路（期望）

1. 用户在官网登录 → 拿到 `accessToken` + `userId`
2. 点击「PPT制作」→ `authGate` 校验已登录 → 进入 `/tools/ppt`
3. 官网用 `accessToken` 向 PPT API **换票** → 得到 PPT `session_token`
4. iframe 加载编辑器，携带短期 `tn_session`（进入后写入内存/sessionStorage，并从 URL 去掉）
5. 编辑器所有 `/api/v1/*` 请求带 `Authorization: Bearer <session_token>`
6. PPT API 解析会话 → `owner_id = 映射用户` → 列表/创建/模板按用户隔离

### 改造前现状（问题）

| 步骤 | 现状 | 问题 |
|------|------|------|
| 官网登录 | ✅ OAuth2 accessToken | — |
| 进 `/tools/ppt` | ✅ 需登录 | — |
| iframe | ⚠️ URL 传长期 `token` | PPT 不消费；泄露风险 |
| PPT 鉴权 | ❌ `DISABLE_AUTH=true` | 无 owner，全库共享 |
| 历史/模板 | ❌ 不按用户过滤 | 看见别人数据或混在一起 |

### 结论

- **引擎已有** `owner_id` 隔离能力（开鉴权时生效）
- **官网已有** 登录态
- **缺的是 Bridge 换票 + 请求带会话 + 关鉴权时也挂 owner**

按本文方案实现即可闭环「登录 → 点 PPT → 只见自己的历史/上传模板」。

---

## 2. 方案摘要

**SSO Bridge（推荐，本仓库采用）**

- 不让用户在 PPT 再注册
- 用官网 `userId` 映射 PPT 用户：`username = tn_{userId}`
- 换票接口：`POST /api/v1/auth/bridge/teachnova`
- 校验：调官网 `get-permission-info`
- 编辑器：Bearer 会话 JWT（避开 3030/5001/8000 跨端口 Cookie 坑）
- 系统内置模板继续全局只读共享

---

## 3. 分步任务与勾选

### P0 — 可用隔离（本阶段）

- [x] 文档落盘（本文件）
- [ ] PPT：`bridge/teachnova` 换票 + 用户映射
- [ ] PPT：`principal` 支持 Bearer 会话 JWT
- [ ] PPT：`DISABLE_AUTH` 下若有会话仍设置 `owner_id`
- [ ] 编辑器：捕获 `tn_session` + fetch/header 自动带 Authorization
- [ ] 官网：Vite 代理 `/ppt-api` + `ToolsPpt` 换票后再嵌 iframe
- [ ] 环境变量说明（`.env.example`）
- [ ] 本地验证：两账号历史互不可见

### P1 — 安全与体验

- [ ] 同域反代（生产）
- [ ] 去掉任何长期 token 进 URL
- [ ] 模板上传页确认归属
- [ ] 无主历史数据迁移策略

### P2 — 多租户

- [ ] `tenant_id` 与官网租户对齐
- [ ] 园所管理员视角

---

## 4. 关键配置

### `xfyun-ai-ppt-mvp/.env`

```env
TEACHNOVA_AUTH_INTROSPECT_URL=http://127.0.0.1:48080/admin-api/system/auth/get-permission-info
TEACHNOVA_TENANT_ID=1
# 可选：逗号分隔，CORS 额外放行官网来源（直连 API 时）
TEACHNOVA_CORS_ORIGINS=http://localhost:3030,http://127.0.0.1:3030
```

### `zhiyi_edu_official/.env`

```env
VITE_PPT_APP_URL=http://127.0.0.1:5001/dashboard
VITE_PPT_API_URL=/ppt-api
```

开发代理：`/ppt-api` → `http://127.0.0.1:8000`

---

## 5. 验收清单

1. 用户 A 登录官网 → PPT → 新建演示文稿 → 仪表盘可见
2. 退出，用户 B 登录 → PPT → **看不到** A 的文稿
3. B 上传自定义模板 → 仅 B 可见；系统默认模板双方可见
4. 未登录点 PPT → 弹登录，不进功能页
5. URL 不出现官网长期 `accessToken`

---

## 6. 实现进度日志

| 日期 | 内容 |
|------|------|
| 2026-08-13 | 复盘确认；P0 编码完成（Bridge/Bearer/官网换票）；待本地双账号验收 |
| 2026-08-13 | 修复空白页：EventSource 补 tn_session；生成保存时清理全部旧 slides |
