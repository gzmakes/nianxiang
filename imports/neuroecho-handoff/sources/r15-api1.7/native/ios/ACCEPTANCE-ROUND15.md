# R15 iOS：三处可用性修复

这是 SwiftUI / Foundation 源码交付。没有安装 Xcode，没有 iOS SDK / UIKit、模拟器、签名、IPA 或手机验收。宿主类型检查、URLProtocol 和假 Vault 不能替代真实设备。

## 当前路径

1. `App/ChangeRefreshViews.swift` 的首页和编辑页使用相同状态选择。断网优先于残留 pending；初次能力清单失败显示“尚未核对”，不会显示“不支持”。编辑页内可点“检查更新”，不撤销编辑租约、不强制替换内容；关闭编辑页后才允许原协调器安全读取。`Sources/EchoCore/ConversationChanges.swift` 的纯规则校验这些状态优先级。
2. `App/EchoStore.swift` 的 `rereadCapabilities()` 只 GET 能力元数据，按原 immutable client / generation / scope / canonical / attempt 核对后提交。失败保留此前已核对的能力；新身份不接受旧设备晚到成功或失败。本人通过首页、设置或编辑页“检查更新”重新读取；旧服务不发 changes，仍保留显式快照读取，编辑期间不绕开保护。能力未知时不把它当成旧服务。检查过程中离开前台，不继续开始后续快照读取。
3. `App/DeviceConnectionView.swift` 每份本应用已保存 profile 新增“只读查看这份连接的本机草稿”，含凭据失效或已明确移除的旧身份。`Sources/EchoCore/LocalDraftArchive.swift` 只读取应用 UserDefaults 中匹配该身份的普通聊天草稿、原发送文字副本、跟进文字与按日心情草稿；校验 origin / canonical / 日期，损坏或身份不符的记录保留原数据并显示无法读取数量。返回模型刻意没有原 request ID、operation JSON、令牌或 API。
4. `App/LocalDraftArchiveView.swift` 显示来源标签、完整文字与未决状态说明，提供明确点按复制；不填入当前输入框、不重建请求、不查询服务、不读取钥匙串、不恢复身份或联系许可。复制不证明服务端取消或撤回；未决操作可能已处理。未找到文字也不声称服务器没有记录。

没有更改共享文案/API 合同、服务端、R14 冻结源或其他端；原聊天/心情 unknown、来源撤回、记忆 CAS、身份隔离和只读更新协议保留。未新增欢迎弹窗、账号授权、模型调用或硬件功能。

## 验证与边界

- `VALIDATION-ROUND15.log`：Foundation **81/81**，在 R14 78 项上增加状态优先级、只读归档不暴露重放身份/不改存储、心情日期/身份过滤三项。
- `HOST-ROUND15.log`：完整 App/Core 的 macOS 类型检查；原 EchoStore **30**、MoodStore **13**、MoodLedgerStore **17**、SpeechController **9**、设备连接 **18** 组；更新与可用性 Store **27** 组。新九组覆盖能力503→本人恢复、lease保留、offline优先、上次能力保留、旧服务编辑保护、离开前台中断后续读取、同canonical旧设备晚回执隔离、旧身份草稿0网络/0vault/0写/0迁移、未知profile拒绝。
- `HOST-CHANGES-ROUND15.log` 是同次最终宿主日志中上述27组的独立摘录。所有 HTTP 均是临时 URLProtocol 合成响应；Vault 为假实现，UserDefaults 为独立合成 suite，结束时清理。没有本轮新增真实 HTTPS、DeepSeek、外部CLI、账号或设备调用。R14 的 HTTPS 日志只保留为历史证据。
- `TYPECHECK-ROUND15.log` 摘录同次最终宿主类型检查；现有 `onChange` 旧签名的弃用警告保留，未据此称 iOS SDK 编译通过。Xcode 工程已生成并包含两个新增 Swift 文件；不表示生成 IPA。

复跑 `sh validate.sh`、`sh validate_host.sh`。普通草稿仍为本应用 UserDefaults，不是加密保险箱或跨设备离线合并。只读归档目前只展示文字副本，不恢复旧请求ID、不提供跨身份一键发送，也不替代服务端状态核对。

## 设备同学首轮

- 在真实 iOS SDK 编译 UIKit / 剪贴板分支；检查导航返回、sheet顶端提示、键盘、动态字号、VoiceOver 与小屏滚动。
- 首次能力请求断网→恢复网络→编辑页点检查；确认当前文字不变，关闭后更新，旧服务不误发 changes。
- 同canonical切设备时让旧能力响应晚到；确认不能影响新连接。退后台后不继续开始后续刷新。
- 本人明确失效/移除令牌后，从原profile查看并复制草稿；确认未读Keychain、未连接、未迁移/重发，未决说明清楚；再在真实设备验证复制反馈。
