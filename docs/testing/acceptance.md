# 最终验收手册

本文档给出当前仓库快照的可重复验收顺序和已接受证据。命令以 PowerShell 7 为例；
除单独注明外，从仓库根目录开始。每次数据库型验收使用一个从未存在过的新 SQLite 文件，
避免旧订单、库存、refresh session 或幂等记录影响结果。

需要保留 Compose 命名卷、反复启动并连接 HarmonyOS 客户端时，使用
[全栈日常启动指南](full-stack-startup.md)；本文专注可隔离复验的验收证据。

## 已接受证据总表

本表记录 2026-09-04（Asia/Shanghai）的已接受结果；以“待”开头的状态不等同于通过。

| 边界 | 规范命令/证据 | 已接受结果 | 状态 |
|---|---|---|---|
| Python 依赖 | `uv sync --frozen`，依据 `server/uv.lock` | 同步成功 | 通过 |
| 空库迁移 | 对同一新库执行两次 `uv run alembic upgrade head` | 首次到 head，第二次无新增迁移 | 通过 |
| 应用种子 | 对同一库执行两次 `uv run tourism-seed` | 首次 applied，第二次 already applied | 通过 |
| Python lint | `uv run ruff check .` | 0 错误 | 通过 |
| 服务端测试/覆盖率 | `uv run pytest`；配置内置 branch coverage 和 `fail_under=70` | 146 passed，覆盖率 72.63%，含注册安全与 PostgreSQL 离线 DDL 门禁 | 通过 |
| 真实网络 smoke | 独立服务 + `uv run tourism-smoke` | 当前 runner 49/49，含注册 3 项与 3 条 WebSocket 契约 | 通过 |
| Locust 本机基线 | SHA-256 校验的 CSV 证据 | 320 请求、0 失败、11.42 req/s、aggregate p95 160 ms | 通过（仅本机基线） |
| Compose 静态边界 | `docker compose config --quiet` | 退出码 0 | 通过 |
| Compose 运行时 | API + PostgreSQL 16 + Redis 7，双 Uvicorn worker | 三个服务 healthy；空库到 `0007`、重复迁移/seed、drift、Redis PONG、health/docs 均通过 | 通过 |
| Compose Locust | 独立的 SHA-256 校验 CSV | 5 users / 30 s；319 请求、0 失败、11.33 req/s、aggregate p95 130 ms | 通过（仅本机基线） |
| OHPM 依赖与 lock | `ohpm install` 并检查 `client/oh-package-lock.json5` | 安装退出码 0；仅公开 `@ohos/hypium@1.0.25` 地址、版本和 integrity，无本机路径 | 通过 |
| DevEco Code Linter | 本文给出的两个位置参数命令 | `No defects found`，Errors/Warns/Suggestions 均为 0 | 通过（支持的规则集） |
| Hypium 本地测试 | `entry@default` Hvigor test | 45 passed，Failure 0，Error 0 | 通过 |
| on-device 测试包 | `entry@ohosTest` debug HAP | 4 个用例编译成功 | 通过（仅编译） |
| 客户端应用包 | `entry@default` debug HAP | 编译成功，CLI 产物未签名 | 通过（仅编译） |
| 模拟器/真机矩阵 | 在 DevEco Studio 运行 `entry@ohosTest` 与人工流程 | 执行结果由测试人员按本文矩阵记录 | 待人工复验 |
| 仓库卫生 | 敏感签名、本机路径、忽略、diff、status、log 检查 | 已接受快照无待提交秘密或用户目录路径 | 通过；交付前重跑 |

## 1. 服务端：从锁文件到空数据库

前置条件为 Python 3.12+ 和 uv。使用仓库内忽略的 cache，可避开全局 cache 权限差异。
以下命令从仓库根目录执行：

```powershell
Set-Location server

$repoRoot = (Resolve-Path ..).Path
$uvCache = Join-Path $repoRoot '.uv-cache'
New-Item -ItemType Directory -Force -Path $uvCache | Out-Null
$env:UV_CACHE_DIR = $uvCache

uv sync --frozen

New-Item -ItemType Directory -Force -Path './data' | Out-Null
$acceptanceDb = Join-Path $PWD.Path ("data/acceptance-{0}.db" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $acceptanceDb) {
  throw "Acceptance database must be new: $acceptanceDb"
}
$databasePath = $acceptanceDb.Replace('\', '/')

$env:APP_ENV = 'development'
$env:DATABASE_URL = "sqlite+aiosqlite:///$databasePath"
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:JWT_SECRET_KEY = [Convert]::ToBase64String(
  [Security.Cryptography.RandomNumberGenerator]::GetBytes(48)
)

uv run alembic upgrade head
uv run alembic upgrade head
uv run alembic current

uv run tourism-seed
uv run tourism-seed

uv run ruff check .
uv run pytest
```

验收点：

- `uv sync --frozen` 不改写 lock，且安装默认 dev dependency group。
- `alembic current` 应指向 head；第二次 upgrade 不创建另一套 schema。
- 两次 seed 后业务目录、库存、演示账号与离线 manifest 不重复；第二次输出
  `Application seed already applied.`。
- canonical `uv run pytest` 已通过 146 个测试，分支覆盖率 72.63%；`server/pyproject.toml` 自动追加
  strict config/markers、隔离 basetemp、`--cov=app` 和 missing-lines 报告，并对 branch
  coverage 施加 70% 下限。不要用省略 coverage addopts 的局部命令代替最终门禁。

## 2. 真实 Uvicorn 的 49-check smoke

smoke 命令不导入 ASGI app，必须连接另一个进程中的真实监听器。继续使用上一节已迁移、
已 seed 的数据库。在终端 A（`server/`）运行：

```powershell
$env:CROWD_PUBLISH_INTERVAL_SECONDS = '0.5'
$env:QUEUE_PUBLISH_INTERVAL_SECONDS = '0.5'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

在终端 B（`server/`）运行：

```powershell
$env:UV_CACHE_DIR = (Join-Path (Resolve-Path ..).Path '.uv-cache')
uv run tourism-smoke --base-url http://127.0.0.1:8765 --timeout 10
```

接受输出为：

```text
Real-network smoke passed (49 checks).
```

49 项覆盖 health、Swagger docs、capability metadata、游客注册、注册后会话、重复用户名冲突、
登录、门票下单/支付/QR/核验窗口、
项目预约确认/取消、商城结算/支付、离线包/同步/SOS/护照/绿色任务，以及三条实时契约：
crowd 初始帧和后续 tick、queue 初始帧/更新及一次性 ticket 拒绝、support 游客与演示
bot 消息和 REST 持久化回读。完成后在终端 A 使用 Ctrl+C 正常停止监听器。

## 3. Locust 基线与证据完整性

### 已接受结果

已接受的 loopback 运行是 5 users、5 users/s、30 s。CSV 汇总是唯一规范计量来源：

| 指标 | 值 |
|---|---:|
| 请求 | 320 |
| 失败 | 0（0.00%） |
| 吞吐 | 11.42 requests/s |
| p95 | 160 ms |

它证明单开发机上的场景可执行，不是生产容量、SLO、饱和点、10,000 在线能力或
PostgreSQL/Redis/多 worker/WebSocket 长连接容量声明。完整环境和解释见
`docs/performance/README.md` 与 `docs/performance/10k-capacity-plan.md`。

### 校验证据 SHA-256

从 `server/` 运行：

```powershell
$evidenceDir = (Resolve-Path '../docs/performance').Path
$checksumFile = Join-Path $evidenceDir 'baseline-5u-30s_SHA256SUMS.txt'

Get-Content -LiteralPath $checksumFile | ForEach-Object {
  $expected, $fileName = $_ -split '\s+', 2
  $artifact = Join-Path $evidenceDir $fileName.Trim()
  $actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $expected) {
    throw "Checksum mismatch: $fileName"
  }
  "verified $fileName $actual"
}
```

接受的摘要为：

| 文件 | SHA-256 |
|---|---|
| `baseline-5u-30s_exceptions.csv` | `50e001907ccff3338f25a2c46417065abf1a828feb0bcf1a8e01d039eb762bf2` |
| `baseline-5u-30s_failures.csv` | `a0f766d126247d27179b2ab30fd2156f5f16130ff67b761a23011a8a32b3934c` |
| `baseline-5u-30s_stats_history.csv` | `eef79f2aef3507b62312b88850a6004845b9bdbce202b1e3a7b32ee2bf6aa36f` |
| `baseline-5u-30s_stats.csv` | `92aaa9ad2027d7f99c495fe9f49154baaa2332a80c1ef816ca63b04e0c013e86` |

### 可比重跑

可比重跑必须使用另一空库，因为场景会消耗库存并创建持久订单。终端 A 在
`server/` 中设置新数据库并无回显读取本地 load password：

```powershell
New-Item -ItemType Directory -Force -Path './data' | Out-Null
$loadDb = Join-Path $PWD.Path ("data/load-{0}.db" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $loadDb) {
  throw "Load database must be new: $loadDb"
}
$env:APP_ENV = 'development'
$env:DATABASE_URL = "sqlite+aiosqlite:///$($loadDb.Replace('\', '/'))"
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:CROWD_PUBLISH_INTERVAL_SECONDS = '30'
$env:QUEUE_PUBLISH_INTERVAL_SECONDS = '15'
$securePassword = Read-Host 'Synthetic load-user password (at least 12 characters)' -AsSecureString
$env:TOURISM_LOAD_USER_PASSWORD = [Net.NetworkCredential]::new('', $securePassword).Password

uv run alembic upgrade head
uv run tourism-load-seed --count 10
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

在终端 B 的 `server/` 中设置相同的本地-only password，再运行：

```powershell
$securePassword = Read-Host 'Same synthetic load-user password (at least 12 characters)' -AsSecureString
$env:TOURISM_LOAD_USER_PASSWORD = [Net.NetworkCredential]::new('', $securePassword).Password
$env:TOURISM_LOAD_USER_COUNT = '10'
$env:TOURISM_LOAD_USER_OFFSET = '0'
$reproPrefix = Join-Path $env:TEMP ("tourism-locust-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

uv run locust -f load/locustfile.py `
  --host http://127.0.0.1:8765 `
  --headless --users 5 --spawn-rate 5 --run-time 30s --stop-timeout 5 `
  --csv $reproPrefix --csv-full-history --only-summary
```

确认 aggregate 和每个必需 workflow 均出现在 `*_stats.csv`，同时
`*_failures.csv`、`*_exceptions.csv` 只有 header。不要覆盖已接受的
`baseline-5u-30s_*` 文件，除非本次运行明确成为新的评审基线并重新生成 checksums。

## 4. Docker Compose：静态与运行时边界

从仓库根目录执行静态门禁：

```powershell
docker compose config --quiet
```

静态检查本身只证明 Compose 合并/插值有效。2026-09-04 的接受运行进一步使用真实
Docker Desktop Linux engine 验证了 PostgreSQL 16、Redis 7 和两个 Uvicorn worker。
本机 Windows PostgreSQL 服务占用 `5432`，因此接受运行将宿主机端口改为 `15432`；
容器内 API 仍连接 `postgres:5432`。下面使用唯一 project name 创建独立命名卷，保证
每次从空库开始，也避免复用旧卷时任意更换 `POSTGRES_PASSWORD` 导致凭据不一致。
运行前应停止占用 8000、15432、16379 的其他测试栈：

```powershell
$composeProject = "smart-tourism-acceptance-$((Get-Date).ToString('yyyyMMdd-HHmmss'))"
$env:APP_ENV = 'development'
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:API_PORT = '8000'
$env:POSTGRES_USER = 'tourism'
$env:POSTGRES_DB = 'tourism'
$env:POSTGRES_PORT = '15432'
$env:REDIS_PORT = '16379'
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$jwtBytes = New-Object byte[] 48
$postgresBytes = New-Object byte[] 24
try {
  $rng.GetBytes($jwtBytes)
  $rng.GetBytes($postgresBytes)
  $env:JWT_SECRET_KEY = [Convert]::ToBase64String($jwtBytes)
  $env:POSTGRES_PASSWORD = -join ($postgresBytes | ForEach-Object { $_.ToString('x2') })
} finally {
  $rng.Dispose()
}

docker compose -p $composeProject config --quiet
docker compose -p $composeProject up --build --detach --wait --wait-timeout 180
docker compose -p $composeProject ps

$apiContainer = docker compose -p $composeProject ps -q api
docker inspect --format 'health={{.State.Health.Status}} restarts={{.RestartCount}}' $apiContainer
Invoke-RestMethod http://127.0.0.1:8000/health
"docs_status=$((Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/docs).StatusCode)"

docker compose -p $composeProject exec -T api uv run --no-sync alembic upgrade head
docker compose -p $composeProject exec -T api uv run --no-sync alembic current
docker compose -p $composeProject exec -T api uv run --no-sync alembic check
docker compose -p $composeProject exec -T api uv run --no-sync tourism-seed
docker compose -p $composeProject exec -T api uv run --no-sync tourism-seed
docker compose -p $composeProject exec -T redis redis-cli ping
docker compose -p $composeProject exec -T postgres psql -U tourism -d tourism -tAc `
  "SELECT version_num FROM alembic_version; SELECT count(*) FROM pg_tables WHERE schemaname='public';"

Set-Location server
$env:UV_CACHE_DIR = (Join-Path (Resolve-Path ..).Path '.uv-cache')
uv sync --frozen
uv run tourism-smoke --base-url http://127.0.0.1:8000 --timeout 45

$loadSecret = Read-Host 'Synthetic load-user password (at least 12 characters)' -AsSecureString
$loadPassword = [Net.NetworkCredential]::new('', $loadSecret).Password
docker compose -f ..\docker-compose.yml -p $composeProject exec -T `
  -e "TOURISM_LOAD_USER_PASSWORD=$loadPassword" `
  api uv run --no-sync tourism-load-seed --count 10
$env:TOURISM_LOAD_USER_PASSWORD = $loadPassword
$env:TOURISM_LOAD_USER_COUNT = '10'
$env:TOURISM_LOAD_USER_OFFSET = '0'
$reproPrefix = Join-Path $env:TEMP ("tourism-compose-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
uv run locust -f load/locustfile.py `
  --host http://127.0.0.1:8000 `
  --headless --users 5 --spawn-rate 5 --run-time 30s --stop-timeout 5 `
  --csv $reproPrefix --csv-full-history --only-summary
Import-Csv "${reproPrefix}_stats.csv" | Where-Object Name -eq 'Aggregated'
if ((Import-Csv "${reproPrefix}_failures.csv").Count -ne 0) { throw 'Locust failures found' }
if ((Import-Csv "${reproPrefix}_exceptions.csv").Count -ne 0) { throw 'Locust exceptions found' }
Set-Location ..
```

接受结果：三个服务均 healthy 且 API restart count 为 0；PostgreSQL 从空库迁移到
`20260901_0007 (head)`，共有 76 张业务表（另有 `alembic_version`），重复 upgrade
无操作、`alembic check` 无 drift、重复 seed 输出 already applied；health/docs 为 200，
Redis 返回 PONG。该组不可变 Locust CSV 关联的 preflight runner 为 46 checks；当前验收
runner 独立通过 49 checks，其中包含 3 项注册检查。随后 5 users / 30 s 的 Compose Locust CSV
记录 319 请求、0 失败、11.33 req/s、p95 130 ms、p99 350 ms、最大 367.80 ms；
终端在 graceful shutdown 后为 324 请求、0 失败。原始文件与 SHA-256 见
[`docs/performance/README.md`](../performance/README.md)。这些结果仍不是生产 SLO 或
10,000 在线容量声明。生产部署还必须使用 secret manager、HTTPS、显式 CORS/trusted
hosts，并关闭 demo accounts。

完成上述独立验收后，以下命令只删除本次唯一 project 的容器、网络和测试卷；确认
`$composeProject` 仍是本次生成的值后再执行：

```powershell
docker compose -p $composeProject down --volumes
```

日常项目若需要保留数据则使用 `docker compose down`，并在后续启动时沿用初始化该卷的
`POSTGRES_PASSWORD`。

## 5. HarmonyOS 客户端 CLI

前置条件为 DevEco Studio 26 工具链。命令从 `client/` 执行；安装目录必须由当前机器
提供，不把盘符或用户目录写入仓库：

```powershell
$devecoRoot = '<DevEco Studio installation directory>'
$env:DEVECO_SDK_HOME = Join-Path $devecoRoot 'sdk'

& (Join-Path $devecoRoot 'tools/ohpm/bin/ohpm.bat') install

& (Join-Path $devecoRoot 'tools\node\node.exe') (Join-Path $devecoRoot 'plugins\codelinter\run\index.js') -c code-linter.json5 -p default -e error (Join-Path $devecoRoot 'sdk\default\openharmony') .

& (Join-Path $devecoRoot 'tools/hvigor/bin/hvigorw.bat') `
  test --mode module -p product=default -p module=entry@default `
  -p buildMode=debug --no-daemon

& (Join-Path $devecoRoot 'tools/hvigor/bin/hvigorw.bat') `
  assembleHap --mode module -p product=default -p module=entry@ohosTest `
  -p buildMode=debug --no-daemon

& (Join-Path $devecoRoot 'tools/hvigor/bin/hvigorw.bat') `
  assembleHap --mode module -p product=default -p module=entry@default `
  -p buildMode=debug --no-daemon

& (Join-Path $devecoRoot 'sdk/default/openharmony/toolchains/hdc.exe') list targets
```

Code Linter 命令最后有两个必需位置参数，顺序必须精确为：

1. `<DevEco root>/sdk/default/openharmony`（OpenHarmony SDK）；
2. `.`（项目目录）。

只传 `.` 会把项目误当成 SDK。当前 gate 的
`plugin:@typescript-eslint/recommended` 与 `plugin:@security/recommended`
真实执行并返回 `No defects found`。附带 `arkPerfCheck` 的 cross-device 扩展会在
6 个大型 ArkUI 文件上触发其内部 `getDeclaringMethod` 异常，因此当前结果只声明
配置中受支持规则、ArkTS 编译和设备矩阵边界，不声明该扩展完整覆盖。

`ohpm install` 已成功完成，仓库 lock 只解析公开的 `@ohos/hypium@1.0.25`，不含
`file:` 或本机路径。Hypium `entry@default` 已执行 45 个用例，Failure 0、Error 0；
包含 4 个用例的 `entry@ohosTest` 与 `entry@default` debug HAP 均已成功编译。

## 6. DevEco 模拟器、签名与 phone/tablet 人工矩阵

CLI HAP 未签名，证书、私钥、设备标识和本机 signing profile 由 DevEco Studio 管理。
因此 `entry@ohosTest` 的 4 个用例编译成功与模拟器执行是两项独立证据；当前执行结果仍由
测试人员在已启动且完成本地签名的模拟器上记录。

连接 phone/tablet 或模拟器并在 DevEco Studio 完成本机自动签名后，先运行
`entry@ohosTest`；接受条件是 `onDeviceBusinessSmoke` 的 4 个用例全部通过。随后
记录设备型号、HarmonyOS/API 版本、实际 vp、方向、主题、字号、结果和截图编号：

人工业务验收从游客注册开始：在游客态打开受保护操作，从登录弹层切换到“注册”，填写
显示名称、唯一的小写用户名、同时含英文字母和数字的 8 位以上密码及确认密码。点击
“注册并登录”后，弹层应关闭并显示新游客身份，受保护功能可直接访问。退出后以相同
用户名再次注册应显示重复用户名提示；空显示名称、非法用户名、弱密码和两次密码不一致
应分别给出可恢复的字段提示。

| 形态 | 视口 / 方向 | 模式 | 主要接受条件 | 当前状态 |
|---|---|---|---|---|
| phone | 360 × 800，竖屏 | 浅色、标准字号 | 底部五栏；注册/自动登录、门票、排队、餐住及返回状态正确 | 待人工复验 |
| phone | 360 × 800，竖屏 | 深色、大字、高对比 | 底栏增高；文本不截断、按钮可达、可滚动、焦点和对比清晰 | 待人工复验 |
| phone | 800 × 360，横屏 | 浅色、标准字号 | 719/720vp 阈值无重复导航、闪烁或内容遮挡 | 待人工复验 |
| tablet | 800 × 1280，竖屏 | 浅色、标准字号 | 左侧五栏；主栏和门票/预约子页正确占用内容区 | 待人工复验 |
| tablet | 1280 × 800，横屏 | 深色、大字、高对比 | 侧栏增宽；双栏、弹层、长列表、空/错/离线态无溢出 | 待人工复验 |

每行还要先抽查注册弹层、字段校验、注册后自动登录及重复用户名提示，再检查登录/退出后
敏感状态清除；门票报价到退改；餐住重复时段提示及确认/取消后的卡片刷新；导览路线结果卡与节点高亮、人流、行程与 queue
WebSocket 断开重连及旧 sequence 丢弃；商城、积分、客服、同行隐私和无障碍偏好；
离线冷启动/outbox、SOS Demo、护照和绿色积分的 demo 标记。失败项必须附最短复现步骤。

## 7. Secrets、本机路径与 Git 交付检查

从仓库根目录运行。第一组确认应忽略的本机文件没有被跟踪：

```powershell
git check-ignore -v client/local.properties server/.env .uv-cache

git ls-files -- `
  client/local.properties server/.env `
  '*.pem' '*.key' '*.p12' '*.pfx' '*.jks' '*.keystore' '*.hap'
```

`git ls-files` 应无输出。下一组扫描常见私钥/credential 签名与用户目录绝对路径；
接受条件是两次 `git grep` 都返回“无匹配”（退出码 1），而不是工具错误：

```powershell
$secretPattern = 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}'
git grep -n -I -E $secretPattern -- . ':(exclude)docs/testing/acceptance.md'
if ($LASTEXITCODE -eq 0) { throw 'Potential tracked secret found' }
if ($LASTEXITCODE -ne 1) { throw 'Secret scan failed' }

$pathPattern = '([A-Za-z]:\\Users\\|/Users/|/home/)'
git grep -n -I -E $pathPattern -- . ':(exclude)docs/testing/acceptance.md'
if ($LASTEXITCODE -eq 0) { throw 'Tracked user-specific absolute path found' }
if ($LASTEXITCODE -ne 1) { throw 'Path scan failed' }

git grep -n -I -E '(file:|[A-Za-z]:\\)' -- client/oh-package-lock.json5
if ($LASTEXITCODE -eq 0) { throw 'OHPM lock contains a local dependency or Windows path' }
if ($LASTEXITCODE -ne 1) { throw 'OHPM lock portability scan failed' }
```

最后检查 patch 可应用性和提交边界：

```powershell
git diff --check
git status --short --branch
git diff --stat
git log --oneline --decorate -n 15
```

`git diff --check` 应无输出；status/stat 只能出现本次明确交付的文件，不应包含
`.env`、数据库、coverage、HAP、签名、`local.properties`、`oh_modules`、
`.venv` 或 cache。提交后最终 status 应干净，log 应包含预期提交且顺序正确。
