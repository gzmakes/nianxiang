# R13 iOS 安全设备连接：实现与验收边界

本目录是 SwiftUI / Foundation 源码，可交给 iOS 开发继续验证。没有安装 Xcode，没有 iOS SDK 构建、模拟器、签名、IPA、iPhone 安装或真机 UI / Keychain / TLS 验收；不能称各端已经齐平或手机已开箱即用。

## 实现

- `App/DeviceConnectionView.swift`：设置中显式输入 HTTPS 地址 / SecureField 令牌，实际引用共享 title / scope / verify / invalid 文案。没有欢迎弹窗、自动剪贴板读取、账号授权或模型密钥输入。离页 / 非 active 清输入并取消验证 attempt，晚响应不激活。
- `Sources/EchoCore/DeviceConnection.swift`：严格 `echo_pair_` + 43 base64url 令牌；验证 `personal_core`、禁止本机动作、有效 UTC 时间和未撤销状态。非秘密 profile 保存 origin / instance / canonical / device / 本机随机 generation；不编码 bearer。失效后内存授权对象清空 bearer 并拒绝继续使用。
- `Sources/EchoCore/APIClient.swift`：默认 ephemeral URLSession，保持系统证书验证；每个 task 均拒绝重定向。只有初次 `GET /api/paired-device` 可以未绑定实例，其余远程请求需已验证 profile 的 Bearer + `X-Echo-Service-Instance`。未连接时不匿名读取 / 重试。旧 client 退役后，晚到成功也不能交给 UI。远程动作 / CLI 请求在客户端阻止，服务端 allowlist 是最终权限边界。
- `App/DeviceCredentialStore.swift`：仅本应用固定 service + 精确 generation account 的 generic password，`WhenUnlockedThisDeviceOnly`、不同步、Data Protection Keychain。初始化不查询；没有枚举、扫描或读取其他钥匙串。实际方法仅由本人 Connect / Restore / Forget 或精确身份 401 调用。本轮仅编译此适配器，所有运行用 fake vault。
- `App/EchoStore.swift`：先验证设备 / canonical 和 GET 对话，再安全保存 / readback 后激活。失败保留当前连接；401 清精确凭据和私密 RAM，隔离草稿 / 未决快照留盘。实例 409 只停用并保留原凭据供原实例恢复；403 / 5xx / 锁定不清凭据。已知旧身份的晚 401 只能清它自己的本机项；旧 409 不删项。generation / immutable client 约束成功、错误和 finally，不能以相同 canonical ID 混用两个设备许可。
- 旧连接在 UI 可见；明确恢复必须同实例 / 设备 / canonical 再验证，使用原 generation，不自动重发 pending。明确移除只删本机所选令牌，**不删除隔离草稿、不撤销服务器许可、不取消已经发出的请求**。移除后需电脑核对 / 新建许可；没有凭 metadata 自动恢复。
- 聊天、跟进、心情 ledger、草稿与话题按 origin / service instance / device / generation 隔离。旧无配对身份的 pending 保留原字段 / 原 body，不赋予新身份。模型提议偏好仍为本应用设置，不声称所有偏好按设备分离。
- 手机只展示可用的个人核心操作；隐藏电脑 CLI / 日历 / 提醒事项 / 动作入口。本人选择的文本先在本地预览再确认上传，可收回已接入来源。现有记忆 CAS、心情 ledger、被动 once / daily 跟进、F5 和显式朗读继续保留；本轮无模型调用、原生自动主动问或系统通知。

## 本轮证据

- `VALIDATION-ROUND13.log`：工程生成、plist / pbxproj、Swift parse 与 Foundation **70/70**。原 R12 的 64 保留，新增 6 组 token / 命名空间 / 绑定 / 错误 / 回执契约检查；XcodeTests 仅同步源码与语法，不称 XCTest 已运行。
- `HOST-ROUND13.log` 与最终 UI 调整后的 `HOST-TYPECHECK-ROUND13.log`：整个 App / Core 在 **macOS** 类型检查；实际 EchoStore **30**、MoodStore **13**、MoodLedgerStore **17**、SpeechController **9** 组，使用 URLProtocol / 假 driver。原隔离测试中旧匿名 HTTPS 夹具改用 loopback 地址；产品 HTTPS 策略没有放宽。
- `HOST-DEVICE-CONNECTION-ROUND13.log`：实际 EchoStore + fake vault + 合成 URLProtocol **18** 组。含验证失败保留旧连接、凭据保存 / readback 失败、optional metadata 401 不误激活、锁定保留、401 / 409 / 403 区分、同 canonical 不同 generation、历史恢复 / 精确移除、后台取消、旧429 / finally 不改新 busy / pending、旧 unknown 原 ID / payload 只 GET 核对。
- `HOST-PAIRED-HTTPS-ROUND13.log`：实际 macOS URLSession → 最终 R13 runner，随机 loopback 端口 / 临时 DB / 临时独立 CA / fake vault，**10 流程组**。产品默认 trust 首先拒绝未安装的合成证书；仅测试注入的 session 使用该临时 CA 为唯一锚点，并调用 `SecTrustEvaluateWithError` + SSL hostname 策略。没有改系统 trust、安装证书或更改产品信任路径。真实 302 / 307 / 308 全拒绝，目标 TLS listener **0 请求 / 0 凭据**。另验设备 DTO、同 canonical 激活、安全 catalogue、记忆 CAS、心情 ledger 同 ID 重试、文件确认 / 撤回、被动 F5 / 跟进、403 保留、owner 收回后 401 清理。无 DeepSeek / chat POST / CLI / 硬件 / 联系 claim。
- 对应后端版本 API **1.6.0**，最终 hash 见根工作区的 `work/round13-backend-seal.json`；本端 manifest 保存相关 hash。R9 / R10 / R11 / R12 旧 HTTP 和 WAV 日志保留为历史，不是本轮重新运行的手机证据。

重跑入口：`sh validate.sh`、`sh validate_host.sh`；真实 HTTPS 用已有 FastAPI / uvicorn Python 环境执行 `HostChecks/run_round13_paired_smoke.py`，仅创建 / 删除自己拥有的临时数据。不要把测试专用 CA delegate 放进产品 App，或改成接受所有证书。

## 仍需首轮设备验收

1. iOS 17+ SDK 构建、UIKit 分支、签名 / bundle / Keychain entitlement，实体设备锁屏 / 解锁与 Data Protection 行为；本轮编译通过不能证明这些。
2. 电脑本人明确启动配对 TLS 入口，配置设备可达且被系统信任的证书；手机实际输入 / 安全键盘 / 后台清输入 / 无重定向 / 验证成功后恢复。没有自动开端口、局域网发现、隧道或证书安装。
3. 真机断网 / 杀进程 / 冷启动、旧 profile 恢复、vault 锁定 / 容量故障、撤销及旧 401 晚到；核对原 unknown 只 GET、不换身份重发、不丢原文。
4. 同一后端真实已配置模型聊天、消息分段 / 取消、文件 picker 与文本预览确认 / 撤回、记忆 CAS / 手动心情 / daily 详情、键盘 / 动态字体 / VoiceOver。R13 没有再次调用模型，不能用本轮 HTTPS 合成数据代替对话体验验收。
5. 系统朗读的真实声音、耳机 / 中断 / 后台停止、源撤回 / 私密 RAM 清理后停止；R12 macOS WAV 仅证明宿主缓冲合成。没有新增语音输入或麦克风权限。

## 存储和交付

令牌在 Keychain 适配器；非秘密连接 metadata / 普通草稿 / 话题 / pending 仍用应用 UserDefaults，按身份隔离，**不是独立加密保险箱或云同步**。明确退出 / 401 清 RAM 不会抹掉用户仍需核对的本机快照。移除令牌与电脑撤销是两个操作；目前不提供手机端删除整份隔离草稿的入口，避免无提示丢失 unknown 原文。

手机设备许可可以读写同一后端，但无推送 / 自动实时多设备同步或多用户云账号。服务默认不启动 TLS gateway；生产 HTTPS 证书、网络可达、运维和应用分发另验。

打包排除 `.build/`、DerivedData、xcuserdata、DB、合成证书 / 私钥、凭据 / 模型配置。保存本端源码、工程、脚本、验收日志和 manifest；不要将临时测试 session 的证书逻辑用于产品。
