# 实施进度

更新时间：2026-09-01（Asia/Shanghai）

| 检查点 | 状态 | 证据/说明 |
|---|---|---|
| 1. 仓库基线 | 已完成 | `main` 基线提交 `9056088`；敏感信息扫描零命中；已切换 `feat/smart-tourism-mvp` |
| 2. FastAPI 与持久化基础 | 已完成 | uv sync；Alembic 重复升级；seed 重复运行；Ruff 通过；pytest 10 passed/79%；`/health`、`/docs`、Compose 配置通过 |
| 3. 认证权限与客户端应用壳 | 已完成 | JWT/RBAC/refresh 重放防护；真实登录 smoke；server pytest 29 passed/83%；客户端业务测试 5 passed；debug HAP 构建通过 |
| 4. 门票交易纵向切片 | 已完成 | 原子库存/动态价/幂等订单/支付/QRCode/核验/退款/改签；server pytest 43 passed/71%；客户端 9 tests passed；真实 REST 与 HAP 通过 |
| 5. 导览、人流与行程智能 | 已完成 | 规则行程/示意路线/模拟人流/冲突与安全重排；真实 WS 单调推送；server pytest 50 passed/67%；客户端 14 tests 与 HAP 通过 |
| 6. 项目排队与餐住预约 | 进行中 | 正在实现统一预约库存、虚拟排队与餐住组合闭环 |
| 7. 商城、客服、协作与无障碍 | 待开始 |  |
| 8. 离线应急与数字护照 | 待开始 |  |
| 9. 综合质量与容量基线 | 待开始 | Docker CLI/Compose 可用，但本次盘点时 daemon 未运行 |
| 10. 文档与最终验收 | 待开始 |  |

已确认的环境约束：

- `client/` 是 ArkTS + ArkUI + Stage 模板，支持 phone/tablet，target SDK 26.0.0，compatible SDK 6.1.0(23)。
- `server/` 初始为空。
- Docker daemon 当前不可用；SQLite 零依赖模式优先，Compose 配置仍会静态验证。
- uv 默认缓存目录受当前受管环境限制；后续使用仓库内已忽略的 `.uv-cache/`。
- 官方 ohpm 注册表在本机多次 TLS `ECONNRESET`；客户端测试已用 DevEco SDK 自带 Hypium 动态源码的 no-save 本地副本验证，提交内容不含本机路径或本地锁。
