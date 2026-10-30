# iOS R9 验收与交接 · 2026-10-30

交付范围是 SwiftUI 原生源码与 Foundation API / 状态管理，**不是 iOS 安装包完成**。用户明确暂不安装 Xcode；没有安装 SDK、模拟器、签名或真机验证。宿主 Mac 类型检查不等于 iOS 编译。

## 本轮完成

| 项目 | 关键语义 | 证据 |
|---|---|---|
| 完整飞书预览 | 必须有实际保留的完整有界文本，length / extracted_length / truncated 自洽；最多 12000 Unicode 字；展开原文后明确接入。标题不能代替内容 | Foundation 合成检查；无新增授权 / 真实飞书读取 |
| 原生周期跟进 | once / daily 创建，time_zone、quiet_start/end；daily 完成传 occurrence_at，暂停 / 恢复 / 整项取消；未来未知规则只读 | Foundation、实际 Store、真实宿主 HTTP |
| 完整草稿与 unknown | 普通表单按服务存储全部范围参数；pending 冻结原 payload；新字段在旧 pending 中保持缺失。已推进 daily 依 created_due_at 核对；已知终态才解锁 | Foundation + 实际 Store；HTTP 原请求重放仍同记录 |
| 逐项联系范围 | 默认不联系；明确窗口 / 话题，daily 明示每次窗口最多一次；过期不补问 | Foundation + Store + 真实 HTTP 元数据；原生不呈现自动轻问 |
| F5 统一边界 | 今天安静按所选当地下一午夜（含 DST）；无限暂停 / 指定时间 / 恢复。PUT confirmed:true + expected_revision；409 / unknown 不自动重试 | Foundation 合成 HTTP、实际 Store GET 时序保护、真实 URLSession CAS409 |
| 旧许可失效 | 改边界 / 拒绝 / 撤源令包括未来项的旧许可失效；待办仍在，恢复只允许以后重新约定，不复活旧许可 | 明确 UI 文案；真实 HTTP 验证未来项到点为 boundary_changed 仍可被动查看 |
| 被动列表 | 使用 review_available，和联系资格 available 分开 | Foundation / Store / 真实 HTTP |
| 共享文案 | 实际使用 EchoSharedReference.copy_companion_boundary_*、copy_followup_contact_*；已保存偏好不覆盖 | sync_shared.py --check、宿主全 App 类型检查 |
| R8 保护 | CAS、单一持续对话、unknown、来源与 epoch、分段 targeted-stop / message ID 回执、搜索 / 话题 / 聊天草稿不退回旧实现 | 旧场景在本轮整套回归中重跑 |

## 本轮实际执行

- `VALIDATION-round9.log`：工程生成、plist / pbxproj、全部 Swift 语法、Foundation Core 实际编译，**49 / 49 合成契约**通过。
- `HOST-ROUND9.log`：全部 App / Core 的宿主 macOS SwiftUI 类型检查通过；实际 EchoStore **30 / 30 合成生命周期组**通过。覆盖完整表单重建 / 地址隔离、已拒绝草稿编辑后新内容优先、daily timeout 保留同 ID / 全 payload、旧请求字段缺失、已推进 daily 对账、未知状态保持锁定、反序返回的旧边界不覆盖新值。没有 iOS / UIKit 类型与布局验收。
- `HOST-LIVE-ROUND9.log`：编译真实 Core + `Round9Smoke.swift`，使用新建临时 DB 与随机 loopback 49814，真正 Swift Foundation URLSession **18 HTTP 请求 / 4 组流程**通过；测试完成服务停止、临时 DB 清理。没有访问 18789 用户预览、原始 outputs 工程或真实 DB。此日志已对最终后端 seal（最新时间与core SHA见日志FINAL_BACKEND_SEAL_VERIFIED）重跑，全部封存server文件hash匹配。

真实 HTTP 的四组：

1. contract 1.3.0 / 最终四项能力键，重复读取同一 canonical conversation。
2. own once / daily 真实创建、时区 / 安静范围 / 同意 / 窗口 / 话题解码，daily 暂停再恢复，严格回执匹配。
3. 边界暂停 → 旧 revision PUT 得 409 → GET 确认未覆盖 → 单独使用新 revision 恢复；服务审计恰好三次显式 PUT，无自动重试。
4. 合成任务三秒后到点：无联系许可及旧未来许可失效的任务仍 review_available；daily 完成推进、原 request 按 created_due_at 对账；自己的两条任务最后取消。

列表与 unknown 待核对时间最后统一按该条保存的 time_zone 显示，并在时间旁标注时区；旧字段缺失明确写“设备时区”，不再以设备钟点冒充另一个所选时区。该展示修复后重跑全部宿主 SwiftUI 类型检查 / Store；Core 49 项源码未变。

请求白名单明确拒绝 chat / 模型、contact claim、来源、CLI、账号、通知、系统写入和硬件接口。该证据是宿主 HTTP，**不是 iOS App 运行**。没有验证真机主动呈现；源码也没有实现原生自动轻问或通知。

## 未完成的验收 / 功能边界

- iOS SDK 构建、模拟器、真机、签名安装，UIKit / iOS 专用分支，真实布局、VoiceOver 与动态字体；XcodeTests 源码尚未接入 App scheme。
- 真实 DeepSeek 聊天与断网 / 后台 / 杀进程设备恢复。R9 没有调用模型；模型只在后端配置，客户端不存 key。
- 实际飞书内容、CLI 与已有账号条件、真机文件选择 / 安全作用域、逐份撤回、真实多端 CAS / 边界冲突点按。
- 原生主动轻问、claim / recheck / finish、OS 通知、后台投递没有实现。打开时看到待办不能称已通知。
- 当前只有本机单用户服务。真机远程可达性、HTTPS、身份认证与即时跨设备同步未完成；不开放现有回环服务到公网。
- 后端目前仅支持 once / daily；编辑已保存跟进的内容 / 时间没有 PATCH 合同，不伪造编辑成功。可明确取消旧项，再重新安排；未来未知规则只读。

## 打包与后续定位

保留 `App/`、`Sources/`、`Checks/`、`HostChecks/`、`XcodeTests/`、生成工程与共享 scheme、Package.swift、验证 / 同步 / 生成脚本、README、本说明和 R9 日志。排除 `.build`、DerivedData、xcuserdata、DB、凭据、证书和本机配置。`ROUND9-SOURCE-MANIFEST.json` 是本轮文件 hash；R8 manifest / 日志仅为历史快照。

入口：`ActionViews.swift`（完整跟进表单 / 列表）、`BoundaryViews.swift`（CAS 边界）、`EchoStore.swift`（完整草稿 / pending / 恢复）、`ConnectionViews.swift`（有界预览）、`Models.swift` / `Boundaries.swift` / `APIClient.swift`（范围 DTO 与严格回执）。共享生成副本 `SharedDesign.generated.swift` 不手改，根 shared 更新后再 sync。
