# 系统运行配置与 AI 提示词说明

本文用于两件事：

1. 说明“智慧景区旅游服务系统”在本机轻量模式、Docker Compose 完整模式及 DevEco Studio 模拟器中的运行配置。
2. 归档本项目开发过程中交给 AI 编程助手的两组核心提示词：最初的 `/goal` 提示词，以及最近一轮组员反馈问题。

这里的“AI 提示词”是**项目开发对话输入**，不是客户端或服务端运行时调用大模型的系统提示词。当前项目的行程规划仍使用确定性 `RulesPlanner`，没有接入外部生成式 AI。

## 1. 系统运行配置

### 1.1 软件与运行模式

| 项目 | 轻量模式 | 完整模式 |
|---|---|---|
| 适用场景 | DevEco 模拟器手工测试、单人开发 | PostgreSQL/Redis、多进程协调和全栈验收 |
| 必需软件 | Windows、Python 3.12、DevEco Studio | 前述软件，以及运行 Linux engine 的 Docker Desktop |
| 数据库 | SQLite：`server/data/tourism.db` | PostgreSQL 16 |
| 协调与缓存 | 单进程内存降级 | Redis 7 |
| API | 单个 FastAPI/Uvicorn 进程 | Compose 中的 FastAPI 服务 |
| 客户端 | HarmonyOS ArkTS/ArkUI `entry` | 同左 |

客户端工程目标 SDK 为 `26.0.0`，兼容 SDK 为 `6.1.0(23)`。轻量模式和完整模式使用两套独立数据库，账号、订单和预约不会自动互通。

详细手册：

- [Python 3.12 + DevEco Studio 轻量启动](testing/lightweight-startup.md)
- [Windows PowerShell 全栈日常启动](testing/full-stack-startup.md)
- [完整验收与模拟器检查](testing/acceptance.md)

### 1.2 目录、端口与网络地址

| 项目 | 配置 |
|---|---|
| 仓库目录 | `D:\YOUR_CODE\tourism_services` |
| 服务端目录 | `D:\YOUR_CODE\tourism_services\server` |
| DevEco 工程目录 | `D:\YOUR_CODE\tourism_services\client` |
| API 监听 | `0.0.0.0:8000` |
| 健康检查 | `http://127.0.0.1:8000/health` |
| OpenAPI | `http://127.0.0.1:8000/docs` |
| Windows 本机 API 基址 | `http://127.0.0.1:8000/api/v1` |
| DevEco 模拟器 API 基址 | `http://10.0.2.2:8000/api/v1` |
| 局域网真机 API 基址 | `http://<开发机局域网 IPv4>:8000/api/v1` |
| PostgreSQL 宿主机端口 | 文档默认使用 `15432`，容器内仍为 `5432` |
| Redis 端口 | `6379` |

模拟器访问 Windows 宿主机必须使用 `10.0.2.2`，不能填写模拟器自身的 `127.0.0.1`。真机测试还需把开发机局域网 IPv4 加入 `TRUSTED_HOSTS`，并只在可信专用网络放行 TCP 8000。

### 1.3 轻量模式启动

首次准备：

```powershell
Set-Location 'D:\YOUR_CODE\tourism_services\server'

python --version
python -m pip install --user uv

$uvUserScripts = python -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user'))"
$uvExe = Join-Path $uvUserScripts 'uv.exe'
if (-not (Test-Path -LiteralPath $uvExe -PathType Leaf)) {
    $uvExe = (Get-Command uv -ErrorAction Stop).Source
}

$env:UV_CACHE_DIR = (New-Item -ItemType Directory -Force ..\.uv-cache).FullName
& $uvExe sync --frozen --no-dev --python 3.12
New-Item -ItemType Directory -Force data | Out-Null
```

每次启动：

```powershell
Set-Location 'D:\YOUR_CODE\tourism_services\server'

$uvUserScripts = python -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user'))"
$uvExe = Join-Path $uvUserScripts 'uv.exe'
if (-not (Test-Path -LiteralPath $uvExe -PathType Leaf)) {
    $uvExe = (Get-Command uv -ErrorAction Stop).Source
}

$env:UV_CACHE_DIR = (New-Item -ItemType Directory -Force ..\.uv-cache).FullName
$env:APP_ENV = 'development'
$env:DATABASE_URL = 'sqlite+aiosqlite:///./data/tourism.db'
$env:REDIS_COORDINATION_ENABLED = 'false'
$env:REDIS_REQUIRED = 'false'
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:TRUSTED_HOSTS = 'localhost,127.0.0.1,10.0.2.2'

& $uvExe run --no-sync alembic upgrade head
& $uvExe run --no-sync tourism-seed
& $uvExe run --no-sync tourism-api
```

另开 PowerShell 验证：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8000/health'
```

迁移和 seed 均可重复执行。该模式不需要 Docker、PostgreSQL 或 Redis；它适合模拟器手工测试，不用于多 worker 或生产部署。

### 1.4 Docker Compose 完整模式

先启动 Docker Desktop，并确认 `docker info` 同时显示 Client 和 Server。然后在仓库根目录配置：

```powershell
Set-Location 'D:\YOUR_CODE\tourism_services'

$env:APP_ENV = 'development'
$env:POSTGRES_USER = 'tourism'
$env:POSTGRES_DB = 'tourism'
$env:POSTGRES_PORT = '15432'
$env:POSTGRES_PASSWORD = 'local-tourism-db-password'
$env:REDIS_PORT = '6379'
$env:API_PORT = '8000'
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:TRUSTED_HOSTS = 'localhost,127.0.0.1,api,testserver,10.0.2.2'

$jwtBytes = New-Object byte[] 48
$jwtRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $jwtRng.GetBytes($jwtBytes)
    $env:JWT_SECRET_KEY = [Convert]::ToBase64String($jwtBytes)
}
finally {
    $jwtRng.Dispose()
}

docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 180
docker compose ps
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8000/health'
```

上述随机密钥写法兼容 Windows PowerShell 5.1。不要提交真实 `.env`、数据库密码、JWT、签名证书或设备材料。停止服务但保留数据：

```powershell
docker compose stop
```

不要在需要保留 PostgreSQL/Redis 数据时使用 `docker compose down -v`。

### 1.5 主要环境变量

完整字段和校验规则以 [server/.env.example](../server/.env.example) 与 [config.py](../server/app/core/config.py) 为准。

| 变量 | 开发默认/示例 | 说明 |
|---|---|---|
| `APP_ENV` | `development` | `development/test/staging/production` |
| `DATABASE_URL` | SQLite 本地文件 | 完整模式由 Compose 注入 PostgreSQL URL |
| `JWT_SECRET_KEY` | 本地开发占位值 | 生产必须为至少 32 字节的非占位随机密钥 |
| `ENABLE_DEMO_ACCOUNTS` | `false` | 本地演示时显式设为 `true`，生产禁止开启 |
| `TRUSTED_HOSTS` | localhost 列表 | 模拟器需包含 `10.0.2.2` |
| `TICKET_QUOTE_TTL_SECONDS` | `300` | 签名门票报价有效期 |
| `TICKET_REFUND_CUTOFF_HOURS` | `2` | 入园前退票截止小时数 |
| `RESERVATION_HOLD_MINUTES` | `15` | 项目/餐住预约保留时间 |
| `QUEUE_PUBLISH_INTERVAL_SECONDS` | `15` | 模拟队列推进周期 |
| `CROWD_PUBLISH_INTERVAL_SECONDS` | `30` | 模拟人流发布周期 |
| `SHOP_ORDER_RESERVATION_MINUTES` | `15` | 商城待支付库存保留时间 |
| `REDIS_COORDINATION_ENABLED` | `false` | 完整模式启用 Redis 协调 |
| `REDIS_REQUIRED` | `false` | 完整强一致模式可要求 Redis 必须可用 |
| `RATE_LIMIT_ENABLED` | `true` | 开启接口限流 |

生产模式还要求显式 HTTPS CORS、可信 Host、安全响应头、关闭演示账号，并拒绝开发占位密钥。

### 1.6 DevEco Studio 模拟器

1. 使用 DevEco Studio 打开 `D:\YOUR_CODE\tourism_services\client`。
2. 等待 OHPM/Hvigor 同步完成。
3. 启动 phone 或 tablet 模拟器。
4. 选择普通 `entry` 模块运行；`entry@ohosTest` 是设备测试入口，不是应用入口。
5. 应用默认 API 基址为 `http://10.0.2.2:8000/api/v1`。
6. 如需修改，可在应用“我的 → 开发环境 API 地址”中填写完整的 `/api/v1` 地址。

CLI 产物未配置仓库签名；模拟器或真机安装由 DevEco Studio 使用开发机本地签名完成。

### 1.7 演示账号

以下账号仅在 `ENABLE_DEMO_ACCOUNTS=true` 且执行 seed 后存在，统一密码为 `Tourism123!`。

| 用户名 | 角色 |
|---|---|
| `tourist_demo` | 游客 |
| `merchant_demo` | 商户 |
| `support_demo` | 客服 |
| `admin_demo` | 管理员 |

也可以在客户端注册新的游客账号。注册数据保存在当前运行模式对应的数据库中。

### 1.8 验证基线

```powershell
Set-Location 'D:\YOUR_CODE\tourism_services\server'
uv run ruff check .
uv run pytest
uv run tourism-smoke --base-url http://127.0.0.1:8000 --timeout 45
```

客户端验证命令见[客户端质量与设备矩阵](testing/client-quality.md)。当前仓库验收基线为：

- 服务端 pytest：159 passed，覆盖率 72.89%，通过 70% 门禁。
- 真实网络 smoke：49/49。
- 客户端 Hypium：49 passed，Failure 0，Error 0。
- DevEco Code Linter：No defects found。
- `entry@default` 与 `entry@ohosTest` debug HAP：构建成功。
- OpenAPI：107 个 REST operations，另有 3 条 WebSocket 契约。

## 2. AI 提示词说明

### 2.1 提示词的含义和范围

本节只记录两组开发提示词：

| 提示词 | 用途 | 使用阶段 |
|---|---|---|
| 最初 `/goal` 提示词 | 定义全栈 MVP、Git、架构、功能、创新点、验证循环和停止条件 | 项目从 Hello World/空服务端开始建设时 |
| 最近组员反馈提示词 | 对已经可运行的系统做预约、库存、日期和交互修复 | MVP 完成后的模拟器人工验收阶段 |

它们是给 AI 编程助手的工程任务说明。项目运行时不会自动读取这些文字，也不会把它们发送给华为 AI 平台或其他模型服务。

### 2.2 最初提供的 `/goal` 提示词（原文）

```text
/goal 在 D:\YOUR_CODE\tourism_services 中完成一个可运行、可验证、由 Git 管理的“智慧景区旅游服务系统”全栈 MVP：保留并扩展现有 HarmonyOS ArkTS 客户端，在空的 server/ 中实现 FastAPI 服务端；持续按检查点实现和验证，直到下述所有停止条件满足。不要停留在需求复述、设计稿、接口桩或纯 Mock 页面阶段。

一、开始前必须核实并保护现状

1. 先只读检查整个工作区、client/ 配置、可用工具和 Git 状态，不要假设已有业务实现。
2. 已知现状：根目录有 client/ 与空 server/；client/ 是 ArkTS + ArkUI + Stage 的 Hello World 骨架，支持 phone/tablet，target SDK 26.0.0，compatible SDK 6.1.0(23)；当前没有 Git 仓库。
3. 保留现有 DevEco 工程结构和 SDK 配置，除非构建证据表明必须调整。不要删除、重建或替换 client/。
4. 制定不超过 10 个检查点的 PLAN.md，并建立简短 PROGRESS.md。每个检查点必须包含交付物、验证命令和对应 Git 提交；持续更新状态，不要把计划当作最终交付。
5. 对普通、可逆且在任务范围内的实现自行决策和推进。只有缺少凭据/设备、需要不可逆外部操作或存在会改变产品方向的关键选择时才暂停请求用户。

二、Git 管理要求（已获得本地 Git 管理授权）

1. 在工作区根目录建立单一 monorepo：`git init -b main`。先添加根级 `.gitignore`，再检查所有待跟踪文件中是否含密钥或本机配置。
2. 根级 `.gitignore` 至少覆盖：根目录及子目录 `.idea/`、`.env`、`.venv/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、覆盖率文件、日志、SQLite 数据库、上传目录、Docker 临时数据、`client/local.properties`、`.hvigor/`、`oh_modules/`、所有 build 目录、HAP/APP 构建产物；保留并尊重 `client/.gitignore`。
3. 提交可公开的 `.env.example`，绝不提交真实 `.env`、密码、Token、签名材料、设备配置、数据库文件或用户数据。
4. 建立客户端原始骨架和仓库规范的基线提交，建议 `chore: establish project baseline`；然后创建 `feat/smart-tourism-mvp` 分支进行实现。
5. 之后按可运行的纵向切片做原子提交，使用清晰的 Conventional Commits。每次提交前查看 `git status` 与 `git diff`，只暂存本检查点文件，并在相关测试通过后提交。
6. 禁止使用 `git reset --hard`、`git clean`、强制 checkout、rebase、改写历史或删除既有用户文件。未经明确授权，不配置远程仓库、不 push、不 force-push。
7. 不修改全局 Git 身份；若提交身份未配置，不得编造姓名或邮箱，应明确报告，但继续完成可安全推进的实现并保持变更分组清晰。
8. Goal 结束时列出当前分支、提交历史、最终 `git status`。除明确说明的外部阻塞外，工作区应干净。

三、总体架构

1. 统一目录：
   - `client/`：HarmonyOS ArkTS/ArkUI 客户端；
   - `server/`：Python FastAPI 服务端；
   - `docs/`：架构、接口、数据模型、测试与压测说明；
   - 根目录 `README.md`、`PLAN.md`、`PROGRESS.md`、`.gitignore`、`docker-compose.yml`。
2. 客户端和服务端必须真实连通。常规业务数据通过 REST API 读写；实时人流、虚拟排队与客服消息至少有一条真实 WebSocket 闭环。不能把所有功能永久留在客户端本地 Mock。
3. 支付、人脸闸机、高精度地图、短信/推送、酒店商家系统和真实人流传感器等缺少外部凭据或硬件的能力，使用明确命名的 Provider 接口、可替换适配器和演示 Mock；界面与文档必须标注边界，不能虚称已接入真实服务。
4. 默认本地模式必须零外部服务即可运行：SQLite + 进程内安全降级。完整模式提供 PostgreSQL + Redis 的 Docker Compose。先验证 Docker daemon；不可用时继续完成 SQLite 模式和可审查的 Compose 配置，不得因此停止整个 Goal。

四、FastAPI 服务端要求

1. 使用 Python 3.12、uv、FastAPI、Uvicorn、Pydantic、SQLAlchemy 2、Alembic；统一通过 `uv sync`、`uv run ...` 管理与执行，不使用系统 `py` 命令，不全局安装依赖。
2. 建议分层：`app/api`、`app/models`、`app/schemas`、`app/services`、`app/repositories`、`app/core`、`app/websocket`、`tests`、`migrations`、`scripts`。禁止把全部业务堆进 `main.py`。
3. 提供 `/health`、OpenAPI `/docs`、统一错误响应、分页、校验、日志、CORS 开发配置、`.env.example`、数据库迁移和可重复种子数据。
4. 实现 JWT 登录与刷新、密码安全散列、游客/商家/客服/管理员角色权限。为演示提供非敏感测试账号并写入 README。
5. 数据模型及 API 至少覆盖：
   - 用户、角色、游客偏好；
   - 门票类型、预约日期/时段、库存、动态价格、订单、退款/改签、电子票二维码与核验记录；
   - 景点、文化讲解、路线节点、人流快照、行程；
   - 游乐项目、演出场次、预约、虚拟排队和快速通行券；
   - 酒店/民宿、房型、餐厅、套餐、住宿和餐饮预约、评价；
   - 商品、购物车、商城订单、配送信息、活动、积分流水和兑换；
   - 游客内容分享记录、反馈/投诉、处理状态、回访、客服会话与消息。
6. 交易型逻辑必须在服务端：库存防超卖、幂等下单、退改规则、预约冲突、积分记账与权限校验。SQLite 演示模式也要有正确约束；PostgreSQL/Redis 模式提供原子库存和限流设计。
7. Redis 完整模式用于缓存、限流、幂等键、库存原子操作、虚拟排队和 WebSocket 发布订阅。订单超时、预约提醒和积分发放可使用明确的后台任务抽象；如引入 Celery，必须提供可运行配置和降级路径，不能只加依赖不使用。
8. 使用 pytest、pytest-asyncio/httpx（按实际实现选择）、覆盖率和 Ruff。重点测试认证、权限、票价、库存并发、防重复下单、退改、预约冲突、积分、WebSocket 与错误响应。
9. 使用 Locust 提供登录、列表查询、抢票下单、预约、商城和实时连接的压测场景；运行本机可承受的 smoke/baseline 测试并保存摘要。1 万在线是部署目标：不得把小规模本机结果冒充达标，需给出服务器资源、连接池、worker/多实例、Redis、限流及扩容方案。

五、HarmonyOS 客户端要求

1. 继续使用 ArkTS、ArkUI、Stage 模型。为 `module.json5` 增加必要的网络权限；使用可配置 `API_BASE_URL`，禁止硬编码生产地址或秘密。
2. 从 Hello World 骨架建立清晰目录：`pages`、`components`、`models`、`services`/`network`、`stores`、`utils`、`config`、`resources`；把导航、状态、网络、持久化和业务逻辑分层。
3. 主导航建议为：首页、导览、行程、商城、我的。手机使用紧凑布局和底部导航；平板使用宽屏/分栏或侧边导航。适配横竖屏、窗口变化、深浅色、字体缩放和安全区域，避免只按单一固定尺寸设计。
4. 网络层必须包含超时、统一解析、认证 Token、错误映射、重试边界和离线判断；至少展示加载、空数据、失败、重试、无权限、库存变化和弱网状态。
5. 实现完整可点击闭环：
   - 门票：成人/儿童/学生/家庭票，日期与分时预约、余量、价格、确认下单、订单、二维码、退款和改签；
   - 导览：景区示意地图/地图适配器、定位演示、景点详情、文化/语音讲解控制、个性路线和人流避堵；
   - 项目：设施/演出预约、等待时间、提醒、取消、快速通行券及透明收费；
   - 餐住：酒店/民宿/房型/设施/评价，餐厅/套餐/时段，住玩和餐玩组合；
   - 商城：分类、详情、购物车、结算、配送、限时折扣、团购、积分兑换和内容分享积分；
   - 服务：反馈/投诉/建议、进度、客服对话、FAQ、回访与评分。
6. 关键订单、电子票、行程和离线包进行适当本地持久化；恢复联网后有明确同步策略。不得在客户端保存明文密码或长期敏感凭据。
7. 模板测试必须替换/扩展为真实业务测试；至少验证客户端的状态转换、输入校验、时间冲突/行程逻辑和服务错误映射。确认并实际运行可用的 DevEco/Hvigor lint、test、build 命令，并把命令写入 README。

六、必须真实呈现的 8 个创新点

每项必须在 UI 中有入口，具备交互、状态变化或算法/服务结果，并在 README 中逐项链接到实现文件；不能只是宣传卡片。

1. AI/规则融合个性行程管家：根据时长、兴趣、同行人群、体力和已预约项目生成时间轴并可重新规划；无模型密钥时使用可解释评分算法并保留 AI Provider。
2. 人流热力与动态避堵：通过服务端模拟/推送人流快照，在地图与景点中展示拥挤等级并动态给出替代路线。
3. 全行程冲突优化器：统一检查门票、演出、项目、餐饮和返程，计算步行缓冲并提出可执行调整。
4. 智慧排队联动：等待时间变化时，推荐附近低拥堵景点、餐厅或休息区，并联动调整后续行程。
5. 多人同行协作：邀请码组队、共享行程、集合点、成员状态、隐私开关与走散提醒演示。
6. 适老与无障碍模式：大字体、高对比度、语音辅助入口、无障碍/亲子推车路线，以及厕所、医务室和休息点。
7. 弱网离线旅行包与应急助手：离线电子票、核心地图/行程/讲解，断网提示、恢复同步、SOS 与疏散指引。
8. 文化数字护照与绿色积分：到访数字印章、文化探索与绿色出行任务、积分流水及商城兑换闭环。

七、建议检查点与提交节奏

1. 仓库初始化、根级规范、PLAN/PROGRESS、基线提交。
2. FastAPI 基础、配置、数据库、迁移、种子、健康检查、测试框架。
3. 认证权限与客户端网络/登录骨架。
4. 门票—库存—订单—二维码—退改完整纵向切片。
5. 导览—人流—路线—行程与前三项创新能力。
6. 项目预约/排队、餐饮住宿及对应客户端流程。
7. 商城/积分、反馈/客服、多人协作和无障碍模式。
8. 离线旅行包、应急、数字护照，以及 phone/tablet 全面适配。
9. 自动化测试、构建、WebSocket、压测、性能/安全检查和缺陷修复。
10. README、架构/API/Mock 边界文档、最终验收、整理提交和干净工作区。

可以根据依赖关系微调顺序，但每个检查点都必须得到可运行或可测试的纵向结果，不要一次性堆积大量未验证代码。

八、验证循环

每个检查点至少执行与变更相关的最快测试；定期执行完整验证。最终应实际执行并记录：

1. `uv sync`。
2. Alembic 升级到最新版本并重复验证种子初始化。
3. `uv run ruff check .`。
4. `uv run pytest`（包含覆盖率摘要）。
5. 启动 FastAPI 后验证 `/health`、`/docs`、核心 REST 流程和 WebSocket 流程。
6. 运行 Locust smoke/baseline，并记录规模、耗时、错误率和环境限制。
7. 在 `client/` 安装 ohpm 依赖，执行当前 DevEco 版本实际支持的 lint、单元测试和 debug HAP 构建命令；不要猜命令，先从项目和已安装工具确认，并将最终命令记录到 README。
8. 如本机模拟器可用，至少启动手机模拟器验证主流程，并对平板预览/模拟器检查宽屏布局；若 GUI、签名或镜像属于外部阻塞，必须完成 CLI 构建并提供精确的人工验证步骤和未验证声明。
9. 搜索并确认不存在密钥、`.env`、本机路径误提交、调试占位、未处理异常、死链接或把 Mock 冒充真实服务的文本。
10. `git status`、`git log --oneline --decorate`，确认提交历史与工作区状态。

九、Goal 停止条件

只有同时满足以下条件才能将 Goal 标记完成：

1. 根目录 Git 仓库和功能分支已建立，有基线及按检查点组织的清晰本地提交；未 push，最终状态干净或剩余项有明确解释。
2. FastAPI 服务端可从全新环境按 README 启动；迁移、种子、认证、核心数据模型、REST、至少一条 WebSocket、测试和 OpenAPI 均可用。
3. HarmonyOS 客户端不再是 Hello World，能够构建，并通过真实 API 完成登录、门票下单/退改、预约、导览/行程、餐住、商城/积分和反馈/客服的演示闭环。
4. phone 与 tablet 均有明确响应式实现和验证证据；关键加载、空、错、弱网及离线恢复状态存在。
5. 8 个创新点都有可操作实现和 README 对照表；外部能力均通过明确适配器/Mock 边界处理。
6. 服务端测试、客户端相关测试、lint、构建和 API/WebSocket smoke 全部通过；Locust 已实际运行并如实记录结果与 1 万在线扩容方案。
7. 根 README 包含环境要求、前后端启动顺序、测试/构建命令、模拟器访问本机 API 方法、演示账号、架构、功能、创新点、外部能力边界、压测结论及常见故障。
8. PROGRESS.md 反映真实最终状态，不存在把未验证、占位或纯文档功能标为完成的情况。

若某项仅因外部账号、证书、真机硬件或不可用 GUI 被阻塞，先穷尽安全替代方案并完成其余工作；最后准确记录阻塞、已有证据和用户下一步，不得虚报完成。保持简洁的阶段进度更新，持续推进直到达到上述可验证停止条件。
```

### 2.3 最近组员反馈问题提示词（原文）

```text
这些是我的组员反映的问题，请做出针对性修改：
1.行程的同行人群和体力等级都不能修改
2.时间不冲突的演出也不能一起选
3.门票预约的冲突检测也有问题（退款的话票的余量要恢复吗，不确定）
4.演出项目的预约冲突检测也有问题
5.门票预约的日期可以修改但是没用（与票的数据没关系）
6.文旅商城的商品余量无效
```

### 2.4 使用说明

- `/goal` 原文记录的是项目初始状态，其中“尚未建立 Git”“`server/` 为空”“建立功能分支”“未经授权不 push”等描述属于当时的前提。当前仓库已经完成实现、连接远端，并按后续要求只保留 `main`，因此不能把这段历史提示词不加判断地重新执行。
- 组员反馈提示词是增量验收输入，应建立在当前代码和现有数据模型之上使用，不能通过删除冲突检测或伪造库存变化来表面消除问题。
- 若把两段提示词交给新的 AI 编程助手，应同时要求它先读取当前 Git 状态、README、运行文档和测试结果，再决定需要执行的部分。
- 提示词中不得加入真实密码、Token、证书、个人数据或生产数据库内容。
- 除上述两段外，普通问答、启动排错和中间修改请求不列入本说明。
