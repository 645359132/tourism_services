# 实施进度

更新时间：2026-09-01（Asia/Shanghai）

| 检查点 | 状态 | 证据/说明 |
|---|---|---|
| 1. 仓库基线 | 已完成 | `main` 基线提交 `9056088`；敏感信息扫描零命中；已切换 `feat/smart-tourism-mvp` |
| 2. FastAPI 与持久化基础 | 已完成 | uv sync；Alembic 重复升级；seed 重复运行；Ruff 通过；pytest 10 passed/79%；`/health`、`/docs`、Compose 配置通过 |
| 3. 认证权限与客户端应用壳 | 进行中 | 正在实现 JWT/RBAC 与客户端网络/登录/响应式导航 |
| 4. 门票交易纵向切片 | 待开始 |  |
| 5. 导览、人流与行程智能 | 待开始 |  |
| 6. 项目排队与餐住预约 | 待开始 |  |
| 7. 商城、客服、协作与无障碍 | 待开始 |  |
| 8. 离线应急与数字护照 | 待开始 |  |
| 9. 综合质量与容量基线 | 待开始 | Docker CLI/Compose 可用，但本次盘点时 daemon 未运行 |
| 10. 文档与最终验收 | 待开始 |  |

已确认的环境约束：

- `client/` 是 ArkTS + ArkUI + Stage 模板，支持 phone/tablet，target SDK 26.0.0，compatible SDK 6.1.0(23)。
- `server/` 初始为空。
- Docker daemon 当前不可用；SQLite 零依赖模式优先，Compose 配置仍会静态验证。
- uv 默认缓存目录受当前受管环境限制；后续使用仓库内已忽略的 `.uv-cache/`。
