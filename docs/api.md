# API 与实时通信契约

本文档描述当前服务端已经注册的 107 个 REST operations 与 3 条 WebSocket 接口。REST 路径已逐项与
`server/app/api/routes/` 中的装饰器及应用生成的 OpenAPI `paths` 核对；请求和响应
字段的最终机器可读定义以运行中服务的 OpenAPI 为准。WebSocket 不属于 OpenAPI，完整
握手和事件约定见本文后半部分。

## 地址与 OpenAPI

| 用途 | 本地默认地址 |
|---|---|
| 服务根地址 | `http://127.0.0.1:8000` |
| 版本化 REST 基址 | `http://127.0.0.1:8000/api/v1` |
| WebSocket 基址 | `ws://127.0.0.1:8000/api/v1` |
| 健康检查 | `GET http://127.0.0.1:8000/health` |
| Swagger UI | `http://127.0.0.1:8000/docs` |
| ReDoc | `http://127.0.0.1:8000/redoc` |
| OpenAPI JSON | `http://127.0.0.1:8000/openapi.json` |

Compose 默认也把 API 暴露到宿主机 `8000` 端口；设置 `API_PORT` 后应替换上表端口。
HTTPS 部署必须相应使用 `https://` 和 `wss://`。客户端配置值应包含
`/api/v1`；`/health`、`/docs`、`/redoc` 和 `/openapi.json` 位于服务根路径。
这些 OpenAPI 入口按当前应用配置公开；生成的 schema 只包含 REST，不包含 WebSocket。

## 认证、JWT 与角色

受保护的 REST 请求使用：

```http
Authorization: Bearer <access-token>
```

`POST /api/v1/auth/register` 是公开游客注册入口，成功返回 201。用户名先去除首尾空白并
转为小写，再按 `[a-z0-9_]`、3..64 字符校验；显示名称去除首尾空白后为 1..100 字符；
密码为 8..128 字符，且至少包含一个 ASCII 字母和一个 ASCII 数字。调用方不能提交角色，
服务端只分配 `tourist`，使用 Argon2id 保存密码散列，并在创建成功后直接返回 token pair
和用户资料供客户端自动登录。用户名冲突返回 `409 USERNAME_TAKEN`；基础 `tourist` 角色
不可用时返回 `503 REGISTRATION_UNAVAILABLE`。请求校验错误不会把提交的用户名或密码
原值放入响应。

`POST /api/v1/auth/login` 接收用户名和密码，并返回
`access_token`、`refresh_token`、`token_type="bearer"`、以秒计的
`expires_in` 及当前用户。默认 access token 有效期为 15 分钟，refresh token 为 7 天。
`POST /api/v1/auth/refresh` 在响应中同时轮换 access token 和 refresh token；已消费
refresh token 的重放会撤销整条 token family，并返回
`401 REFRESH_TOKEN_REUSED`。`POST /api/v1/auth/logout` 接收 refresh token，
幂等撤销其 family 并返回 204。

JWT 只接受配置的 `HS256` 算法，并校验 `iss`、`aud`、`exp` 以及
`sub`、`jti`、`type`、`iat`、`exp`、`iss`、`aud` 必需声明。access
token 携带 `roles`；refresh token 还携带 session/family 标识。每个受保护请求仍会
从数据库重新加载用户，停用或不存在的用户会被拒绝，权限以持久化角色为准。

角色为 `tourist`、`merchant`、`support`、`admin`。下表中的角色表示最低
业务角色；`admin` 是所有 `require_roles` 检查的显式超级用户。`any active user`
表示任一已认证且启用的账号。当前 `merchant` 没有独立的业务写接口，但可读取自己的
用户资料。演示账号仅在 `ENABLE_DEMO_ACCOUNTS=true` 时由种子创建，production
配置明确禁止启用它们。

## 通用响应约定

### 错误信封与请求关联

进入 FastAPI 路由与异常处理层的框架校验错误、HTTP 错误和业务错误使用同一 JSON 形状：

```json
{
  "error": {
    "code": "STABLE_MACHINE_CODE",
    "message": "Human-readable message",
    "details": {}
  },
  "request_id": "correlation-id"
}
```

`details` 没有内容时省略。调用方可传入由 1 至 64 个字母、数字、点、下划线、冒号或
连字符组成的 `X-Request-ID`；无效或缺失时服务端生成新值。响应同时返回
`X-Request-ID`。认证失败为 401 并带 `WWW-Authenticate: Bearer`，权限不足为
`403 FORBIDDEN`，请求模型错误为 `422 VALIDATION_ERROR`。注册、登录、刷新等凭据请求的
校验信封会移除原始输入值。分布式协调忙或不可用
分别返回 `409 OPERATION_IN_PROGRESS` 或 `503 COORDINATION_UNAVAILABLE`，并带
`Retry-After: 1`。

基础设施中间件可在路由前拒绝请求，因此不进入上述 JSON handler。例如非法 `Host`
由 `TrustedHostMiddleware` 返回 `400 text/plain`（`Invalid host header`）；不合法的
CORS 预检也使用 Starlette 的文本响应。这些响应仍经过外层 request-ID 与安全响应头
中间件。客户端应优先按 JSON 信封解析，并为此类 pre-router 文本错误保留通用映射。

### 分页

以下列表使用页码分页：ticket orders、reservations、shop orders、point ledger、
feedback、support conversations、support messages 和 emergency SOS。查询参数均为
`page`（默认 1，最小 1）与 `page_size`（默认 50，范围 1..100），响应形状为：

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 0
}
```

离线同步使用独立的 opaque cursor 协议，不使用页码，见“离线包与同步语义”。

### 幂等

本服务没有 `Idempotency-Key` HTTP header 约定；幂等标识位于 JSON 请求体，通常为
`idempotency_key`（8..128 字符）。同一用户在同一业务作用域内用相同 key 和相同
请求重试会取得既有结果；相同 key 搭配不同有效载荷返回
`409 IDEMPOTENCY_CONFLICT`。

使用 `idempotency_key` 的操作包括：

- ticket order 创建、支付、退款、改签；
- experience reservation 创建、确认、取消；
- queue 加入、离开、FastPass；
- stay、dining、bundle 预约；
- shop checkout、shop order 支付、积分兑换、内容分享；
- support REST/WS 消息发送；
- SOS 提交、护照打卡、绿色任务完成。

闸机核验以请求体 `request_id` 实现同类重放保护。离线 push 则以
`client_mutation_id` 配合请求摘要实现幂等；相同 ID、相同内容返回 `REPLAYED`，
相同 ID、不同内容返回 409。

### 限流

默认窗口为 60 秒。限流只选择 `/api/v1` 下的请求，`OPTIONS` 与普通 GET 不进入
这些桶：

| 类别 | 默认上限 | 匹配请求 |
|---|---:|---|
| auth | 30 | `POST /api/v1/auth/register`、`POST /api/v1/auth/login`、`POST /api/v1/auth/refresh` |
| ws-ticket | 30 | 路径以 `/ws-tickets` 结尾的 POST |
| mutation | 120 | 其余 POST、PUT、PATCH、DELETE |

认证类请求始终按网络身份/IP 计数；其他受限请求在 access token 有效时以
`user:<sub>` 计数，否则以直接对端 IP 计数。只有直接对端位于
`TRUSTED_PROXY_NETWORKS` 时才采用 `X-Forwarded-For`。受限响应带
`X-RateLimit-Limit`、`X-RateLimit-Remaining`、`X-RateLimit-Reset`（距窗口
重置的秒数）；超限还带
`Retry-After` 并返回 `429 RATE_LIMITED`。默认单进程模式使用进程内协调；启用
Redis rate-limit 后跨 worker 共享。请求期 Redis 调用失败并允许回退时，响应会标记
`X-Coordination-Mode: local-degraded`；`REDIS_REQUIRED=true` 时协调失败返回 503。

### 演示 Provider 标记

`GET /api/v1/meta/capabilities` 是客户端展示能力边界的稳定入口；其中
`providers` 当前全部显式声明 `is_demo=true`：

| 能力 | mode | 含义 |
|---|---|---|
| `ai` | `rules` | 确定性本地规则，没有外部 AI |
| `crowd` | `simulated` | 合成人流数据 |
| `face_gate` | `demo_no_biometrics` | 不调用摄像头、不处理生物信息且不放行的身份匹配演示 |
| `gate` | `demo` | 没有物理闸机 |
| `map` | `schematic` | 本地示意图，没有实时地图商 |
| `merchant` | `demo` | 本地演示商户数据 |
| `notification` | `in_process` | 进程内通知，没有外部投递 |
| `payment` | `demo` | 不发生真实资金流转 |

具体响应还使用 `provider`、`source`、`mode` 和 `is_demo` 明示边界，例如
`simulated` 人流/排队、`schematic` 路线、`demo_payment`、
`demo_support_bot`、`local_offline_pack`、`curated_demo`、
`demo_sos`、`demo_checkin`、`demo_green_verifier` 和
`local_collaboration`。客户端必须呈现这些标记，不能把演示结果解释为真实支付、
救援派单、人工客服、传感器人流或第三方核验。

## REST 端点目录

表中的 `Bearer` 表示必须携带 access token。除特别注明外，资源读取也会实施所有权
或可见性检查。

### 系统、认证、用户与元数据

| 方法 | 路径 | 认证 / 角色 | 用途 |
|---|---|---|---|
| GET | `/health` | Public | 服务存活与必需 Redis pub/sub 健康状态 |
| POST | `/api/v1/auth/register` | Public | 创建普通游客账号并签发 token pair，返回 201 |
| POST | `/api/v1/auth/login` | Public | 用户名/密码登录并签发 token pair |
| POST | `/api/v1/auth/refresh` | Public；body refresh token | 轮换 refresh token 并签发新 token pair |
| POST | `/api/v1/auth/logout` | Public；body refresh token | 撤销 refresh-token family，返回 204 |
| GET | `/api/v1/users/me` | Bearer / any active user | 当前用户与角色 |
| PATCH | `/api/v1/users/me/preferences` | Bearer / tourist | 更新语言、兴趣、无障碍及通知偏好 |
| GET | `/api/v1/meta/capabilities` | Public | 角色能力与演示 Provider 元数据 |

### 门票

| 方法 | 路径 | 认证 / 角色 | 用途 |
|---|---|---|---|
| GET | `/api/v1/ticketing/types` | Public | 票种目录 |
| GET | `/api/v1/ticketing/slots` | Public | 按 `visit_date` 和可选 `ticket_type_id` 查询场次库存与动态价格 |
| POST | `/api/v1/ticketing/quotes` | Public | 为场次和数量生成限时报价；响应回传权威票种、日期、起止时间及签名 `quote_token` |
| POST | `/api/v1/ticketing/orders` | Bearer / tourist | 携带 `quote_token` 幂等占用库存并按签名价格创建待支付订单 |
| GET | `/api/v1/ticketing/orders` | Bearer / tourist | 分页列出自己的门票订单 |
| GET | `/api/v1/ticketing/orders/{order_id}` | Bearer / tourist | 获取自己的门票订单 |
| POST | `/api/v1/ticketing/orders/{order_id}/pay` | Bearer / tourist | 幂等演示支付并签发电子票 |
| POST | `/api/v1/ticketing/orders/{order_id}/cancel` | Bearer / tourist | 取消待支付订单并原子释放预占库存；终态重放不重复释放 |
| POST | `/api/v1/ticketing/orders/{order_id}/refund` | Bearer / tourist | 按截止规则幂等退款 |
| POST | `/api/v1/ticketing/orders/{order_id}/reschedule` | Bearer / tourist | 幂等改签到目标场次 |
| GET | `/api/v1/ticketing/tickets/{ticket_id}/qr` | Bearer / tourist | 获取自己的短期 QR JWT；响应禁止缓存 |
| POST | `/api/v1/ticketing/tickets/{ticket_id}/face-demo/verify` | Bearer / tourist | 对自己的有效电子票执行无生物信息的人脸接入演示；不核销、不放行 |
| POST | `/api/v1/ticketing/gate/validate` | Bearer / admin | 以 `request_id` 幂等执行演示闸机核验 |

`TicketOrderResponse` 对所有订单统一返回 `refund_cutoff_hours`、
`refund_deadline_at`（UTC）和 `refundable`。客户端应以这些服务端字段展示退票规则与
按钮状态，不能把默认的 2 小时写死；运维覆盖 `TICKET_REFUND_CUTOFF_HOURS` 后契约会同步变化。
退款事务将电子票置为 `VOID`、订单置为 `REFUNDED`，并在同一事务把
`TicketInventory.sold` 减去订单数量，因此 `remaining = capacity - reserved - sold`
会精确恢复；幂等重放不会重复增加余票。

`quote_token` 将场次、数量、单价和有效期写入服务端签名 JWT。首次下单必须携带该
令牌；在有效期内即使动态占用率变化，也按签名单价创建订单，库存不足仍会拒绝。
令牌过期、被篡改或与请求不一致分别返回 `QUOTE_EXPIRED`、`INVALID_QUOTE`、
`QUOTE_MISMATCH`。幂等摘要只使用场次与数量，因此首次响应丢失后重新报价并沿用
原幂等键，会返回已经创建的订单而不会重复占库存。

普通门票时段是可入园窗口，不是独占游客时间的活动。购买或改签门票不会与园内演出、
项目或餐饮预约互斥，也不会在行程中生成占满整个窗口的 `COMMITMENT`。真正定时占座的
票务能力应在未来以明确业务类型接入。

人脸演示请求只接受 `sample=OWNER|OTHER` 与 `consent=true`。响应始终携带
`provider=demo_face_gate`、`is_demo=true`、`biometric_processed=false`、
`admission_granted=false` 和免责声明。`DEMO_MATCHED` 只说明演示适配器命中了
“本人”样本，不代表真实人脸识别、活体检测、闸机放行或电子票核销；真正核销仍只发生
在管理员授权的 `/ticketing/gate/validate` 事务中。

### 导览、设施与行程

| 方法 | 路径 | 认证 / 角色 | 用途 |
|---|---|---|---|
| GET | `/api/v1/guide/attractions` | Public | 景点列表及当前人流摘要 |
| GET | `/api/v1/guide/attractions/{attraction_id}` | Public | 景点详情 |
| GET | `/api/v1/guide/attractions/{attraction_id}/narrations` | Public | 文化讲解列表；含文字、时长、`audio_url` 与 `provider_mode` 音频扩展字段 |
| GET | `/api/v1/guide/map` | Public | 本地示意地图节点和边 |
| GET | `/api/v1/guide/crowd` | Public | 最新模拟人流快照 |
| POST | `/api/v1/guide/routes/plan` | Public | 按无障碍/婴儿车约束计算示意路线 |
| GET | `/api/v1/guide/facilities` | Public | 按 `kind`、`accessible_only` 查询设施 |
| POST | `/api/v1/itineraries/generate` | Bearer / tourist | 用确定性规则生成个性化行程 |
| GET | `/api/v1/itineraries/{itinerary_id}` | Bearer / tourist | 获取自己的行程 |
| POST | `/api/v1/itineraries/{itinerary_id}/conflicts/check` | Bearer / tourist | 检查时间及步行缓冲冲突 |
| POST | `/api/v1/itineraries/{itinerary_id}/replan` | Bearer / tourist | 按期望 revision 重排自己的行程 |

### 项目、预约、排队、餐住与评价

| 方法 | 路径 | 认证 / 角色 | 用途 |
|---|---|---|---|
| GET | `/api/v1/experiences` | Public | 游乐项目/演出目录 |
| GET | `/api/v1/experiences/{experience_id}/sessions` | Public | 按 `date` 查询项目场次和库存 |
| POST | `/api/v1/reservations` | Bearer / tourist | 幂等创建项目预约 hold；只拒绝真实时间重叠，首尾相接可预约 |
| GET | `/api/v1/reservations` | Bearer / tourist | 分页列出自己的全部预约 |
| POST | `/api/v1/reservations/{reservation_id}/confirm` | Bearer / tourist | 幂等确认自己的预约 |
| POST | `/api/v1/reservations/{reservation_id}/cancel` | Bearer / tourist | 幂等取消自己的预约 |
| POST | `/api/v1/queues` | Bearer / tourist | 幂等加入虚拟队列，可关联行程 |
| GET | `/api/v1/queues/{queue_id}` | Bearer / tourist | 获取自己的排队状态 |
| DELETE | `/api/v1/queues/{queue_id}` | Bearer / tourist；body | 用请求体中的幂等 key 离队 |
| POST | `/api/v1/queues/{queue_id}/fast-pass` | Bearer / tourist | 幂等购买演示 FastPass |
| POST | `/api/v1/ws-tickets` | Bearer / tourist | 为自己的 active queue 签发一次性 WS ticket |
| GET | `/api/v1/hospitality/venues` | Public | 酒店、民宿、餐厅目录 |
| GET | `/api/v1/hospitality/offers` | Public | 全部或指定 `venue_id` 的房/餐/组合 offer |
| GET | `/api/v1/hospitality/availability` | Public | 按 `resource_id`、`date_from`、`date_to` 查询库存 |
| POST | `/api/v1/hospitality/bookings/stay` | Bearer / tourist | 幂等创建住宿预约 |
| POST | `/api/v1/hospitality/bookings/dining` | Bearer / tourist | 幂等创建餐饮预约 |
| POST | `/api/v1/hospitality/bookings/bundle` | Bearer / tourist | 幂等创建组合预约 |
| POST | `/api/v1/reviews` | Bearer / tourist | 为符合条件的预约提交评价 |

### 商城、积分与分享

| 方法 | 路径 | 认证 / 角色 | 用途 |
|---|---|---|---|
| GET | `/api/v1/shop/categories` | Public | 商品分类 |
| GET | `/api/v1/shop/products` | Public | 全部或指定 `category_id` 的商品 |
| GET | `/api/v1/shop/campaigns` | Public | 当前演示营销活动 |
| GET | `/api/v1/shop/cart` | Bearer / tourist | 获取或初始化自己的购物车 |
| POST | `/api/v1/shop/cart/items` | Bearer / tourist | 添加购物车商品 |
| PUT | `/api/v1/shop/cart/items/{item_id}` | Bearer / tourist | 设置购物车项数量 |
| PATCH | `/api/v1/shop/cart/items/{item_id}` | Bearer / tourist | 设置购物车项数量，与 PUT 同处理器 |
| DELETE | `/api/v1/shop/cart/items/{item_id}` | Bearer / tourist | 删除购物车项 |
| POST | `/api/v1/shop/cart/checkout` | Bearer / tourist | 幂等结算并创建待支付商城订单 |
| GET | `/api/v1/shop/orders` | Bearer / tourist | 分页列出自己的商城订单 |
| GET | `/api/v1/shop/orders/{order_id}` | Bearer / tourist | 获取自己的商城订单 |
| POST | `/api/v1/shop/orders/{order_id}/pay` | Bearer / tourist | 幂等演示支付商城订单并记积分 |
| GET | `/api/v1/points/account` | Bearer / tourist | 获取或初始化积分账户 |
| GET | `/api/v1/points/ledger` | Bearer / tourist | 分页读取不可变积分流水 |
| GET | `/api/v1/points/rewards` | Public | 演示兑换品目录 |
| POST | `/api/v1/points/redeem` | Bearer / tourist | 幂等兑换积分奖励 |
| POST | `/api/v1/shares` | Bearer / tourist | 演示验证内容分享并幂等奖励积分 |

商城商品的 `stock` 是服务端权威可售余量。加入购物车不预占库存；结算使用条件更新
原子扣减库存并创建 `PENDING_PAYMENT` 订单，`ShopOrderResponse.expires_at`（UTC）
表示库存保留截止。支付不会再次扣减；待支付订单过期后只回补一次。

### 反馈、同行协作与客服

| 方法 | 路径 | 认证 / 角色 | 用途 |
|---|---|---|---|
| POST | `/api/v1/feedback` | Bearer / tourist | 提交反馈或投诉 |
| GET | `/api/v1/feedback` | Bearer / tourist or support | 分页列出本人反馈；support 可看工作队列 |
| GET | `/api/v1/feedback/{feedback_id}` | Bearer / tourist or support | 获取可见反馈 |
| POST | `/api/v1/feedback/{feedback_id}/assign` | Bearer / support | 指派反馈 |
| POST | `/api/v1/feedback/{feedback_id}/resolve` | Bearer / support | 记录解决结果 |
| POST | `/api/v1/feedback/{feedback_id}/follow-up` | Bearer / tourist | 提交回访评分/评论 |
| POST | `/api/v1/feedback/{feedback_id}/rating` | Bearer / tourist | 回访评分兼容别名 |
| GET | `/api/v1/faqs` | Public | 全部或指定 `category` 的 FAQ |
| POST | `/api/v1/groups/create` | Bearer / tourist | 创建同行组和限时邀请码 |
| POST | `/api/v1/groups/join` | Bearer / tourist | 使用邀请码入组 |
| GET | `/api/v1/groups/{group_id}` | Bearer / tourist | 获取成员可见的同行组 |
| PUT | `/api/v1/groups/{group_id}/privacy` | Bearer / tourist | 设置行程、位置、状态共享开关 |
| PATCH | `/api/v1/groups/{group_id}/privacy` | Bearer / tourist | 设置共享开关，与 PUT 同处理器 |
| PUT | `/api/v1/groups/{group_id}/itinerary` | Bearer / tourist | 按期望 revision 关联/解除行程 |
| PATCH | `/api/v1/groups/{group_id}/itinerary` | Bearer / tourist | 关联/解除行程，与 PUT 同处理器 |
| POST | `/api/v1/groups/{group_id}/meeting-points` | Bearer / tourist | 创建集合点 |
| POST | `/api/v1/groups/{group_id}/member-status` | Bearer / tourist | 更新自己的状态及可选位置 |
| POST | `/api/v1/groups/{group_id}/lost-alerts` | Bearer / tourist | 创建走失提醒 |
| POST | `/api/v1/support/conversations` | Bearer / tourist | 创建演示客服会话 |
| GET | `/api/v1/support/conversations` | Bearer / tourist or support | 分页列出可见会话 |
| GET | `/api/v1/support/conversations/{conversation_id}/messages` | Bearer / tourist or support | 分页读取持久化消息 |
| POST | `/api/v1/support/conversations/{conversation_id}/messages` | Bearer / tourist or support | 幂等发送消息并广播事件 |
| POST | `/api/v1/support/ws-tickets` | Bearer / tourist or support | 为可见会话签发一次性 WS ticket |

### 离线、应急、护照与绿色积分

| 方法 | 路径 | 认证 / 角色 | 用途 |
|---|---|---|---|
| GET | `/api/v1/offline/packs/latest` | Bearer / tourist | 最新离线包元数据 |
| GET | `/api/v1/offline/packs/{pack_id}/manifest` | Bearer / tourist | 带 ETag 的离线资产 manifest |
| GET | `/api/v1/offline/packs/{pack_id}/assets/{asset_id}` | Bearer / tourist | 获取 manifest 中的 JSON 资产内容 |
| GET | `/api/v1/offline/sync/status` | Bearer / tourist | 读取指定 `device_id` 的设备与服务端 cursor |
| POST | `/api/v1/offline/sync/push` | Bearer / tourist | 幂等上传 1..50 个离线 mutation |
| GET | `/api/v1/offline/sync/pull` | Bearer / tourist | 按 opaque cursor 顺序拉取 mutation |
| GET | `/api/v1/emergency/resources` | Bearer / tourist or support | 演示应急电话、地点和指引 |
| GET | `/api/v1/emergency/bulletins` | Bearer / tourist or support | 当前演示应急公告 |
| POST | `/api/v1/emergency/sos` | Bearer / tourist | 幂等持久化 SOS；仅演示派单 |
| GET | `/api/v1/emergency/sos` | Bearer / tourist or support | 分页列出可见 SOS |
| GET | `/api/v1/emergency/sos/{sos_id}` | Bearer / tourist or support | 获取可见 SOS |
| PUT | `/api/v1/emergency/sos/{sos_id}/acknowledge` | Bearer / support | 将 SOS 转为 acknowledged |
| PUT | `/api/v1/emergency/sos/{sos_id}/resolve` | Bearer / support | 将 SOS 转为 resolved |
| GET | `/api/v1/passport` | Bearer / tourist | 数字护照印章和积分摘要 |
| POST | `/api/v1/passport/check-ins` | Bearer / tourist | 演示核验并幂等领取印章 |
| GET | `/api/v1/green/tasks` | Bearer / tourist | 绿色任务及个人完成状态 |
| POST | `/api/v1/green/tasks/{task_id}/complete` | Bearer / tourist | 演示核验并幂等完成任务、奖励积分 |

## WebSocket 契约

WebSocket 事件统一使用 `id`、`type`、`occurred_at`、`data` 信封。queue 与
support ticket 都是短期 bearer credential：不要放入日志、分析事件或可分享链接。
默认 `WS_TICKET_TTL_SECONDS=60`，ticket 原子消费且只能使用一次；错误 channel/
conversation 的消费尝试也会烧毁 ticket。启用 Redis ticket backend 后可跨 worker
消费，否则仅在签发它的进程内协调。

### 1. Crowd stream

- Ticket：无；这是公开流。
- URL：`ws://127.0.0.1:8000/api/v1/guide/ws/crowd`。
- 连接后立即收到一次快照，随后收到 publisher tick。
- 服务端事件固定为
  `{"id": "...", "type": "crowd.snapshot", "occurred_at": "...", "data": {...}}`。
  `data` 是 `CrowdResponse`：`items`、单调 `sequence`、`captured_at`、
  `source="simulated"`、`is_demo=true`。每个 item 含景点、人数、占用基点、
  拥挤等级、等待分钟和采集时间。
- 客户端只可发送 `{"type":"ping"}`；其他 JSON 关闭码 1008，非法 JSON 为 1003。
  发送阻塞/超时由服务端以 1013 关闭。重连后应以 `sequence` 丢弃旧快照。

### 2. Queue stream

1. 以 tourist access token 调用 `POST /api/v1/ws-tickets`：

   ```json
   {"channel_type": "queue", "channel_id": "<queue-uuid>"}
   ```

   队列必须属于当前用户且状态为 `WAITING`、`CALLED` 或 `SERVING`。响应是
   `{"ticket":"...","expires_at":"..."}`。

2. 立即连接
   `ws://127.0.0.1:8000/api/v1/ws/queues/{queue_id}?ticket=<url-encoded-ticket>`。

3. 初始帧及后续帧的 `type` 为 `queue.updated`、
   `nearby.recommended` 或 `itinerary.replan_available`。`data` 包含完整
   `queue`、`source="simulated"`、`is_demo=true`、可选 `recommendation`、
   `itinerary_id` 和 `itinerary_revision`。queue 自身的 `sequence` 用于顺序和
   去旧。客户端只可发送 `{"type":"ping"}`。

关闭码：ticket 无效/过期/已用/作用域错误为 4401，资源不可见为 4404，队列已不 active
为 4409，非法 JSON 为 1003，非 ping JSON 为 1008，协调不可用或发送超时为 1013。
队列离开 active 状态的最后一帧后正常关闭为 1000。

### 3. Support stream

1. 以 tourist 或 support access token 调用
   `POST /api/v1/support/ws-tickets`：

   ```json
   {"conversation_id": "<conversation-uuid>"}
   ```

   服务端先验证会话可见性，再返回 `ticket` 与 `expires_at`。

2. 立即连接
   `ws://127.0.0.1:8000/api/v1/ws/support/{conversation_id}?ticket=<url-encoded-ticket>`。

3. 初始事件为 `support.updated`，后续消息事件为 `support.message`。输出信封的
   `data` 包含 `conversation`、可空 `message`、`source`（
   `demo_support_bot` 或 `human`）和 `is_demo`。message 含
   `sender_type`、`sender_name`、`content`、`sequence`、`provider` 等字段。

客户端可发送 `{"type":"ping"}`，或：

```json
{
  "type": "message.send",
  "data": {
    "content": "message",
    "idempotency_key": "at-least-8-characters"
  }
}
```

有效消息会持久化，并向会话内连接广播 tourist/support 消息及可能的演示 bot 回复。
无效/过期/已用 ticket 为 4401，会话或用户不可见为 4404，协调不可用/发送超时为
1013；无效入站事件、模型校验失败或业务拒绝以 1008 关闭。

## 离线包与同步语义

### ETag 和内容完整性

`GET /api/v1/offline/packs/latest` 返回带引号的 pack `etag` 和
`manifest_url`。manifest 响应带：

- `ETag: "<pack-etag>"`
- `Cache-Control: private, max-age=60`
- `Vary: Authorization`

再次请求时可发送 `If-None-Match`；强标签或带 `W/` 前缀的同值标签均返回 304，
并保留上述缓存 header。manifest 的每个资产提供 `download_url`、
`content_hash`、`size_bytes`、`encoding="json"`。客户端下载资产后应以 SHA-256
核对 `content_hash`，只有完整 manifest 成功后才原子替换本地 pack。

### Opaque cursor

同步 cursor 是以服务端 secret 做 HMAC 的 URL-safe opaque token，并绑定
`user_id`、`device_id`、协议 version/epoch。客户端不得解析、修改或跨用户/设备
复用。省略 cursor 表示从 0 开始；无效、篡改或作用域错误返回
`409 SYNC_CURSOR_INVALID`，超前于服务端状态返回 `409 SYNC_CURSOR_AHEAD`，调用方
应执行 full resync。

- `GET /api/v1/offline/sync/status?device_id=...` 返回设备已确认 `cursor`、
  `last_client_version` 与用户 mutation head `server_cursor`。
- `POST /api/v1/offline/sync/push` 接收同一设备的可空 `base_cursor` 与 1..50 个
  mutation。批内 `client_version` 必须唯一且严格递增，
  `client_mutation_id` 必须唯一；已提交的同内容 ID 返回 `REPLAYED`，新内容返回
  `APPLIED`。旧于设备状态的版本返回 `SYNC_CLIENT_VERSION_STALE`，并发修改设备
  状态返回 `SYNC_CONFLICT`。
- `GET /api/v1/offline/sync/pull?device_id=...&cursor=...&limit=...` 以全用户
  `server_cursor` 升序返回 cursor 之后的项目。`limit` 默认 50、范围 1..100；
  响应回显起始 `cursor`，给出 `next_cursor` 和 `has_more`。调用方应持续把
  `next_cursor` 用于下一页，直到 `has_more=false`，并仅在本页持久化成功后推进
  本地 checkpoint。

这些同步 token 与 JWT secret 共享签名材料；轮换该 secret 会使既有 token 失效，客户端
应按 `SYNC_CURSOR_INVALID` 路径执行 full resync。
