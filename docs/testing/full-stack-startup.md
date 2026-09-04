# 全栈日常启动（Windows PowerShell 5.1）

本文是当前系统的日常运行手册：使用 Compose 命名卷保留 PostgreSQL/Redis 数据，适合反复启动、停止和开发。需要从全新空卷做一次隔离验收时，请改用[隔离空卷验收指南](acceptance.md)，不要混用两套流程。项目总览见[根 README](../../README.md)，实际编排以 [docker-compose.yml](../../docker-compose.yml) 为准。如果 `docker compose ps` 已显示三个服务均为 `healthy`，可直接从第 3 节继续验证，不必重新生成 JWT 或重建容器。

## 1. 准备与环境变量

在仓库根目录打开 **Windows PowerShell 5.1**。如果 Docker Desktop 尚未运行，先启动并等待引擎就绪：

```powershell
Set-Location '<tourism_services 仓库目录>'
$PSVersionTable.PSVersion
docker desktop start
docker version
docker compose version
docker info
```

`docker info` 必须同时显示 Client 与 Server。每个新的 PowerShell 会话都设置以下变量。
本仓库日常测试卷使用下列 URL-safe 本地密码；如果某个既有卷初始化时使用了其他密码，
必须继续提供那个原值，因为仅修改环境变量不会替换库内密码。

```powershell
$env:APP_ENV = 'development'
$env:POSTGRES_USER = 'tourism'
$env:POSTGRES_DB = 'tourism'
$env:POSTGRES_PORT = '15432'
$env:POSTGRES_PASSWORD = 'local-tourism-db-password'
$env:REDIS_PORT = '6379'
$env:API_PORT = '8000'
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:TRUSTED_HOSTS = 'localhost,127.0.0.1,api,testserver,10.0.2.2'

if ($env:POSTGRES_PASSWORD -notmatch '^[A-Za-z0-9._~-]{12,}$') {
    throw 'POSTGRES_PASSWORD 必须复用至少 12 位的 URL-safe 本机密码'
}

$jwtBytes = New-Object byte[] 48
$jwtRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $jwtRng.GetBytes($jwtBytes)
    $env:JWT_SECRET_KEY = [Convert]::ToBase64String($jwtBytes)
}
finally {
    $jwtRng.Dispose()
}

"JWT length=$($env:JWT_SECRET_KEY.Length)"
```

输出应为 `JWT length=64`。以上密钥由 CSPRNG 生成，并兼容 Windows PowerShell 5.1。
不要把数据库密码或 JWT 的实际值贴进工单或提交到仓库。真机测试时，把开发机实际
局域网 IPv4 追加到 `TRUSTED_HOSTS`；不要原样保留示例地址。

## 2. 配置检查与启动

```powershell
docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 180
docker compose ps
```

正常端口为：API `8000`、PostgreSQL 宿主机端口 `15432`（容器内 `5432`）、Redis `6379`。检查健康状态和日志：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8000/health'
docker compose logs --tail 100 api postgres redis
```

Swagger UI 位于 <http://127.0.0.1:8000/docs>。

持续查看 API 日志可运行 `docker compose logs --follow --tail 100 api`；按 `Ctrl+C` 只退出日志跟随，不会停止容器。

## 3. 数据库、缓存与幂等性检查

下面的 `upgrade` 和 seed 各执行两次；第二次仍须成功，以确认重复执行安全：

```powershell
docker compose exec -T api uv run --no-sync alembic current
docker compose exec -T api uv run --no-sync alembic check

docker compose exec -T api uv run --no-sync alembic upgrade head
docker compose exec -T api uv run --no-sync tourism-seed
docker compose exec -T api uv run --no-sync alembic upgrade head
docker compose exec -T api uv run --no-sync tourism-seed

docker compose exec -T postgres psql -U tourism -d tourism -tAc "SELECT version_num FROM alembic_version; SELECT count(*) FROM pg_tables WHERE schemaname='public';"
docker compose exec -T redis redis-cli ping
```

当前验收值：Alembic revision 为 `20260901_0007`；public schema 共 `77` 张表（`76` 张业务表加 `alembic_version`）；Redis 返回 `PONG`。

## 4. 服务端质量门与真实 API 冒烟

宿主机需已安装 `uv`。在 `server` 目录运行静态检查和完整测试：

```powershell
Set-Location server
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

当前验收值：Ruff 退出码为 `0`；pytest 为 `146 passed`，总覆盖率 `72.63%`。

容器保持运行，在同一目录对真实 API 执行 45 秒单请求超时的冒烟测试：

```powershell
uv run tourism-smoke --base-url http://127.0.0.1:8000 --timeout 45
Set-Location ..
```

当前验收输出为 `Real-network smoke passed (49 checks).`。其中 3 项验证游客注册、
注册后会话和重复用户名冲突；这一步访问实际的 API、
PostgreSQL 和 Redis。

## 5. OpenHarmony 客户端

详尽质量说明见[客户端质量指南](client-quality.md)。先进入 `client`，把 DevEco Studio 根目录设为本机安装位置；后续命令均从该变量派生路径：

```powershell
Set-Location client
$devecoRoot = '<DevEco Studio 安装目录>'
if (-not (Test-Path -LiteralPath $devecoRoot -PathType Container)) {
    throw 'DevEco Studio 安装目录不存在'
}
$env:DEVECO_SDK_HOME = Join-Path $devecoRoot 'sdk'

& (Join-Path $devecoRoot 'tools\ohpm\bin\ohpm.bat') install

& (Join-Path $devecoRoot 'tools\node\node.exe') `
    (Join-Path $devecoRoot 'plugins\codelinter\run\index.js') `
    -c code-linter.json5 `
    -p default `
    -e error `
    (Join-Path $devecoRoot 'sdk\default\openharmony') `
    .

& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') `
    test --mode module -p product=default -p module=entry@default -p buildMode=debug --no-daemon

& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') `
    assembleHap --mode module -p product=default -p module=entry@default -p buildMode=debug --no-daemon

& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') `
    assembleHap --mode module -p product=default -p module=entry@ohosTest -p buildMode=debug --no-daemon

& (Join-Path $devecoRoot 'sdk\default\openharmony\toolchains\hdc.exe') list targets
```

构建产物为：

- `entry/build/default/outputs/default/entry-default-unsigned.hap`
- `entry/build/default/outputs/ohosTest/entry-ohosTest-unsigned.hap`

CLI 产物是 unsigned HAP。真机运行前须在 DevEco Studio 配置本地签名、连接可见目标，再由 IDE 分别运行 `entry` 和 `entry@ohosTest`；不要直接用 `hdc install` 安装 unsigned HAP。

客户端 API 基址按运行位置设置：

| 运行位置 | API 基址 |
| --- | --- |
| Windows 本机、宿主机测试 | `http://127.0.0.1:8000/api/v1` |
| DevEco 模拟器 | `http://10.0.2.2:8000/api/v1` |
| 局域网真机 | `http://<开发机局域网 IPv4>:8000/api/v1` |

真机与开发机应位于可互通网络；确认 Compose 已发布 `8000` 端口，并仅在可信网络为 Windows 防火墙放行入站 TCP `8000`。不要把 `127.0.0.1` 配给真机。
应用内可通过“我的 → 开发环境 API 地址”修改当前进程使用的基址；该值必须包含
`/api/v1`。预期 CLI 结果为 Code Linter `No defects found`、Hypium 41 passed，以及
`entry@default`、含 4 个用例的 `entry@ohosTest` 两个 HAP 构建成功。测试包在模拟器上的
执行由测试人员在 DevEco Studio 完成本地签名后进行。

## 6. 演示账号

四个账号的统一密码为 `Tourism123!`：

| 账号 | 角色 |
| --- | --- |
| `tourist_demo` | tourist |
| `merchant_demo` | merchant |
| `support_demo` | support |
| `admin_demo` | admin |

## 7. 人工业务闭环

先在模拟器完成游客自助注册：

1. 以游客态打开受保护操作，在登录弹层切换到“注册”；
2. 填写显示名称、唯一的小写用户名、同时含英文字母和数字的 8 位以上密码，并确认密码；
3. 点击“注册并登录”，确认弹层关闭且新游客已自动登录；
4. 退出后用同一用户名再次注册，确认显示重复用户名提示；
5. 抽查空显示名称、非法用户名、弱密码及确认密码不一致的字段提示。

随后使用这个新账号或 `tourist_demo` 登录，依次抽查：

1. 门票报价、下单、演示支付、电子票 QR、退款和改签；
2. 导览、人流推送、个性行程、冲突检查和动态避堵；
3. 项目预约、虚拟排队、FastPass、餐饮与住宿预约；
4. 商城购物车、结算、积分兑换、内容分享；
5. 反馈/投诉、客服 WebSocket、同行协作和无障碍模式；
6. 离线旅行包、恢复同步、SOS Demo、数字护照和绿色任务。

再使用 `support_demo` 或 `admin_demo` 抽查客服处理、SOS 状态和管理员权限边界。

## 8. 可选 Locust 快速负载检查

完整口径见[性能测试说明](../performance/README.md)。先在仓库根目录创建 10 个专用负载账号，再从 `server` 运行 30 秒无头测试：

```powershell
Set-Location '<tourism_services 仓库目录>'
$loadSecret = Read-Host '输入至少 12 位的负载测试密码' -AsSecureString
$loadPassword = [Net.NetworkCredential]::new('', $loadSecret).Password
if ($loadPassword.Length -lt 12) {
    throw '负载测试密码至少需要 12 位'
}

docker compose exec -T -e "TOURISM_LOAD_USER_PASSWORD=$loadPassword" api `
    uv run --no-sync tourism-load-seed --count 10

Set-Location server
$env:TOURISM_LOAD_USER_PASSWORD = $loadPassword
$env:TOURISM_LOAD_USER_COUNT = '10'
$env:TOURISM_LOAD_USER_OFFSET = '0'
$prefix = Join-Path ([IO.Path]::GetTempPath()) ('tourism-locust-' + [Guid]::NewGuid().ToString('N'))

uv run locust -f load/locustfile.py `
    --host http://127.0.0.1:8000 `
    --headless --users 5 --spawn-rate 5 --run-time 30s --stop-timeout 5 `
    --csv $prefix --csv-full-history --only-summary

Import-Csv "${prefix}_stats.csv" | Where-Object Name -eq 'Aggregated'
if ((Import-Csv "${prefix}_failures.csv").Count -ne 0) {
    throw 'Locust failures found'
}
if ((Import-Csv "${prefix}_exceptions.csv").Count -ne 0) {
    throw 'Locust exceptions found'
}

$loadPassword = $null
$loadSecret = $null
Remove-Item Env:TOURISM_LOAD_USER_PASSWORD -ErrorAction SilentlyContinue
```

已接受的 Compose 基线为 5 users / 30 s、CSV 319 requests、0 failures、11.33 req/s、
aggregate p95 130 ms；它是开发机回归基线，不是生产容量或 10,000 在线声明。

## 9. 停止与下次启动

日常停止使用以下非破坏性命令；命名卷会保留，下次重新执行第 1、2 节即可继续使用现有数据：

```powershell
Set-Location '<tourism_services 仓库目录>'
docker compose down
```

> **危险：以下命令会删除 Compose 命名卷，清空本机 PostgreSQL/Redis 数据。仅在明确需要重置空库且已备份所需数据时执行。**

```powershell
docker compose down --volumes --remove-orphans
```
