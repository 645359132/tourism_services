# 智慧景区旅游服务系统

面向 HarmonyOS phone/tablet 的智慧景区全栈 MVP。客户端使用 ArkTS、ArkUI 与 Stage 模型；服务端使用 FastAPI、SQLAlchemy 2 与 Alembic。默认开发模式只需要一个本地 SQLite 文件，同时保留 PostgreSQL + Redis 的完整 Compose 拓扑。

系统已经打通游客、商户、客服、管理员四种角色，以及门票交易、导览与人流、规则行程、项目预约与排队、餐住组合预约、商城与积分、反馈客服、同行协作、无障碍、离线应急、文化护照和绿色任务。外部支付、地图、AI、闸机、救援等能力均通过明确标注的 Demo Provider 隔离，不会产生真实扣款、导航或救援派单。

运行入口：日常保留数据的完整 PostgreSQL + Redis + HarmonyOS 流程见[全栈日常启动指南](docs/testing/full-stack-startup.md)；需要独立 project、全新空卷和完整证据检查时使用[最终验收手册](docs/testing/acceptance.md)。

## 功能概览

- 游客自助注册并自动登录、JWT 登录、刷新令牌轮换与重放防护、Argon2id 密码散列，以及游客/商户/客服/管理员 RBAC。
- 动态票价、分时库存、幂等下单、演示支付、短时电子票二维码、核验、退款和改签。
- 景点与文化讲解、示意地图、模拟人流 WebSocket、偏好行程、冲突检查与动态重排。
- 项目/演出预约、虚拟排队、FastPass、酒店/民宿/餐饮和原子组合预约。
- 商品、购物车、订单、活动、不可变积分流水、反馈回访、客服 WebSocket 和同行协作。
- phone/tablet 响应式五栏导航、深浅色、大字/高对比、无障碍路线与便民设施。
- 五项离线旅行资产、ETag/校验、用户隔离缓存、安全 outbox、只读冷启动和演示 SOS。
- 文化数字护照、幂等打卡、绿色任务及与商城共用的积分账户。

## 仓库结构

```text
tourism_services/
├─ client/                       HarmonyOS ArkTS/ArkUI Stage 应用
│  └─ entry/src/
│     ├─ main/ets/               页面、组件、网络层、Store、模型和业务规则
│     ├─ test/                   Hypium 本地业务测试
│     └─ ohosTest/               设备业务 smoke 测试
├─ server/                       Python 3.12 FastAPI 服务
│  ├─ app/
│  │  ├─ api/routes/             REST 与 WebSocket 路由
│  │  ├─ services/               事务和领域用例
│  │  ├─ providers/              外部能力适配边界及本地 Demo 实现
│  │  ├─ db/models/              SQLAlchemy 持久化模型
│  │  ├─ realtime/               人流、排队、客服实时通道
│  │  └─ scripts/                seed、网络 smoke、压测身份准备
│  ├─ alembic/                   数据库迁移
│  ├─ tests/                     服务端测试
│  └─ load/                      Locust 场景
├─ docs/                         架构、API、数据模型、验收和性能证据
└─ docker-compose.yml            API + PostgreSQL + Redis 完整模式
```

## 前置条件

- Python 3.12，以及 [uv](https://docs.astral.sh/uv/)；依赖版本由 `server/uv.lock` 固定。
- DevEco Studio 与 HarmonyOS SDK。工程目标 SDK 为 `26.0.0`，兼容 SDK 为 `6.1.0(23)`；Hvigor、Code Linter、Node、OHPM 和 hdc 使用 DevEco 随附版本。
- 可选：Docker Desktop/Engine 与 Compose v2，用于 PostgreSQL + Redis 完整模式。
- 下文命令采用 PowerShell；Linux/macOS 只需换成对应的环境变量语法和 DevEco 工具路径。

## SQLite 零服务快速启动

默认模式不需要 PostgreSQL、Redis 或 Docker。请从仓库根目录严格按“依赖 → 数据目录 → 迁移 → seed → API”的顺序执行：

```powershell
Set-Location server
uv sync --frozen
New-Item -ItemType Directory -Force data | Out-Null

$env:APP_ENV = 'development'
$env:DATABASE_URL = 'sqlite+aiosqlite:///./data/tourism.db'
$env:ENABLE_DEMO_ACCOUNTS = 'true'

uv run alembic upgrade head
uv run tourism-seed
uv run tourism-api
```

`tourism-seed` 可重复执行；目录、参考数据和演示数据会保持幂等。API 默认监听 `0.0.0.0:8000`：

- 健康检查：<http://127.0.0.1:8000/health>
- Swagger UI：<http://127.0.0.1:8000/docs>
- OpenAPI：<http://127.0.0.1:8000/openapi.json>

[`tourism-seed`](server/app/scripts/seed.py) 中的演示账号只会在非生产环境显式设置 `ENABLE_DEMO_ACCOUNTS=true` 后创建。四个账号共用公开演示密码 `Tourism123!`：

| 用户名 | 角色 | 用途 |
|---|---|---|
| `tourist_demo` | tourist | 游客完整业务流程 |
| `merchant_demo` | merchant | 商户权限边界 |
| `support_demo` | support | 客服处理、SOS 状态流转 |
| `admin_demo` | admin | 管理员权限边界与验收 smoke |

这些凭据仅用于本地演示；配置会拒绝在 `APP_ENV=production` 时启用演示账号。

## 连接 HarmonyOS 客户端

本文将客户端基址称为 `API_BASE_URL`；代码中对应 [`AppConfig.apiBaseUrl`](client/entry/src/main/ets/config/AppConfig.ets)，不是操作系统环境变量。值必须包含 `/api/v1`，也可在应用“我的 → 开发环境 API 地址”中为当前进程修改。

| 运行位置 | API 地址示例 | 主机侧要求 |
|---|---|---|
| 与服务端共享网络命名空间的本机预览 | `http://127.0.0.1:8000/api/v1` | 使用快速启动默认值 |
| DevEco 模拟器 | 通常为 `http://10.0.2.2:8000/api/v1` | 若当前镜像使用不同宿主机网关，以模拟器网络配置为准 |
| 同一局域网的真机 | `http://192.168.1.23:8000/api/v1` | 替换为开发机 LAN IPv4，并允许防火墙入站 TCP 8000 |

模拟器或真机中的 `127.0.0.1` 指向设备自身。服务端需监听 `0.0.0.0`，并把实际 Host 加入可信列表后再启动，例如：

```powershell
Set-Location server
$env:TRUSTED_HOSTS = 'localhost,127.0.0.1,10.0.2.2,192.168.1.23'
uv run tourism-api
```

只保留实际使用的地址；示例 `192.168.1.23` 不能原样用于另一台开发机。REST 基址会自动派生 `ws://`/`wss://` 实时地址。

## HarmonyOS 安装、检查、测试与构建

在 `client/` 执行。将 `$devecoRoot` 指向本机 DevEco Studio 安装目录：

```powershell
Set-Location client
$devecoRoot = '<DevEco Studio 安装目录>'
$env:DEVECO_SDK_HOME = Join-Path $devecoRoot 'sdk'

& (Join-Path $devecoRoot 'tools\ohpm\bin\ohpm.bat') install

& (Join-Path $devecoRoot 'tools\node\node.exe') `
  (Join-Path $devecoRoot 'plugins\codelinter\run\index.js') `
  -c code-linter.json5 -p default -e error `
  (Join-Path $devecoRoot 'sdk\default\openharmony') .

& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') `
  test --mode module -p product=default -p module=entry@default `
  -p buildMode=debug --no-daemon

& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') `
  assembleHap --mode module -p product=default -p module=entry@default `
  -p buildMode=debug --no-daemon

& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') `
  assembleHap --mode module -p product=default -p module=entry@ohosTest `
  -p buildMode=debug --no-daemon

& (Join-Path $devecoRoot 'sdk\default\openharmony\toolchains\hdc.exe') list targets
```

Code Linter 的第一个位置参数是 OpenHarmony SDK，最后的 `.` 才是项目目录。`entry@ohosTest` 的 HAP 构建只证明设备测试代码可编译；实际执行需要 hdc 目标和本地签名，在 DevEco Studio 中选择 `entry@ohosTest` 运行。

## 服务端质量命令

静态检查和完整测试从 `server/` 执行；pytest 配置已内置分支覆盖率和 `fail_under = 70` 门禁：

```powershell
Set-Location server
uv run ruff check .
uv run pytest
```

真实网络 smoke 需要已迁移、已 seed 演示账号的数据库。先停止快速启动的 API；为在合理时间内观察到后续人流和排队发布事件，在第一个终端启动加速发布器：

```powershell
Set-Location server
$env:APP_ENV = 'development'
$env:DATABASE_URL = 'sqlite+aiosqlite:///./data/tourism.db'
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:CROWD_PUBLISH_INTERVAL_SECONDS = '0.5'
$env:QUEUE_PUBLISH_INTERVAL_SECONDS = '0.5'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

第二个终端执行：

```powershell
Set-Location server
uv run tourism-smoke --base-url http://127.0.0.1:8765 --timeout 10
```

Locust 场景会创建订单并消耗库存，应使用全新数据库。下面是已验收的 5 用户、30 秒参数；先停止上面的加速服务，再执行准备步骤：

```powershell
Set-Location server
$env:APP_ENV = 'development'
$loadDb = Join-Path $PWD.Path ("data/local-load-{0}.db" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$env:DATABASE_URL = "sqlite+aiosqlite:///$($loadDb.Replace('\', '/'))"
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:TOURISM_LOAD_USER_PASSWORD = '<至少 12 字符的本地压测密码>'
uv run alembic upgrade head
uv run tourism-load-seed --count 10
```

在第一个终端以正常发布周期启动 API：

```powershell
$env:CROWD_PUBLISH_INTERVAL_SECONDS = '30'
$env:QUEUE_PUBLISH_INTERVAL_SECONDS = '15'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

在第二个终端启动 Locust：

```powershell
$env:TOURISM_LOAD_USER_PASSWORD = '<与 seed 相同、至少 12 字符的本地密码>'
$env:TOURISM_LOAD_USER_COUNT = '10'
$env:TOURISM_LOAD_USER_OFFSET = '0'
$reproPrefix = Join-Path $env:TEMP ("tourism-locust-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
uv run locust -f load/locustfile.py `
  --host http://127.0.0.1:8765 `
  --headless --users 5 --spawn-rate 5 --run-time 30s --stop-timeout 5 `
  --csv $reproPrefix --csv-full-history --only-summary
```

该命令把个人复验输出放到临时目录，不会覆盖仓库中的基准证据。完整隔离规则、场景约束和结果解释见[本地容量基线](docs/performance/README.md)。

## PostgreSQL + Redis Compose 完整模式

完整模式使用 PostgreSQL 作为权威数据存储，Redis 承担跨 worker 缓存、限流、一次性 WebSocket ticket、锁、发布者选主和 pub/sub；API 容器运行两个 Uvicorn worker。Dockerfile 会在 API 启动前自动执行迁移和幂等 seed。

推荐按[全栈日常启动指南](docs/testing/full-stack-startup.md)依次完成 Docker、环境变量、数据库/Redis 检查、服务端门禁、真实 smoke、HarmonyOS 构建、人工闭环和可选 Locust。下面仅保留最短启动路径。

以下命令从仓库根目录执行：

```powershell
$env:POSTGRES_PASSWORD = 'local-tourism-db-password'
$env:POSTGRES_PORT = '15432'
$env:JWT_SECRET_KEY = 'local-compose-evaluator-secret-at-least-32-bytes'
$env:ENABLE_DEMO_ACCOUNTS = 'true'

docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 180
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health

Set-Location server
uv run tourism-smoke --base-url http://127.0.0.1:8000 --timeout 45
Set-Location ..
```

服务可用后访问 <http://127.0.0.1:8000/health> 和 <http://127.0.0.1:8000/docs>。示例把 PostgreSQL 的宿主机端口放在 `15432`，容器内 API 仍连接 `postgres:5432`，可避开本机 PostgreSQL 常见的 `5432` 冲突。`docker compose down` 会停止容器并保留命名卷；不要在需要保留数据时附加 `-v`。生产部署还必须使用密钥管理、HTTPS、明确的 CORS/Trusted Hosts 和受管 PostgreSQL/Redis，而不是示例凭据。

## 架构

ArkUI 页面通过类型化 Service 和统一 `HttpClient`/WebSocket 客户端访问 FastAPI。路由层负责协议、认证和 RBAC，领域 Service 负责事务、幂等与状态机，SQLAlchemy 模型保存权威状态。SQLite 与 PostgreSQL 共享迁移和业务语义；Redis 或进程内协调层可替换地提供临时协调能力，但库存、订单和积分仍由数据库约束及原子更新裁决。

客户端将网络状态、会话、无障碍设置和旅行缓存拆分为独立 Store；服务端将 provider、实时 hub/publisher、API、领域服务和持久化解耦。进一步说明：

- [系统架构与运行时](docs/architecture.md)；[Mermaid 图源](docs/architecture.mmd)
- [数据模型与一致性约束](docs/data-model.md)
- [REST/WebSocket API 指南](docs/api.md)
- [外部 Provider 与 Demo/Mock 边界](docs/mock-boundaries.md)

## REST 与 WebSocket

除 `/health`、`/docs` 和 `/openapi.json` 外，REST API 统一位于 `/api/v1`。成功响应使用具体 Pydantic schema；进入应用路由的错误使用稳定错误码、消息和 request ID；非法 Host/CORS 预检等路由前拒绝保留基础设施文本响应，详见 [API 指南](docs/api.md#错误信封与请求关联)。写操作中的订单、预约、支付、SOS、打卡等关键流程使用幂等键或版本/唯一约束保护。

| 领域 | 主要路径 | 能力 |
|---|---|---|
| 身份与元数据 | `/auth/*`、`/users/*`、`/meta/capabilities` | 游客注册、登录/刷新/登出、个人偏好、角色与 Provider 元数据 |
| 门票 | `/ticketing/*` | 类型/场次、报价、订单、支付、二维码、核验、退改 |
| 导览与行程 | `/guide/*`、`/itineraries/*` | 景点/讲解/地图/人流、路线、生成、冲突、重排 |
| 预约与排队 | `/experiences*`、`/reservations*`、`/queues*`、`/hospitality/*` | 项目场次、组合预约、队列、FastPass、餐住 |
| 商城与积分 | `/shop/*`、`/points/*`、`/shares` | 商品/购物车/订单/支付、流水、兑换、分享奖励 |
| 服务与协作 | `/feedback*`、`/faqs`、`/guide/facilities`、`/groups*`、`/support/*` | 投诉回访、设施、同行隐私与客服会话 |
| 离线与文化 | `/offline/*`、`/emergency/*`、`/passport*`、`/green/*` | 旅行包、push/pull、应急、SOS、护照和绿色任务 |

| WebSocket | 鉴权 | 语义 |
|---|---|---|
| `/api/v1/guide/ws/crowd` | 公共演示通道 | 初始人流快照及单调 sequence 更新 |
| `/api/v1/ws/queues/{queue_id}?ticket=...` | `POST /api/v1/ws-tickets` 签发的一次性 ticket | 当前排队状态和后续更新 |
| `/api/v1/ws/support/{conversation_id}?ticket=...` | `POST /api/v1/support/ws-tickets` 签发的一次性 ticket | 客服消息收发；消息同时持久化 |

完整请求/响应示例、分页、权限与关闭码见 [API 指南](docs/api.md)。

## 持久化与离线策略

服务端默认 SQLite 开启外键、WAL 和 busy timeout；完整模式切换到 PostgreSQL。Alembic 管理全部 schema。订单、库存、预约、队列、购物车、积分、反馈、客服消息、同行组、同步记录、SOS、护照和绿色任务均持久化。Redis 只保存可重建的协调状态；禁用 Redis 时单进程开发使用本地降级，完整模式默认 `REDIS_REQUIRED=true` 以避免静默退化。

客户端使用 ArkData Preferences 保存按用户封装的票单/票据身份、行程、商城订单、离线包和 outbox，并保存最小离线身份以支持重启后的只读冷启动。access/refresh token 只保存在内存；动态 QR 凭证不会作为可离线扫码的凭据保留。

离线包含地图、旅行说明、应急指引、文化简介和文字讲解五类资产，并通过 manifest hash、内容 hash 与 ETag/304 校验。离线 outbox 只允许便签、行程已读和应急公告已读等白名单 mutation；服务端使用用户/设备绑定的签名游标、客户端版本和幂等记录完成分页 push/pull。离线 SOS 只保存为 `LOCAL_ONLY/PENDING_SYNC` 草稿，恢复网络后需要显式重试；护照打卡和绿色任务仍要求在线 Provider 验证。

## 八项创新实现索引

| # | 创新点 | 已实现机制 | 关键源码 |
|---:|---|---|---|
| 1 | 个性化智能旅游管家 | 兴趣、同行人、体力、无障碍、人流和步行成本的可解释规则评分 | [planner.py](server/app/providers/planner.py)、[itinerary.py](server/app/services/itinerary.py)、[TripPage.ets](client/entry/src/main/ets/pages/TripPage.ets) |
| 2 | 动态避堵与最优路线 | 模拟人流单调推送、示意图最短路、拥挤替代建议与按最新快照重排 | [crowd.py](server/app/realtime/crowd.py)、[map.py](server/app/providers/map.py)、[GuidePage.ets](client/entry/src/main/ets/pages/GuidePage.ets) |
| 3 | 多订单冲突优化器 | 行程、门票、预约及步行缓冲的冲突检测、版本化建议与安全重排 | [itinerary.py](server/app/services/itinerary.py)、[TripConflict.ets](client/entry/src/main/ets/utils/TripConflict.ets) |
| 4 | 排队与行程联动 | 虚拟队列/FastPass 更新生成带 itinerary revision 的调整建议，客户端拒绝过期建议 | [queues.py](server/app/services/queues.py)、[reservations.py](server/app/services/reservations.py)、[ExperienceBookingView.ets](client/entry/src/main/ets/components/booking/ExperienceBookingView.ets) |
| 5 | 多人同行协作 | 邀请加入、成员状态、行程 revision，以及群组级与成员级的行程/位置/状态双重隐私控制 | [groups.py](server/app/services/groups.py)、[GroupCollaborationView.ets](client/entry/src/main/ets/components/profile/GroupCollaborationView.ets) |
| 6 | 适老与无障碍 | 大字、高对比、持久化偏好、720vp 响应式布局、无障碍路线过滤及便民设施 | [AccessibilityStore.ets](client/entry/src/main/ets/stores/AccessibilityStore.ets)、[AccessibilityView.ets](client/entry/src/main/ets/components/profile/AccessibilityView.ets)、[engagement.py](server/app/services/engagement.py) |
| 7 | 弱网离线与应急 | 校验旅行包、用户隔离缓存、安全 outbox、只读冷启动、疏散信息和不误导的 SOS 草稿 | [offline.py](server/app/services/offline.py)、[safety.py](server/app/services/safety.py)、[OfflineEmergencyView.ets](client/entry/src/main/ets/components/profile/OfflineEmergencyView.ets) |
| 8 | 文化护照与绿色积分 | 幂等文化打卡、绿色凭证验证、统一不可变积分流水及商城余额联动 | [passport.py](server/app/services/passport.py)、[points.py](server/app/services/points.py)、[PassportGreenView.ets](client/entry/src/main/ets/components/profile/PassportGreenView.ets) |

## 外部能力与 Demo 边界

MVP 的 API、事务、持久化、状态机、RBAC 和 WebSocket 都是可运行实现；下列外部世界连接是有意保留的适配边界：

| 能力 | 当前实现 | 不应据此声称 |
|---|---|---|
| AI/行程 | 可解释的确定性 RulesPlanner | 已连接大模型或在线推荐服务 |
| 地图/讲解 | 本地示意图和策展文字 | 实时地图、GPS 导航或在线语音服务 |
| 人流/排队 | seed 数据与模拟发布器 | 已连接传感器、闸机或园区排队系统 |
| 支付/闸机/商户 | 幂等 Demo 支付、演示核验、本地目录 | 真实资金流、物理闸机或外部商户履约 |
| 客服/通知/分享 | 本地客服角色、规则 bot、进程内通知、格式校验 | 外部工单、短信推送或社交平台回执 |
| SOS/护照/绿色任务 | 持久化 Demo 请求和确定性验证器 | 联系急救/公安、真实地理围栏或现实行为认证 |

响应中的 `provider`、`mode`、`is_demo`、`real_dispatch` 等字段以及 `/api/v1/meta/capabilities` 会暴露这些边界。详见 [Mock 边界说明](docs/mock-boundaries.md)。

## 最终验收证据

验收基线日期为 2026-09-04（Asia/Shanghai）：

| 检查 | 已接受结果 |
|---|---|
| 服务端 pytest | 146 tests passed；分支覆盖率 72.63%，通过 `>= 70%` 门禁；包含游客注册与 PostgreSQL 离线 DDL 门禁 |
| Ruff | `uv run ruff check .` 通过 |
| HarmonyOS 本地业务测试 | Hvigor `test`：41 passed，Failure 0，Error 0 |
| 真实网络 smoke | 当前 runner 为 49/49，其中注册、注册会话和重复用户名占 3 项；覆盖 REST 及人流、排队、客服 3 条 WebSocket |
| Locust 本机基线 | 5 users / 30 s；CSV 320 requests、0 failures、11.42 req/s、aggregate p95 160 ms |
| Locust Compose 基线 | PostgreSQL 16 + Redis 7 + 双 worker；CSV 319 requests、0 failures、11.33 req/s、aggregate p95 130 ms |
| HarmonyOS 编译 | `entry@default` debug HAP 与含 4 个用例的 `entry@ohosTest` debug HAP 均构建成功 |
| Code Linter | 仓库配置启用的 TypeScript/security recommended 规则执行且零缺陷 |
| API 契约 | OpenAPI 共 105 个 REST operations；另有 3 条 WebSocket 契约 |
| Compose | API/PostgreSQL/Redis 均 healthy；空库迁移至 `0007`、重复迁移/seed、schema drift、Redis PONG 均通过 |

详细证据与复验范围：

- [全栈日常启动指南](docs/testing/full-stack-startup.md)
- [全栈验收说明](docs/testing/acceptance.md)
- [客户端质量与设备矩阵](docs/testing/client-quality.md)
- [本地性能基线与原始 CSV](docs/performance/README.md)
- [10,000 在线容量验证计划](docs/performance/10k-capacity-plan.md)

两组本机 Locust 结果都是开发机可重复基线，不是 10,000 在线、生产 SLO 或公网性能声明。

### 当前需要外部环境完成的验证

- `entry@ohosTest` 的 4 个用例已经编译；模拟器上的测试包执行和 phone/tablet 人工矩阵由测试人员在 DevEco Studio 完成本地签名后执行并记录结果。
- 当前 DevEco `arkPerfCheck` 扩展会在六个大型 ArkUI 文件上触发内部 `getDeclaringMethod` 异常；已接受门禁是实际执行且零缺陷的 TypeScript/security 规则、ArkTS 编译和设备矩阵。升级检查器后应重跑 cross-device/性能扩展。

## 常见问题

- **Alembic 报无法打开 SQLite 文件**：确认当前目录是 `server/`，并先执行 `New-Item -ItemType Directory -Force data`。
- **uv 缓存目录不可写**：在仓库根目录创建 `.uv-cache`，然后在 `server/` 设置 `$env:UV_CACHE_DIR = (Resolve-Path '..\.uv-cache').Path` 再运行 `uv sync --frozen`。
- **演示账号登录返回 401**：在迁移后的同一环境设置 `ENABLE_DEMO_ACCOUNTS=true`，重新执行 `uv run tourism-seed`，并确认连接的是同一个 `DATABASE_URL`。
- **设备无法连接 API 或返回 Invalid host header**：不要使用设备自身的 `127.0.0.1`；检查 `/api/v1` 后缀、服务端 `0.0.0.0` 监听、`TRUSTED_HOSTS`、同网段和主机防火墙。
- **排队/客服 WebSocket 返回 4401**：先通过对应 REST 接口取得一次性 ticket；ticket 有有效期且消费后不能复用。
- **Hvigor 找不到 SDK 或 HAP 无法安装**：设置 `DEVECO_SDK_HOME`；CLI 编译产物未签名时，在 DevEco Studio 配置本地签名并选择已连接的 hdc 目标。
- **Code Linter 把项目当成 SDK**：保持命令中的参数顺序——OpenHarmony SDK 路径在前，项目目录 `.` 在最后；`arkPerfCheck` 的已知内部异常不等于 TypeScript/security 门禁失败。
- **Compose 无法连接 daemon**：先启动 Docker Desktop 的 Linux engine，以 `docker info` 确认 daemon 可用，再运行 `docker compose up --build`。
- **PostgreSQL 端口绑定失败**：本机服务占用 `5432` 时，设置 `$env:POSTGRES_PORT = '15432'` 后重新执行 Compose；这不会改变容器内的 `postgres:5432`。
