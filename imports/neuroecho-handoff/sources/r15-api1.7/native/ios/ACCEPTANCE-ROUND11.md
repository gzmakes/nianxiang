# iOS R11 心情提交账本验收

交付为 SwiftUI 原生源码。本轮没有安装 Xcode / iOS SDK，没有 IPA、模拟器、签名、真机点按或布局验收。宿主 SwiftUI 类型检查、URLProtocol、实际 macOS URLSession 证据分别列出，均不等于 iOS App 运行。

## 这轮完成

在 R10 副本增量修改 Mood DTO / API / Store / View；保留单一持续对话、F5、daily、来源撤回、聊天 unknown、记忆 CAS 和日记默认不进模型的边界。

- 服务声明 `mood_operation_ledger` 才为**新**提交准备 UUID 和精确 `operation_json`。发送前完整保存服务 / 对话 / 日期、原编号、原 JSON 和原 CAS token；重开或重试不会重新序列化 JSON、换编号或采用新 token。
- 传输失败、格式错误、不匹配回执或服务 422 均保留账本未决身份。普通保存不能重发；用户可只读核对、明确用原请求重试，或确认取消。`not_found` 不等于原请求不会晚到，不会自动解锁。
- 取消前先持久 `cancelRequested`。此后跨重启也只能 GET 或用同 hash / kind 再次取消，不能再 apply。取消请求只发元数据，没有日记日期、原文或原 JSON。服务确认 `cancelled` 后保留可编辑草稿；迟到同一 apply 仍返回取消墓碑，不会写入。
- `applied` / `conflict` / `cancelled` 均严格核对六字段回执、服务对话、原编号、SHA256、kind 和 token。CAS 冲突是 HTTP 200 的终态，不能当保存成功；身份冲突 409 不能换 ID 静默重试。
- 所有终态另 GET 当前日记。已处理的历史提交若后来被修改 / 删除 / 重建，不复活旧正文；保留草稿，需明确采用当前版本后另行确认。取消若晚于写入只说明已经处理，不假称回滚。终态后 GET 失败仍保持未决，后续只读核对。
- R10 **无 ID** 的未决快照不迁移、不补造编号、不开放账本重试 / 取消，只沿旧 GET 核对。服务没有能力键时，新操作仍用原 R10 接口；已有账本 pending 遇能力降级保持保护，不改走旧 PUT / DELETE。
- 继续按 origin / sid / generation / sequence / mutation ID 隔离晚回执。取消和重试的界面确认还绑定当前 mutation ID。落盘失败保留文字，阻止写入与取消请求。
- 实际引用共享 `copy_mood_recovery_check/retry/cancel/cancelled/applied`；“带到聊天”仍只追加现有聊天草稿，用户另按发送才交给聊天模型，不存记忆或联系许可。

## 可复核证据

| 证据 | 结果与边界 |
|---|---|
| `VALIDATION-ROUND11.log` | 工程生成、plist / pbxproj、Swift 语法和 Foundation **59 / 59**；R10 原 54 加 5 组账本检查。包括精确 raw SHA、旧数据 decode、缺 nullable 键 / 不匹配 / 未知状态拒绝、元数据取消和严格删除 token |
| `HOST-ROUND11.log` | 全 App / Core 的 macOS SwiftUI 类型检查；实际 R9 EchoStore **30 / 30**、原 MoodStore **13 / 13**、新 ledger MoodStore **17 / 17**组，均使用合成 URLProtocol；不是 iOS 运行 |
| `HOST-LIVE-LEDGER-ROUND11.log` | **61 次真实 HTTP / 10 流程组**，Swift URLSession + 实际 MoodStore → 最终 1.5 临时后端。含 3 轮并发 apply/cancel、并发同 ID apply、raw 空白变更 409、取消墓碑、删除重建、历史结果、4 次测试中间件 HTTP503 故障（提交前 / 后丢回执、取消前丢回执），验证重启后不再 apply、原请求重试和独立当前行核对 |
| `HOST-LIVE-LEGACY-ROUND11.log` | 原 R10 CRUD 的 **21 次真实 HTTP / 4 流程组**，在 1.5 后端新建临时 DB 回归；旧 PUT / DELETE CAS 与 ISO token 编码保留 |
| `HOST-LIVE-R9-REGRESSION-ROUND11.log` | 原 R9 **18 次真实 HTTP / 4 流程组**重新跑过：daily / F5 CAS / 旧未来许可失效；不是原生自动联系投递 |

实际 HTTP 仅用新的临时合成 DB、随机 loopback 端口；每个服务在脚本 finally 停止。账本脚本校验后端 seal 的全部 server hash，审计只开放白名单路径。没有调用模型、账号授权、来源读取、CLI、系统通知、硬件或 contact claim。HTTP503 仅由隔离测试中间件注入，非生产服务错误率或真实断网证据。

XcodeTests 同步了 Foundation 场景，但未接入 / 运行 XCTest。历史 R8 / R9 / R10 日志与 manifest 仅留作历史，本轮以命名 ROUND11 的证据为准。

## 设备首轮仍需

1. 安装完整 Xcode / iOS SDK 后构建 UIKit 分支、模拟器 / 真机签名；验证日期选择、滑杆、长文字、VoiceOver、动态字体、键盘与安全区。
2. 真机断网 / 杀进程 / 前后台恢复：未决完整 JSON 和 UUID 保留，点击“核对 / 重试 / 取消”，取消意图不丢、不补发；确认弹框和重复点击只操作原条目。
3. 验证本机 UserDefaults 写入 / 磁盘故障提示；它不是独立加密保险箱或跨设备同步服务。
4. 连接可达的 HTTPS 与真正的身份鉴权、后端配对；当前后端 `local_single_user`，不等于公网多用户服务。原生没有自动主动问候、后台投递或 OS 通知闭环。
5. 真机复验 R9 来源逐份预览 / 确认 / 撤回、聊天取消与未知恢复、记忆 CAS / 搜索定位 / 草稿和 daily / F5 边界。SDK 缺失是验收门槛，不能据此声称源码出错或全端完成。

## 重跑入口

- `sh native/ios/validate.sh`
- `sh native/ios/validate_host.sh`
- 在已有 FastAPI / uvicorn Python 环境运行 `HostChecks/run_round11_mood_smoke.py`、`run_round11_legacy_smoke.py`、`run_round9_smoke.py`。只使用脚本创建的临时服务，不传用户预览 URL。

打包排除 `.build/`（含本轮备份）、DerivedData、xcuserdata、DB、凭据、证书、模型配置。R11 源码 manifest 用于复核本轮快照，不代表手机包或云同步验收。
