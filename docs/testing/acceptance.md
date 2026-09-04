# 最终验收手册

本文档给出当前仓库快照的可重复验收顺序和已接受证据。命令以 PowerShell 7 为例；
除单独注明外，从仓库根目录开始。每次数据库型验收使用一个从未存在过的新 SQLite 文件，
避免旧订单、库存、refresh session 或幂等记录影响结果。

## 已接受证据总表

本表记录 2026-09-04（Asia/Shanghai）的已接受结果；“待环境复验”不等同于通过。

| 边界 | 规范命令/证据 | 已接受结果 | 状态 |
|---|---|---|---|
| Python 依赖 | `uv sync --frozen`，依据 `server/uv.lock` | 同步成功 | 通过 |
| 空库迁移 | 对同一新库执行两次 `uv run alembic upgrade head` | 首次到 head，第二次无新增迁移 | 通过 |
| 应用种子 | 对同一库执行两次 `uv run tourism-seed` | 首次 applied，第二次 already applied | 通过 |
| Python lint | `uv run ruff check .` | 0 错误 | 通过 |
| 服务端测试/覆盖率 | `uv run pytest`；配置内置 branch coverage 和 `fail_under=70` | 129 passed，覆盖率 72.75%，通过 70% 门禁 | 通过 |
| 真实网络 smoke | 独立 Uvicorn + `uv run tourism-smoke` | 46/46，含 3 条 WebSocket 契约 | 通过 |
| Locust 本机基线 | 已签名 CSV 证据 | 320 请求、0 失败、11.42 req/s、aggregate p95 160 ms | 通过（仅本机基线） |
| Compose 静态边界 | `docker compose config --quiet` | 退出码 0 | 通过 |
| Compose 运行时 | API + PostgreSQL + Redis | Docker Desktop Linux daemon 不可用 | 待环境复验 |
| OHPM 依赖与 lock | `ohpm install` 并检查 `client/oh-package-lock.json5` | 安装退出码 0；仅公开 `@ohos/hypium@1.0.25` 地址、版本和 integrity，无本机路径 | 通过 |
| DevEco Code Linter | 本文给出的两个位置参数命令 | `No defects found`，Errors/Warns/Suggestions 均为 0 | 通过（支持的规则集） |
| Hypium 本地测试 | `entry@default` Hvigor test | 37 passed，Failure 0，Error 0 | 通过 |
| on-device 测试包 | `entry@ohosTest` debug HAP | 编译成功 | 通过（仅编译） |
| 客户端应用包 | `entry@default` debug HAP | 编译成功，CLI 产物未签名 | 通过（仅编译） |
| hdc/真机矩阵 | `hdc list targets` 及本文矩阵 | `[Empty]`；没有已签名 phone/tablet 目标 | 待环境复验 |
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
- canonical `uv run pytest` 已通过 129 个测试，分支覆盖率 72.75%；`server/pyproject.toml` 自动追加
  strict config/markers、隔离 basetemp、`--cov=app` 和 missing-lines 报告，并对 branch
  coverage 施加 70% 下限。不要用省略 coverage addopts 的局部命令代替最终门禁。

## 2. 真实 Uvicorn 的 46-check smoke

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
Real-network smoke passed (46 checks).
```

46 项覆盖 health、Swagger docs、capability metadata、登录、门票下单/支付/QR/核验窗口、
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

该检查已通过，只证明 Compose 合并/插值有效；不证明镜像能构建、容器能启动、迁移能在
PostgreSQL 上成功、Redis 协调健康或多 worker 正确。

当前机器的 Docker Desktop Linux daemon 不可用，命名管道
`//./pipe/dockerDesktopLinuxEngine` 不存在，因此 API + PostgreSQL + Redis
运行时拓扑尚未验收。daemon 可用后，使用本地 secret 在仓库根目录执行以下待验步骤：

```powershell
$env:APP_ENV = 'development'
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:COMPOSE_PROJECT_NAME = "smart-tourism-acceptance-$((Get-Date).ToString('yyyyMMdd-HHmmss'))"
$env:JWT_SECRET_KEY = [Convert]::ToBase64String(
  [Security.Cryptography.RandomNumberGenerator]::GetBytes(48)
)
$postgresSecret = Read-Host 'Local PostgreSQL password' -AsSecureString
$env:POSTGRES_PASSWORD = [Net.NetworkCredential]::new('', $postgresSecret).Password

docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 120
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health

Set-Location server
$env:UV_CACHE_DIR = (Join-Path (Resolve-Path ..).Path '.uv-cache')
uv run tourism-smoke --base-url http://127.0.0.1:8000 --timeout 10
Set-Location ..

docker compose down --volumes
```

接受条件是三个服务均 healthy、迁移和 seed 成功、health 为 200、46-check smoke
通过，且 Redis-required 模式没有 local-degraded 标记。生产部署还必须使用 secret
manager、HTTPS、显式 CORS/trusted hosts，并关闭 demo accounts。

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
`file:` 或本机路径。Hypium `entry@default` 已执行 37 个用例，Failure 0、Error 0；
`entry@ohosTest` 与 `entry@default` debug HAP 均已成功编译。

## 6. hdc、签名与 phone/tablet 人工矩阵

当前 `hdc list targets` 返回 `[Empty]`。CLI HAP 未签名，而仓库有意不提交证书、
私钥、设备标识或本机 signing profile。因此 on-device `entry@ohosTest` 和人工矩阵
尚未执行，不能把“HAP 编译通过”报告为“真机通过”。

连接 phone/tablet 或模拟器并在 DevEco Studio 完成本机自动签名后，先运行
`entry@ohosTest`；接受条件是 `onDeviceBusinessSmoke` 的 3 个用例全部通过。随后
记录设备型号、HarmonyOS/API 版本、实际 vp、方向、主题、字号、结果和截图编号：

| 形态 | 视口 / 方向 | 模式 | 主要接受条件 | 当前状态 |
|---|---|---|---|---|
| phone | 360 × 800，竖屏 | 浅色、标准字号 | 底部五栏；登录、门票、排队、餐住及返回状态正确 | 待设备/签名 |
| phone | 360 × 800，竖屏 | 深色、大字、高对比 | 底栏增高；文本不截断、按钮可达、可滚动、焦点和对比清晰 | 待设备/签名 |
| phone | 800 × 360，横屏 | 浅色、标准字号 | 719/720vp 阈值无重复导航、闪烁或内容遮挡 | 待设备/签名 |
| tablet | 800 × 1280，竖屏 | 浅色、标准字号 | 左侧五栏；主栏和门票/预约子页正确占用内容区 | 待设备/签名 |
| tablet | 1280 × 800，横屏 | 深色、大字、高对比 | 侧栏增宽；双栏、弹层、长列表、空/错/离线态无溢出 | 待设备/签名 |

每行还要抽查：登录/退出后敏感状态清除；门票报价到退改；导览、人流、行程与 queue
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
