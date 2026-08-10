# 008 API 变更

## 1. 原则

- 保留现有异步 Job、幂等键和 revision conflict。
- 新阶段产物可以单独查询和重放。
- API 不暴露供应商请求体和密钥。
- 费用只记录在后台 usage ledger，不加入用户确认页面。

## 2. Presentation 资源

`GET /api/v1/presentations/:id` 新增：

- `narrativeArc`
- `visualGrammar`
- `pageLinks`
- `assetBundle`
- `renderEvidence`
- `qualityGate`

所有字段包含 schemaVersion、revision、contentHash 和 upstreamHashes。

## 3. Jobs

- `POST /presentations/:id/narrative-jobs`
- `POST /presentations/:id/design-jobs`
- `POST /presentations/:id/composition-jobs`
- `POST /presentations/:id/asset-jobs`
- `POST /presentations/:id/render-jobs`
- `POST /presentations/:id/quality-jobs`
- `POST /presentations/:id/repair-jobs`
- `POST /presentations/:id/export-jobs`

每个写请求必须提交 `idempotencyKey`；依赖 Scene 的请求必须提交 `expectedRevision`。

## 4. 页面组与候选

- `GET /presentations/:id/page-groups`
- `GET /presentations/:id/pages/:pageId/candidates`
- `POST /presentations/:id/page-groups/:groupId/select-composition`
- `POST /presentations/:id/pages/:pageId/redesign-jobs`

关联页面默认按组切换候选，防止问题页与揭晓页失去连续性。单页强制切换时必须重新运行组级约束检查。

## 5. 素材

- `GET /presentations/:id/assets`
- `POST /presentations/:id/assets/:assetId/regenerate-jobs`
- `POST /presentations/:id/assets/:assetId/replace`
- `POST /presentations/:id/assets/:assetId/variants-jobs`

接口必须返回素材身份、角色、复用页面、生成状态和质量状态。图片描述只属于元数据，不得进入可见内容接口。

## 6. 渲染证据

- `GET /presentations/:id/render-evidence`
- `GET /presentations/:id/render-evidence/pages/:pageId`

每页记录 Scene render、PPTX render、尺寸、哈希和差异分数。未通过最终渲染质量门时，导出接口返回 `409 QUALITY_GATE_FAILED`。

## 7. 编辑命令

Scene Command 新增：

- resize/rotate
- multi-select alignment/distribution
- add/replace image
- group/ungroup
- add/duplicate/delete/reorder page
- update theme token
- update page-link constraint

命令必须可撤销，并在影响关联页或质量状态时使对应产物失效。

## 8. 统一错误响应

所有错误返回：

```json
{
  "error": {
    "code": "COMPOSITION_NO_VALID_CANDIDATE",
    "message": "面向用户的简洁说明",
    "stage": "composition",
    "presentationId": "pres_xxx",
    "pageId": "可选",
    "nodeIds": [],
    "incurredCost": false,
    "manualRetryAllowed": true,
    "details": []
  },
  "meta": { "requestId": "req_xxx" }
}
```

- Schema/输入错误使用 400；
- revision conflict 使用 409；
- 资源不存在使用 404；
- 上游模型或图片服务失败使用 502/503；
- 质量门失败使用 409；
- 不得向客户端返回 stack、API Key、供应商原始鉴权信息、完整模型响应或图片 base64。

## 9. 决策与验证证据

后台调试接口：

- `GET /presentations/:id/layout-traces`
- `GET /presentations/:id/asset-traces`
- `GET /presentations/:id/quality-evidence`
- `GET /presentations/:id/usage`

它们用于定位排版来源、素材复用、质量证据和费用，不得将生产说明注入 Scene Graph 可见节点。生产环境必须经过管理员权限控制。

## 10. 状态一致性

- 所有资源响应包含 revision、contentHash 和 upstreamHashes。
- 任何会改变 Scene 的命令都必须携带 expectedRevision。
- 失效产物不得继续由 GET 或 export 当作当前结果返回。
- Job 成功前不公开部分新状态；失败后保留最后一个完整可用 revision。
- 相同 idempotencyKey、请求类型和作用域必须返回同一 Job，不得重复产生模型或图片调用。
