# 轻量启动（Python 3.12 + DevEco Studio）

本文适用于只有 Python 3.12 与 DevEco Studio 的本地开发机。服务端使用 SQLite 和进程内协调能力，不需要 Docker、PostgreSQL 或 Redis；客户端使用 DevEco Studio 自带的 Node.js、OHPM、Hvigor、SDK 与模拟器。

这种模式适合功能演示、模拟器手工测试和单人开发，不用于多进程部署、并发压测或生产环境。需要验证 PostgreSQL、Redis、双 worker 和完整运行拓扑时，请改用[全栈日常启动指南](full-stack-startup.md)。

## 1. 运行结构与数据边界

- API：单个 FastAPI 进程，监听 `0.0.0.0:8000`。
- 数据库：`server/data/tourism.db`，由 SQLite 持久化。
- Redis：关闭；限流、锁和实时消息协调使用单进程本地实现。
- 模拟器 API 地址：`http://10.0.2.2:8000/api/v1`。
- 外部支付、地图、AI、闸机和救援仍是项目中明确标注的 Demo Provider。

SQLite 与 Compose 使用的 PostgreSQL 是两套独立数据库。之前在 PostgreSQL 中注册的账号、订单和预约不会自动出现在 SQLite 中；切换到轻量模式后可使用演示账号，或重新注册一个 SQLite 本地账号。

## 2. 首次准备

在 Windows PowerShell 5.1 中进入服务端目录，并确认 `python` 指向 3.12：

```powershell
Set-Location '<tourism_services 仓库目录>\server'

python --version
if (-not ((python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))") -eq '3.12')) {
    throw '轻量启动要求 Python 3.12'
}
```

首次安装 `uv`。`--user` 不需要管理员权限；后续通过绝对路径调用，因此不依赖 PATH 是否已经刷新：

```powershell
python -m pip install --user uv

$uvUserScripts = python -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user'))"
$uvExe = Join-Path $uvUserScripts 'uv.exe'
if (-not (Test-Path -LiteralPath $uvExe -PathType Leaf)) {
    $uvExe = (Get-Command uv -ErrorAction Stop).Source
}

& $uvExe --version
```

首次同步只安装运行依赖，不安装 pytest、Locust、Ruff 等开发依赖：

```powershell
$uvCache = (New-Item -ItemType Directory -Force ..\.uv-cache).FullName
$env:UV_CACHE_DIR = $uvCache

& $uvExe sync --frozen --no-dev --python 3.12
New-Item -ItemType Directory -Force data | Out-Null
```

首次下载 Python 依赖需要网络；完成后日常启动可以直接复用 `server/.venv`。

## 3. 初始化 SQLite 并启动 API

在同一个 PowerShell 中设置轻量运行变量：

```powershell
$env:APP_ENV = 'development'
$env:DATABASE_URL = 'sqlite+aiosqlite:///./data/tourism.db'
$env:REDIS_COORDINATION_ENABLED = 'false'
$env:REDIS_REQUIRED = 'false'
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:TRUSTED_HOSTS = 'localhost,127.0.0.1,10.0.2.2'
```

执行迁移、幂等 seed 并启动 API：

```powershell
& $uvExe run --no-sync alembic upgrade head
& $uvExe run --no-sync tourism-seed
& $uvExe run --no-sync tourism-api
```

`tourism-seed` 可以重复执行，不会重复创建目录数据或演示账号。`tourism-api` 启动后应保持当前窗口运行；按 `Ctrl+C` 可以停止服务。

轻量开发模式会使用项目内置的稳定开发密钥，便于重启后继续调试。该默认值只允许用于本机开发，不能用于生产部署。

## 4. 验证服务端

另开一个 PowerShell：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

预期返回 `status = ok`。也可在浏览器打开：

- 健康检查：<http://127.0.0.1:8000/health>
- OpenAPI：<http://127.0.0.1:8000/docs>

## 5. 在 DevEco Studio 运行模拟器客户端

1. 使用 DevEco Studio 打开 `<tourism_services 仓库目录>\client`。
2. 等待工程同步完成。项目所需 Node.js、OHPM、Hvigor 和 HarmonyOS SDK 均使用 DevEco Studio 自带版本。
3. 启动 phone 或 tablet 模拟器。
4. 选择普通 `entry` 模块并点击运行；不要把 `entry@ohosTest` 当成应用启动入口。
5. 客户端开发构建默认连接 `http://10.0.2.2:8000/api/v1`，无需再填写 `127.0.0.1`。

如果 IDE 没有自动完成 OHPM 同步，可在 `client/` 目录使用 DevEco 自带工具执行一次：

```powershell
$devecoRoot = '<DevEco Studio 安装目录>'
$env:DEVECO_SDK_HOME = Join-Path $devecoRoot 'sdk'

& (Join-Path $devecoRoot 'tools\ohpm\bin\ohpm.bat') install
```

内置演示游客账号：

- 用户名：`tourist_demo`
- 密码：`Tourism123!`

也可以从登录面板注册新游客账号；新账号会保存在 `server/data/tourism.db`。

## 6. 后续日常启动

依赖已经同步且代码依赖没有变化时，只需在新的 PowerShell 中重新设置路径和运行变量：

```powershell
Set-Location '<tourism_services 仓库目录>\server'

$uvUserScripts = python -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user'))"
$uvExe = Join-Path $uvUserScripts 'uv.exe'
if (-not (Test-Path -LiteralPath $uvExe -PathType Leaf)) {
    $uvExe = (Get-Command uv -ErrorAction Stop).Source
}

$uvCache = (New-Item -ItemType Directory -Force ..\.uv-cache).FullName
$env:UV_CACHE_DIR = $uvCache
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

迁移和 seed 都可安全重复执行。拉取了新的 `pyproject.toml` 或 `uv.lock` 后，先重新执行：

```powershell
& $uvExe sync --frozen --no-dev --python 3.12
```

## 7. 与现有 Compose 环境切换

如果本机此前已经启动 Compose，容器 API 会占用 `8000` 端口。切换到轻量模式前，在仓库根目录停止容器：

```powershell
Set-Location '<tourism_services 仓库目录>'
docker compose stop
```

`docker compose stop` 不删除 PostgreSQL/Redis 数据卷。不要为了切换模式执行带 `-v` 的删除命令。

## 8. 常见问题

- **端口 8000 已占用**：停止已有 Compose API 或其他本地服务，再运行 `tourism-api`。
- **`uv.exe` 找不到**：重新执行第 2 节的安装与 `$uvExe` 定位命令，不必修改系统 PATH。
- **模拟器无法访问 API**：确认服务端窗口仍在运行、健康检查成功，且客户端地址为 `http://10.0.2.2:8000/api/v1`。
- **Windows 首次提示防火墙授权**：只在可信的专用网络允许 Python 监听 TCP `8000`，不要向公共网络开放开发服务。
- **返回 `Invalid host header`**：确认 `TRUSTED_HOSTS` 包含 `10.0.2.2`，然后重启 Python API。
- **原账号无法登录**：先确认账号创建于 SQLite 还是 PostgreSQL；两种启动模式的数据不会自动互通。
- **代码更新后出现迁移或依赖错误**：依次重新执行 `uv sync --frozen --no-dev --python 3.12`、`alembic upgrade head` 和 `tourism-seed`。

轻量模式仍可手工测试注册、登录、导览、行程、门票、预约、排队、商城、客服、离线包、护照和积分等主要流程；Redis 多 worker 协调、PostgreSQL 方言与容量基线必须在完整模式下验证。
