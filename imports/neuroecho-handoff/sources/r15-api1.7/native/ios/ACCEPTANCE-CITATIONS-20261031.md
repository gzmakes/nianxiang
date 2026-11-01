# iOS：飞书文档引用兼容 · 2026-10-31

本次为当前 R15 的最小源码增量。没有安装 Xcode / iOS SDK，没有运行 iOS 模拟器、签名、IPA、真机、真实 Keychain 或实际系统外链打开；macOS 类型检查和 Foundation 不能替代设备验收。

## 修改范围

- `Sources/EchoCore/MessageCitations.swift` 增加文档 / 旧记忆两类 DTO。缺失、null、非数组引用兼容旧消息；数组内未知 kind、原始值、不完整字段、坏链接逐项略过，不令整条消息或对话读取失败。只有缺少 kind 的合法旧记忆结构保留为 memory，不把新文档或未知类型当记忆；没有新增记忆引用 UI。
- `Sources/EchoCore/Models.swift` 的 EchoMessage 保留已有字段语义，新增默认空 citations。原会话读取、变更快照和聊天回执均通过同一解码路径。
- `App/MessageCitationViews.swift` 与 RootViews 消息接线只给完整、已有可见正文的 assistant 回复增加“查阅 · 文档标题”。引用正文 text 不新增展示、不写入记忆、不发起读取。提示“文档权限与飞书连接在电脑端管理”。未新增原生账户授权、账户级检索开关或 owner CLI 接口，配对设备边界保留。
- 外链仅允许纯 ASCII 合法域名标签的 feishu.cn / larksuite.com 及子域、HTTPS、默认端口或显式443、/docx|docs|wiki/合法标识路径。拒绝 userinfo、非官方域、编码主机/路径、点路径、原始空白/控制/反斜杠、编码控制或反斜杠；普通 query / fragment 保留。只在本人点选后交给系统 openURL，不经 EchoAPI、不附设备 Bearer，也不表示用户具备文档访问权限。
- 点击重新核对前台、原 scope（含凭据代次）/会话、当前话题可见消息、原文字/可见段和精确引用；消息移除、内容变化或身份更换后不打开旧入口，晚到的失败回调也不能覆盖新消息状态。
- `generate_project.py` 重新生成 Xcode 工程源引用，只增两份新 Swift 文件。历史轮次说明和封板 manifest 保留为当时证据，没有冒充本次源的最终验收。

## 本次实际验证

本次检查结果和覆盖范围如下。

1. Foundation runner **87/87**：原81组加6组引用检查，涵盖旧消息、混合/坏引用、memory与document分型、官方URL、完整可见回复、跨身份/删改/重复消息点击拒绝，以及实际 EchoAPI + URLProtocol 的 GET会话 / GET变更快照 / POST聊天回执解码。均为合成数据，无网络/账号/模型请求。
2. 当前全部 App/Core 的 **macOS SwiftUI 类型检查通过，退出0**；旧 onChange 弃用警告仍在，未因本次范围去重构。该检查没有编译 UIKit / iOS 平台分支。
3. App Info.plist / project.pbxproj 的 plutil 检查通过；git diff --check通过。新增6组 XCTest 对应源码已同步，但未运行 XCTest 或 iOS 构建。

可复跑（在 native/ios 目录，scratch 目录可选源树之外）：

```sh
swift run --scratch-path /tmp/echo-citations-core-checks EchoCoreChecks
swiftc -typecheck App/*.swift Sources/EchoCore/*.swift
plutil -lint App/Info.plist Echo.xcodeproj/project.pbxproj
```

首轮设备验收仍需：真实 iOS 工程构建后查看完整回复的标题，点开有权限与无权限的飞书文档，确认未完成回复不显示引用，并验证切连接/话题后旧入口失效。系统接收外链不证明文档读取成功；手机端仍不管理电脑 CLI 授权。

## 增量：前台跨页面分段续读 · 2026-10-31

`EchoStore` 现在独立于所选标签监控当前 assistant 的分段呈现；`ChatStreamView` 的旧循环已移除，没有两个续读 loop。停留“今天／连接”页，从既有 changes 更新读到后台洞察第一段后，也会继续 GET `/api/conversation`，直到该条完整或已被移除。旧服务没有 changes 能力时，已有的 pending 回复仍可续读；此处没有新增 intro POST、账户读取或请求重放。

每个 Store 同时最多一个续读 GET；回执核对原消息 ID、scope（含设备凭据代次）、连接 generation、对话 revision 和前台生命周期代次。离开前台取消监控；后台、身份变化、较新快照、正在提交、unknown 请求或编辑／来源确认 lease 下，不采用旧回执或开始不安全读取。普通输入草稿不被续读清空。保留原有只显示已交付段落、完整后才显示文档引用／允许朗读的规则。

本增量实际结果见 `CITATIONS-DELIVERY-VALIDATION-20261031.log`：

1. 新 `HostChecks/DeliveryLifecycleChecks.swift` **8/8**：完全不创建 ChatStreamView，以真实 EchoStore + URLProtocol 重现 changes 发现 pending 后的跨页续读；验证单飞、后台再前台旧回执、同 canonical 换设备／代次、同消息新 revision、编辑／unknown 保护、普通草稿保留、服务端删除、无 changes 能力的旧服务。全部合成响应，未访问服务、模型或账号。
2. 相关旧 Store **30/30**、更新／可用性 Store **27/27** 回归；Foundation **87/87** 再次通过。
3. 全部 App/Core 的 macOS SwiftUI 类型检查退出0；现有 onChange 弃用警告保留。没有运行 UIKit / iOS 分支、系统真实前后台事件或设备界面。上述跨页面结论是 Store 行为和源码接线检查，不能表述为 iPhone GUI 已验收。

新增检查已接入 `validate_host.sh`。只跑本次续读回归可执行：

```sh
swiftc -whole-module-optimization -parse-as-library Sources/EchoCore/*.swift App/DeviceCredentialStore.swift App/EchoStore.swift HostChecks/DeliveryLifecycleChecks.swift -o /tmp/echo-delivery-checks
/tmp/echo-delivery-checks
```

本轮仅修续读；资料确认请求仍未携带 `start_intro`，原生尚未接入“自己确认资料后启动洞察”的选项或 job 状态。电脑启动的后台消息由既有 changes + delivery 读取，手机不新增 CLI／账户授权。历史 `CITATIONS-VALIDATION-20261031.log` 及 R8–R15 日志／封板表未修改。
