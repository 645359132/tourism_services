# 客户端质量与真机验收

本页记录检查点 9 的 HarmonyOS 客户端自动化证据，以及仍需在已签名真机/模拟器上完成的人工验收。命令均从 `client/` 执行。

## 自动化证据

本机验证日期：2026-09-04（Asia/Shanghai）。

| 检查 | 结果 | 证据 |
|---|---|---|
| OHPM 依赖与锁文件可移植性 | 通过 | `ohpm install` 退出码 0；`oh-package-lock.json5` 只包含 `@ohos/hypium@1.0.25` 的公开 OHPM 地址、版本和完整性摘要，不含盘符、用户目录或本地 `file:` 依赖。 |
| Hypium 本地业务规则 | 通过 | Hvigor `test` 构建成功；44 个用例全部通过，Failure 0、Error 0，包含注册字段、重复用户名错误映射、历史英文行程的中文展示兼容、模拟器连接提示，以及路线节点顺序和出行模式展示。 |
| `ohosTest` 业务 smoke 编译 | 通过 | `entry@ohosTest` HAP 构建成功；4 个用例覆盖游客注册输入、购票状态流、离线/应急安全和 719/720vp 响应式边界。 |
| debug HAP | 通过 | `entry@default` HAP 构建成功；CLI 产物未签名，供编译验收使用。 |
| DevEco Code Linter | 支持的规则门禁通过 | 配置改为本机支持的 TypeScript 与 security recommended 规则；CLI 以 0 退出并输出 `No defects found`，引擎日志确认 ESLint 实际执行且 Errors/Warns/Suggestions 均为 0。附带的 `arkPerfCheck` 仍会在 6 个大型 ArkUI 文件上触发其内部 `getDeclaringMethod` 异常，因此不把该扩展的覆盖范围虚报为完整。 |
| 模拟器执行 | 待人工复验 | 测试包已经编译；在 DevEco Studio 对已启动模拟器完成本地签名后运行 4 个 `onDeviceBusinessSmoke` 用例并记录结果。 |

构建前为当前 PowerShell 进程提供 DevEco SDK 根目录：

```powershell
$devecoRoot = '<DevEco Studio 安装目录>'
$env:DEVECO_SDK_HOME = Join-Path $devecoRoot 'sdk'
```

复验命令：

```powershell
& (Join-Path $devecoRoot 'tools\node\node.exe') (Join-Path $devecoRoot 'plugins\codelinter\run\index.js') -c code-linter.json5 -p default -e error (Join-Path $devecoRoot 'sdk\default\openharmony') .
& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') test --mode module -p product=default -p module=entry@default -p buildMode=debug --no-daemon
& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') assembleHap --mode module -p product=default -p module=entry@ohosTest -p buildMode=debug --no-daemon
& (Join-Path $devecoRoot 'tools\hvigor\bin\hvigorw.bat') assembleHap --mode module -p product=default -p module=entry@default -p buildMode=debug --no-daemon
& (Join-Path $devecoRoot 'sdk\default\openharmony\toolchains\hdc.exe') list targets
```

Code Linter 的第一个位置参数必须是 OpenHarmony SDK，第二个才是项目目录；只传 `.`
会让其把项目目录误当成 SDK。另行启用 cross-device recommended 规则做诊断时，工具报告了
颜色资源、对比度与字号等建议，但同一 `arkPerfCheck` 版本仍在 6 个文件上发生内部异常。
当前以真实执行且零缺陷的 TypeScript/security gate、ArkTS 编译和下面的设备矩阵共同作为
验收证据；升级 DevEco/Code Linter 后应重跑 cross-device 扩展并清理其有效建议。

模拟器或真机执行还要求本地签名配置。证书、私钥和设备标识只保存在开发机/DevEco Studio 中，不写入仓库；连接目标并完成自动签名后，在 DevEco Studio 运行 `entry@ohosTest`，预期 `onDeviceBusinessSmoke` 的 4 个用例全部通过。

## 模拟器首个手工流程：游客注册

1. 以游客态打开任一受保护操作，在登录弹层点击“注册”。
2. 输入 1..100 字符的显示名称、3..64 位的小写字母/数字/下划线用户名，以及 8..128 位且同时含英文字母和数字的密码；再次输入相同密码。
3. 点击“注册并登录”。接受结果是弹层关闭、页面显示新游客身份，可直接访问受保护功能，不需要再次登录。
4. 退出后再次注册同一用户名。接受结果是“该用户名已被使用，请更换后重试”，既有账号仍可正常登录。
5. 分别尝试空显示名称、大写或连字符用户名、纯字母/纯数字密码、两次密码不一致。接受结果是客户端给出对应字段提示且保持可修改；服务端校验响应不回显提交的凭据原值。

## phone/tablet 人工矩阵

所有行当前均等待测试人员在 DevEco Studio 执行并记录。表中的 vp 是验收视口，不代表某一台特定设备。

| 形态 | 视口/方向 | 显示模式 | 预期导航 | 核心验收 | 状态 |
|---|---|---|---|---|---|
| phone | 360 × 800，竖屏 | 浅色、标准字号 | 底部五栏 | 注册/自动登录与重复用户名提示；首页进入门票、排队、餐住；返回后状态正确 | 待执行 |
| phone | 360 × 800，竖屏 | 深色、大字、高对比 | 底部五栏增高 | 文本不截断；按钮可点击；页面可滚动；焦点与对比度清晰 | 待执行 |
| phone | 800 × 360，横屏 | 浅色、标准字号 | 720vp 起切换侧栏 | 719/720vp 附近无导航重复、闪烁或内容遮挡 | 待执行 |
| tablet | 800 × 1280，竖屏 | 浅色、标准字号 | 左侧五栏 | 首页、导览、行程、商城、我的切换；门票/预约子页占满内容区 | 待执行 |
| tablet | 1280 × 800，横屏 | 深色、大字、高对比 | 左侧五栏增宽 | 双栏空间利用；弹层居中；长列表、空态、错误态和离线态无溢出 | 待执行 |

每一行都应完成以下业务抽查：

1. 完成上述游客注册流程；随后验证登录成功后的身份和返回路径正确，退出后不残留敏感信息。
2. 门票报价、库存变化、支付状态、二维码入口和退改入口布局稳定。
3. 导览中切换起终点并规划路线，确认结果卡就地出现、节点按顺序高亮；人流、行程及排队 WebSocket 断开、重连和旧序列丢弃有明确反馈。
4. 商城结算、积分兑换、客服、同行协作和无障碍偏好可达且输入错误可恢复。
5. 离线包冷启动、待同步 outbox、SOS Demo、数字护照和绿色积分明确标注状态，不把演示能力呈现为真实救援派单。

完成矩阵时记录设备型号、HarmonyOS/API 版本、实际 vp、主题/字号、结果和截图编号；任一失败应附最短复现步骤。
