# 八项创新实现详解

本文把 README 中的八项创新拆解为可演示、可读源码、可运行测试的实现说明。这里的“创新”指 MVP 内部已经落地的业务组合、状态保护和一致性机制，不代表已经接入外部人工智能、实时地图、传感器、闸机、支付、救援、语音或生物识别平台。

## 1. 个性化智能旅游管家

- **用户入口**：进入“行程”页，设置日期、开始时间、游览时长、兴趣、同行类型、体力和无障碍偏好后生成行程；结果卡展示总分及每个景点的兴趣、人流、步行、同行、体力和无障碍分项。
- **客户端状态保护**：提交前校验日期、时间、时长和兴趣；请求期间用 `operationBusy` 阻止重复提交；成功后同时更新当前行程 ID、版本和按用户隔离的本地缓存。历史缓存中的英文解释只在展示层转换为中文，不修改服务端数据。
- **服务端算法/事务不变量**：`RulesPlanner` 使用确定性加法评分：兴趣每项 `+30`，模拟人流按等级加减分，示意步行每分钟 `-2`，再叠加同行、体力和无障碍分项；无障碍不满足时使用不可被普通偏好抵消的硬性负分，并在候选阶段再次排除。候选按“总分降序、景点代码升序”稳定排序；生成记录、行程项和本次评分明细在同一数据库流程中持久化，相同输入和相同快照可复验。
- **演示/外部能力边界**：当前来源固定为 `rules`，没有调用大模型、在线推荐服务或用户画像平台。人流和步行成本分别来自模拟快照与本地示意图，因此结果是可解释的规则行程，不是对现实路况或个体安全的承诺。
- **关键源码与测试**：[规则评分器](../server/app/providers/planner.py)、[行程生成服务](../server/app/services/itinerary.py)、[行程页面](../client/entry/src/main/ets/pages/TripPage.ets)、[客户端行程规则](../client/entry/src/main/ets/utils/GuideRules.ets)；服务端重点看 `test_rules_planner_is_deterministic_and_owned`（[test_guide_itinerary.py](../server/tests/test_guide_itinerary.py)）和两个边界评分测试（[test_quality_edges.py](../server/tests/test_quality_edges.py)），客户端重点看 `validatesItineraryGenerationInput` 和 `localizesPersistedItineraryPresentationText`（[LocalUnit.test.ets](../client/entry/src/test/LocalUnit.test.ets)）。

## 2. 动态避堵与确定性路线

- **用户入口**：进入“导览”页查看景点拥挤度和模拟热力快照，选择两个不同节点后点击“规划路线”；页面就地显示节点顺序、路径、总距离和预计步行时间。行程页的重排也可按最新模拟人流调整未锁定景点。
- **客户端状态保护**：REST 快照与 WebSocket 消息共用单调 `sequence` 门禁，迟到或重复数据不会把页面回滚；切换起终点会递增路线请求版本并清空旧高亮，异步响应只有仍匹配当前版本时才可落屏。WebSocket 断开后仍可用 REST 刷新恢复状态。
- **服务端算法/事务不变量**：本地示意图先按通行条件裁剪边和节点，再以“步行分钟、距离米数”为字典序运行确定性最短路，并用节点 ID 稳定打破平局。人流发布器只为每个连接保留最新快照，协调层选出发布者后推进持久化序列；行程重排读取最新持久化快照，并记录采用的最大人流序列，便于追溯。
- **演示/外部能力边界**：路线 Provider 明确为 `schematic`，没有 GPS、道路网络、导航语音、实时封路或室内定位；人流为 `simulated`，没有接入摄像头、Wi-Fi、蓝牙、传感器或物理闸机。页面上的热力和耗时只用于功能演示。
- **关键源码与测试**：[示意最短路](../server/app/providers/map.py)、[模拟人流发布](../server/app/realtime/crowd.py)、[导览服务](../server/app/services/guide.py)、[导览页面](../client/entry/src/main/ets/pages/GuidePage.ets)、[人流 WebSocket 客户端](../client/entry/src/main/ets/network/CrowdSocket.ets)；服务端重点看示意路线、人流重排和公共 WebSocket 测试（[test_guide_itinerary.py](../server/tests/test_guide_itinerary.py)）以及 `test_crowd_pubsub_delivers_remote_once_and_ignores_echo`（[test_coordination_runtime.py](../server/tests/test_coordination_runtime.py)），客户端重点看 `classifiesCrowdAndRejectsStaleSequence`、`buildsVisiblePlannedRouteFeedback`（[LocalUnit.test.ets](../client/entry/src/test/LocalUnit.test.ets)）。

## 3. 多订单冲突优化器

- **用户入口**：在“行程”页修改同行人群和体力等级后重新生成，再点击“检查冲突”或“按最新人流重排”；冲突卡列出真实活动重叠、步行可行性或路线不可达等原因及建议动作。
- **客户端状态保护**：同行人群与体力控件直接绑定页面 `@State` 并显示当前选择。本地时间轴按半开区间判断相邻项；住宿只检查入住和退房各 30 分钟。重排请求携带当前 `revision`，响应仍须通过版本递增及真实锁定项不变的二次验收。
- **服务端算法/事务不变量**：交易层按 `[start, end)` 只拒绝真实活动重叠，首尾相接可以预约；步行缓冲留在行程可行性检查，不再误作下单硬限制。普通入园票是准入窗口，不投影为独占 `COMMITMENT`；旧版本留下的普通门票项会在响应中隐藏并在成功重排后清理。重排继续用期望版本和数据库条件更新原子递增版本。
- **演示/外部能力边界**：优化器只处理本系统数据库中的门票、预约、行程和本地示意图，不读取第三方酒店、航班、日历或真实交通订单。建议是规则计算结果，不保证现实世界一定可达或无冲突。
- **关键源码与测试**：[冲突检测与重排](../server/app/services/itinerary.py)、[预约冲突](../server/app/services/reservations.py)、[行程页面](../client/entry/src/main/ets/pages/TripPage.ets)、[客户端预约规则](../client/entry/src/main/ets/utils/BookingRules.ets)；服务端重点看准入票兼容及步行缓冲（[test_guide_itinerary.py](../server/tests/test_guide_itinerary.py)）和演出相邻/重叠回归（[test_experience_schedule_regressions.py](../server/tests/test_experience_schedule_regressions.py)，客户端对应 [ItineraryExperienceRegression.test.ets](../client/entry/src/test/ItineraryExperienceRegression.test.ets)）。

## 4. 排队与行程联动

- **用户入口**：从首页“智慧排队”或“项目排队与餐住”进入项目列表，预约场次、加入虚拟队列并查看等待时间；当等待变化产生行程建议时，由用户点击后才应用。FastPass 和叫号提醒也在该页展示。
- **客户端状态保护**：预约、入队、离队和 FastPass 请求用 `operationBusy` 防重复点击，并在可重试失败期间复用同一幂等键。队列事件必须同时命中当前队列 ID 和递增 `sequence`；行程建议在接收和点击应用两个时点都必须命中当前行程 ID 与版本，过期建议直接丢弃。终态队列会关闭实时连接。
- **服务端算法/事务不变量**：每个项目用原子计数器分配入队顺序，队列状态变更递增序列；推荐会排除高拥挤景点，并要求往返步行加游览时长能放入当前等待窗口。队列事件只携带建议生成时观察到的行程版本，不直接修改行程。最终预约仍获取用户级日程锁，并在同一事务内重新检查演出、项目、餐饮、住宿办理时段与库存；数据库条件更新和唯一约束裁决并发竞争。
- **演示/外部能力边界**：等待时间和推进事件来自模拟发布器，FastPass 不接真实支付，也不承诺现实优先入场；叫号仅为应用内状态，没有系统通知、短信、电话或物理队列/闸机连接。
- **关键源码与测试**：[队列服务](../server/app/services/queues.py)、[预约服务](../server/app/services/reservations.py)、[排队页面](../client/entry/src/main/ets/components/booking/ExperienceBookingView.ets)、[队列 WebSocket 客户端](../client/entry/src/main/ets/network/QueueSocket.ets)；服务端重点看预约生命周期、队列/FastPass 状态机和并发配额测试（[test_marketplace.py](../server/tests/test_marketplace.py)）。行程版本建议的直接客户端证据是 `parsesQueueEventAndRejectsStaleSequence`、`rejectsStaleQueueItinerarySuggestion`、`reusesQueueJoinIdempotencyKeyAfterNetworkFailure`（[LocalUnit.test.ets](../client/entry/src/test/LocalUnit.test.ets)）。

## 5. 多人同行协作

- **用户入口**：进入“我的 → 同行协作”，创建小队或使用邀请码加入，链接当前行程、设置集合点、更新成员状态和演示位置，并配置小队共享范围。
- **客户端状态保护**：未登录时只显示登录入口；所有写操作在进行中禁用重复提交。链接行程携带页面持有的小队版本，发生 `409` 时提示刷新；客户端只渲染服务端已经裁剪的成员状态、备注和坐标，不尝试在本地恢复被隐藏字段。位置输入还会校验经纬度范围。
- **服务端算法/事务不变量**：小队访问先验证有效成员身份；只有队主能修改小队隐私或链接行程，且只能链接自己的行程。行程链接使用期望 `revision` 做原子条件更新；隐私响应采用“小队总开关 ∩ 成员本人授权”的双层判定，任一层关闭即在服务端脱敏。关闭小队位置共享时清除历史坐标，避免以后重新开启泄露旧位置；邀请加入依靠成员唯一约束收敛并发重复加入。
- **演示/外部能力边界**：坐标由用户输入或固定“定位演示”按钮填入，没有调用 HarmonyOS 定位硬件；走散提醒只持久化为本地协作记录，没有短信、系统推送、后台定位或真实寻人服务。
- **关键源码与测试**：[同行协作服务](../server/app/services/groups.py)、[协作 API 路由](../server/app/api/routes/engagement.py)、[同行协作页面](../client/entry/src/main/ets/components/profile/GroupCollaborationView.ets)、[客户端输入规则](../client/entry/src/main/ets/utils/ServiceRules.ets)；服务端重点看 `test_group_invite_dual_privacy_meeting_and_lost_alert`（[test_commerce_engagement.py](../server/tests/test_commerce_engagement.py)），客户端重点看 `validatesFeedbackSupportAndGroupInputs`（[LocalUnit.test.ets](../client/entry/src/test/LocalUnit.test.ets)）。

## 6. 适老与无障碍

- **用户入口**：进入“我的 → 无障碍”调整大字体、高对比、语音辅助演示、轮椅和亲子推车偏好，并按类别查看便民设施。轮椅/推车偏好会参与设施筛选；进入行程页时，两者会合并为行程生成的无障碍需求。
- **客户端状态保护**：全局 `AccessibilityStore` 通过 HarmonyOS Preferences 同步恢复和持久化设置，向调用方返回副本，避免绕过 setter 修改内部状态。视觉设置经页面容器统一传播，大字缩放被限制在固定比例；设施列表保留加载、空、离线和错误状态。720vp 断点只切换布局，不重建业务状态。
- **服务端算法/事务不变量**：设施查询按类别以及 `accessible && wheelchair_ok` 条件过滤，并逐项返回轮椅、推车、开放状态、来源和演示标记。行程生成会排除不满足轮椅属性或节点通行条件的景点；本地路线算法在计算最短路之前过滤不满足轮椅/推车条件的边，避免先算路线再仅修改展示标签。
- **演示/外部能力边界**：语音辅助按钮当前只显示演示文案，没有调用系统 TTS 或在线音频；设施与开放状态来自本地数据，不代表实时设备可用性。路线仍是示意图，不是经过现场审计的无障碍导航，也不能替代人工确认。
- **关键源码与测试**：[无障碍设置仓库](../client/entry/src/main/ets/stores/AccessibilityStore.ets)、[无障碍页面](../client/entry/src/main/ets/components/profile/AccessibilityView.ets)、[响应式规则](../client/entry/src/main/ets/utils/ResponsiveRules.ets)、[设施服务](../server/app/services/engagement.py)、[示意路线 Provider](../server/app/providers/map.py)；服务端重点看 `test_feedback_rbac_state_machine_faq_and_accessible_facilities`（[test_commerce_engagement.py](../server/tests/test_commerce_engagement.py)）和示意路线硬过滤测试（[test_guide_itinerary.py](../server/tests/test_guide_itinerary.py)），客户端重点看 `filtersFacilitiesByPersistedRoutePreferences`、`appliesConstrainedGlobalLargeTextScale`（[LocalUnit.test.ets](../client/entry/src/test/LocalUnit.test.ets)）及 `selectsPhoneAndTabletLayoutsAtBoundary`（[BusinessSmoke.test.ets](../client/entry/src/ohosTest/ets/test/BusinessSmoke.test.ets)）。

## 7. 弱网离线与应急

- **用户入口**：从首页“应急助手”或“我的 → 离线/应急”进入，下载旅行包、查看缓存地图/行程/文字讲解/应急指引、创建低风险离线操作并执行 `Push → Pull`；SOS 位于同一页面，离线时保存为待手动重试草稿。
- **客户端状态保护**：缓存同时校验 schema 版本、所属用户、manifest 指纹和每项内容哈希，任一不匹配则整包拒绝；退出登录后的冷启动只恢复最小离线身份并强制只读。outbox 只允许便签、行程已读和应急公告已读，保留 mutation ID、递增客户端版本及失败分类；认证失败不会跨账号重放。SOS 在可重试失败期间复用幂等键，但不会进入通用自动重放队列。
- **服务端算法/事务不变量**：manifest 支持私有缓存头、ETag/304 和内容校验；同步游标以 HMAC 签名并绑定用户、设备和协议版本。push 在分配服务端游标前验证操作白名单、目标所有权和行程版本，同一 mutation ID 只有请求摘要相同时才能重放；每个用户的服务端游标单调递增，pull 按游标排序分页。SOS 以幂等键和请求摘要去重，状态机只允许规定迁移，并按游客所有权与客服角色控制可见和处理范围。
- **演示/外部能力边界**：离线讲解是文本资产，不是离线音频流；SOS Provider 固定返回演示接收状态、`real_dispatch=false` 和免责声明。离线草稿始终标记 `LOCAL_ONLY/PENDING_SYNC`，不会声称已联系急救、公安、景区救援、短信或电话服务，也不能替代当地应急流程。
- **关键源码与测试**：[离线同步服务](../server/app/services/offline.py)、[应急服务](../server/app/services/safety.py)、[演示应急 Provider](../server/app/providers/journey.py)、[离线/应急页面](../client/entry/src/main/ets/components/profile/OfflineEmergencyView.ets)、[客户端校验规则](../client/entry/src/main/ets/utils/JourneyRules.ets)；服务端重点看离线包、签名游标、目标验证和 SOS 生命周期测试（[test_journey.py](../server/tests/test_journey.py)），客户端重点看 `validatesUserSchemaAndChecksumScopedOfflineCache`、`keepsOutboxReplayDurableAndClassifiesFailures`、`validatesSosAndGreenEvidenceWithoutClaimingDispatch`（[LocalUnit.test.ets](../client/entry/src/test/LocalUnit.test.ets)）及 `keepsEmergencyAndOfflineFailuresSafe`（[BusinessSmoke.test.ets](../client/entry/src/ohosTest/ets/test/BusinessSmoke.test.ets)）。

## 8. 文化护照与绿色积分

- **用户入口**：进入“我的 → 护照/绿色”查看印章、输入演示打卡码、提交绿色任务凭证并观察积分余额；商城“积分”页读取同一个账户，可查看流水和兑换奖励。
- **客户端状态保护**：打卡和任务完成在可重试失败期间复用幂等键，成功或确定性失败后才结束该操作身份；两类操作都要求在线 Provider 验证，不进入通用离线 outbox。操作成功后一起刷新护照、任务列表和商城积分账户，避免页面展示不同快照的余额。
- **服务端算法/事务不变量**：同一幂等键必须匹配同一请求摘要，`用户 + 印章定义` 与 `用户 + 任务` 唯一约束阻止换键重复领奖。印章/任务完成记录与积分入账在同一事务提交，并发冲突后重新读取胜者结果。积分采用追加流水记录来源、增减额和 `balance_after`；兑换追加负数流水，不回写历史账目，来源类型与来源 ID 的唯一约束保证一次业务只记一次账。
- **演示/外部能力边界**：打卡码和绿色凭证由确定性 Demo Provider 校验，没有 NFC、二维码硬件、GPS 地理围栏、第三方平台回执或现实环保行为认证；积分仅是本项目数据库内余额，不可兑付现金。内容分享只验证演示格式，不代表社交平台已发布。
- **关键源码与测试**：[护照与绿色任务服务](../server/app/services/passport.py)、[积分服务](../server/app/services/points.py)、[演示验证 Provider](../server/app/providers/journey.py)、[护照/绿色页面](../client/entry/src/main/ets/components/profile/PassportGreenView.ets)、[商城积分页面](../client/entry/src/main/ets/pages/MallPage.ets)；服务端重点看护照/绿色任务的重复防护与并发测试（[test_journey.py](../server/tests/test_journey.py)）和 `test_points_redemption_rollback_and_share_award_once`（[test_commerce_engagement.py](../server/tests/test_commerce_engagement.py)），客户端重点看 `validatesSosAndGreenEvidenceWithoutClaimingDispatch`、`reusesCheckpointSevenIdempotencyKeysOnTransportFailure`（[LocalUnit.test.ets](../client/entry/src/test/LocalUnit.test.ets)）。

## 验证建议

服务端测试按上述链接中的测试函数运行；客户端规则测试位于 `LocalUnit.test.ets`，设备侧最小业务检查位于 `BusinessSmoke.test.ets`。完整手工演示路径、账号和预期结果参见[全栈启动与手工验收](testing/full-stack-startup.md)及[验收清单](testing/acceptance.md)。所有外部能力声明以[外部能力与 Mock 边界](mock-boundaries.md)为准。
