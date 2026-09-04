# 实施计划

计划采用 10 个可运行、可验证的纵向检查点。每个检查点只在对应验证通过后提交；命令会随本机工具链实测结果保持更新。

## 1. 仓库基线

- 交付物：根级忽略规则、换行规范、README、PLAN、PROGRESS；保留原始 `client/` 工程；初始化 `main`。
- 验证：`git status --short --branch`、`git check-ignore -v client/local.properties`、待跟踪文件敏感信息扫描。
- 提交：`chore: establish project baseline`

## 2. FastAPI 与持久化基础

- 交付物：uv 项目、分层应用工厂、配置/日志/CORS/统一错误、SQLAlchemy 2、Alembic、SQLite、可重复种子、`/health`、Docker Compose。
- 验证：`uv sync --frozen`、`uv run alembic upgrade head`（重复两次）、`uv run tourism-seed`（重复两次）、`uv run ruff check .`、`uv run pytest`、`docker compose config`。
- 提交：`feat(server): establish api and persistence foundation`

## 3. 认证权限与客户端应用壳

- 交付物：JWT 登录/刷新、密码散列、游客/商家/客服/管理员 RBAC；客户端网络层、Token 管理、登录与响应式五栏导航。
- 验证：认证/刷新/权限 API 测试、客户端网络错误映射单测，并在 `client/` 运行 Hvigor `test` 与 debug `assembleHap`。
- 提交：`feat(auth): connect role-aware client shell`

## 4. 门票交易纵向切片

- 交付物：票种、日期/分时库存、动态价格、幂等下单、电子票二维码、核验、退款/改签；客户端完整门票闭环。
- 验证：价格、原子库存并发、防重复下单、退改状态机与 API smoke；客户端状态转换/校验测试和 HAP 构建。
- 提交：`feat(ticketing): deliver booking and refund journey`

## 5. 导览、人流与行程智能

- 交付物：景点/文化讲解、地图 Provider、人流 WebSocket、路线/行程；创新点 1 个性管家、2 动态避堵、3 冲突优化器。
- 验证：路线评分/冲突/人流推送测试、REST 与 WebSocket smoke、客户端行程和弱网状态测试。
- 提交：`feat(guide): add crowd-aware itinerary intelligence`

## 6. 项目排队与餐住预约

- 交付物：设施/演出预约、虚拟排队/快速通行、酒店/民宿/房型、餐厅/套餐、组合预约；创新点 4 排队联动。
- 验证：预约冲突、排队状态推送、取消规则及餐住 API 测试；客户端流程测试和 HAP 构建。
- 提交：`feat(booking): connect queue dining and lodging`

## 7. 商城、客服、协作与无障碍

- 交付物：商品/购物车/商城订单/配送/活动/积分，反馈投诉/回访/客服 WebSocket；创新点 5 多人协作、6 适老无障碍。
- 验证：结算、积分不可变流水、权限、协作隐私、客服消息测试；无障碍布局与客户端业务单测。
- 提交：`feat(service): add commerce support and collaboration`

## 8. 离线应急与数字护照

- 交付物：关键订单/票/行程持久化、离线旅行包、恢复同步、SOS/疏散；创新点 7 弱网应急、8 文化护照/绿色积分；phone/tablet 全面适配。
- 验证：离线状态机/同步冲突/印章幂等测试、深浅色与宽屏构建检查、Hvigor 全量测试和 HAP 构建。
- 提交：`feat(experience): add offline safety and digital passport`

## 9. 综合质量与容量基线

- 交付物：核心覆盖率、真实 REST/WebSocket smoke、Locust 登录/查询/抢票/预约/商城/实时场景、安全与性能修复、1 万在线扩容说明。
- 验证：`uv run ruff check .`、`uv run pytest`、API/WebSocket smoke、Locust 本机 smoke/baseline、Hvigor test/build。
- 提交：`test: verify end-to-end mvp quality`

## 10. 文档与最终验收

- 交付物：完整 README，架构/API/数据模型/测试/压测/Mock 边界文档，创新点源码对照，最终 PROGRESS。
- 验证：从空数据库复跑全部服务端验证、客户端 CLI 验证、密钥/本机路径/占位/死链扫描、`git status` 与 `git log`。
- 提交：`docs: complete mvp acceptance guide`

## 客户端 CLI 基准

在 `client/` 中令 `$devecoRoot` 指向 DevEco Studio 安装目录，再使用实测工具：

- `& (Join-Path $devecoRoot 'tools\ohpm\bin\ohpm.bat') install`
- `& (Join-Path $devecoRoot 'tools\node\node.exe') (Join-Path $devecoRoot 'plugins\codelinter\run\index.js') -c code-linter.json5 -p default -e error (Join-Path $devecoRoot 'sdk\default\openharmony') .`
- `& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') tasks --no-daemon`
- `& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') test --mode module -p product=default -p module=entry@default -p buildMode=debug --no-daemon`
- `& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') assembleHap --mode module -p product=default -p module=entry@ohosTest -p buildMode=debug --no-daemon`
- `& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') assembleHap --mode module -p product=default -p module=entry@default -p buildMode=debug --no-daemon`
