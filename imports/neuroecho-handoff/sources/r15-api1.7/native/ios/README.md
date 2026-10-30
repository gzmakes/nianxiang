# R15：编辑页反馈、能力重查与本机草稿副本

当前源码在 R14 上修复三处可用性：受保护编辑页显示准确的断网/待检查状态，并提供只读检查；能力清单短暂失败时明确为“尚未核对”，本人可重新 GET，不再把失败当作不支持；设备连接页的每份已保存身份都可只读查看、选择或复制本机草稿文字，失效/已移除凭据也可查看。不会激活旧身份、读取其令牌、恢复请求编号、迁移或自动发送。

详见 [ACCEPTANCE-ROUND15.md](ACCEPTANCE-ROUND15.md)。本轮只交付源码与宿主检查；没有 iOS SDK、UIKit、模拟器、IPA、手机或真实 Keychain/剪贴板操作验收。下面 R14 与更早部分保留为历史范围与证据，不表示手机已完成验收。

# R14：前台只读发现其他设备的变化（当前源码）

连接同一后端后，前台按需 GET changes → 暂存完整快照/所需域 → 稳定性复核，再一起发布内容与第一份 cursor。编辑、聊天草稿、unknown、正在发送或上传确认时先保留原内容；“检查更新”不会自动写入或覆盖草稿。退后台停止，失败退避；无并行刷新、推送或离线合并。

详见 [ACCEPTANCE-ROUND14.md](ACCEPTANCE-ROUND14.md) 与 [ROUND14-SOURCE-MANIFEST.json](ROUND14-SOURCE-MANIFEST.json)。当前证据为 Foundation78、macOS App/Core 类型检查、原 Host30+13+17+9+18、新刷新 Store18；临时 HTTPS 两客户端10流程与 R13 传输回归10流程。**没有 iOS SDK、模拟器、IPA、真机或真实 Keychain；不可称手机已经完整验收。**

原服务未声明 `conversation_change_cursor` 时继续显式刷新；新的 cursor 不迁移旧 pending 或设备身份，重启先重新 baseline。实际手机仍需本人准备可达且被系统信任的 HTTPS。下面 R13 及更早章节是保留的历史实现/证据说明，最新行为以上述 R14 验收为准。

# R13：同一后端的安全设备连接（最新源码范围）

设置新增「设备连接」：从电脑本人明确生成的设备令牌与 HTTPS 地址验证，再启用同一持续对话。先核对服务实例、设备和主对话，成功后才写入本应用的精确 Keychain 条目。令牌不进入 URL、普通草稿或模型；旧身份草稿和 unknown 请求不迁入新许可。

- 401 停用并清理对应本机令牌；实例变化的 409 仅停用，保留原身份供回原实例验证。403、断网或钥匙串锁定不当作撤销。
- 本机保留的旧连接有明确「验证并恢复」与「移除本机令牌」入口。恢复核对同一实例 / 设备 / 主对话，只读恢复；移除仅删除所选本应用凭据，草稿仍隔离保留，也不撤销服务器许可。
- 手机设备连接仅用个人核心 API。CLI、电脑系统动作、硬件、账号管理与模型设置不开放；所选文本文件和已有来源撤回仍可用。后台不自动连接、不自动发请求、不投递系统通知。连接页离开或退后台会清空令牌输入，并作废仍在验证的 attempt。

详见 [ACCEPTANCE-ROUND13.md](ACCEPTANCE-ROUND13.md)。R13 的当前证据、真实 HTTPS 临时服务与无 iOS SDK / 真机边界以该文档和 [ROUND13-SOURCE-MANIFEST.json](ROUND13-SOURCE-MANIFEST.json) 为准。下面 R12–R10 日志只说明历史验证；不能把宿主 SwiftUI / URLSession 或 macOS 系统语音当作 iOS 已运行。

# 回响 iOS 原生工程 · R10

## R12 增量：点选回复朗读

完整回复下新增设备系统“朗读 / 停止朗读”小按钮，不自动播放、不申请麦克风或个人声音权限、不上传 TTS、不创建产品音频文件。未完成回复不能朗读；旧消息只读实际可见段。服务 / 前后台 / 消息改删变化停止，旧回调不能清新播放。

详见 [ACCEPTANCE-ROUND12.md](ACCEPTANCE-ROUND12.md) 和 [ROUND12-SOURCE-MANIFEST.json](ROUND12-SOURCE-MANIFEST.json)。本轮 Foundation64、原Store30+13+17、新SpeechController9组通过；真实macOS系统引擎合成临时WAV并验证非零采样，文件已删除，**不是扬声器或iOS真机验收**。没有 iOS SDK / IPA；以下 R11 与 R10 段落为历史范围与能力说明。


## R11 增量：心情提交账本

当前副本增量加入原编号恢复、明确重试与元数据取消。能力 `mood_operation_ledger` / API 1.5；旧无 ID 未决记录继续旧 GET 核对，不补造身份。取消意图先落盘，之后不再 apply；已处理的取消不会回滚，终态还需核对当前日记。详见 [ACCEPTANCE-ROUND11.md](ACCEPTANCE-ROUND11.md) 和 [ROUND11-SOURCE-MANIFEST.json](ROUND11-SOURCE-MANIFEST.json)。

R11 证据：Foundation 59、原 EchoStore 30 / MoodStore 13、新账本 MoodStore 17 组合成检查；真实宿主账本 HTTP 61 / legacy CRUD 21 / R9 回归 18 请求。没有 iOS SDK / 模拟器 / 真机或自动主动联系验收。以下原 R10 段落是历史范围说明，新账本能力与恢复方式以 R11 验收为准。


SwiftUI 原生源码，最低 iOS 17，不是 WebView。所有页面继续使用 `GET /api/conversation` 的同一持续对话；不展示技术性会话编号、“会话已恢复”或新建会话；单次发送结果不确定时仍明确提示核对。视觉遵循根目录 `design.md`，共享色板、导航、默认偏好和 F5 边界文案实际引用 `App/SharedDesign.generated.swift`。

**可以交给 iOS 开发同学继续打磨；目前没有 IPA、iOS SDK 构建、模拟器、签名或真机验收。用户明确暂不安装 Xcode。**

## 最新证据

R10在R9基线上分块新增手动心情日记；没有整份覆盖原工程的旧Models/API/EchoStore。详见 [R10验收说明](ACCEPTANCE-ROUND10.md)，R9说明保留为历史。用户暂不安装Xcode，仍没有iOS SDK、模拟器、签名或真机验收。

- `sh validate.sh`：工程生成、plist / pbxproj、Swift语法、实际Foundation Core编译，**54 / 54合成契约**通过（保留R9原49项）。
- `sh validate_host.sh`：全App/Core宿主macOS SwiftUI类型检查；R9实际Store **30 / 30**、新独立MoodStore **13 / 13**合成生命周期组。不是UIKit / iOS类型或设备运行。
- `HostChecks/run_round10_mood_smoke.py`：新建临时DB / 随机loopback服务，真正URLSession **21请求 / 4流程组**，手动CRUD、CAS409、删除重建旧token拒绝和日记不进入聊天/记忆/F5。没有模型、规则建议、账号或设备调用。
- R9原生18请求 / 4流程组另在1.4后端重新执行，验证daily / 联系范围 / 边界CAS与旧许可失效仍在；不是新增主动呈现或手机通知。

手动日记默认只存本人记录，不被模型读取。显式“带到聊天，由我发送”先显示将带入的内容，只追加原聊天草稿；本人另按发送后才按当前聊天模型处理。心情不是自动记忆、设备识别或心理诊断。图只展示，当前用滑杆选择；尚未实现原生画布拖动、候选推断、心理练习或自动主动问。

## 原生能力与边界

| 流程 | 实现与边界 |
|---|---|
| 手动心情日记 | 日期 / 两轴 / 选填文字，初始0/0仍未选择；完整本机草稿与unknown快照，显式CRUD/CAS核对，先预览后带入聊天草稿；无自动模型读取 / 记忆 / 联系 |
| 对话与分段 | 稳定 request ID / 原 payload 持久化，202 与 unknown 只读核对；显式同 ID 重试。分段 GET 恢复；定向停止绑定 assistant ID 与能力键，真实 `stopped:true` 加 GET 核对才称停止。模型 cancel 独立处理 |
| 检索 / 话题 / 草稿 | 当前消息与记忆本机统一检索；定位消息 / 记忆详情。话题只筛选同一对话。普通聊天草稿、话题与 pending 按服务隔离；R13 配对模式进一步按实例 / 设备 / credential generation 隔离，模型记忆提议偏好仍为本应用设置 |
| 记忆 | 手动候选 / 原话确认、修改、确认、版本和忘掉；CAS 409 保留内容、读最新后明确再确认，未知动作状态不报成功 |
| 资料 | 范围 → 真实预览 → 明确确认。飞书须有长度自洽的完整有界文本（最多 12000 字），展示截取范围并可展开实际保留内容；只有标题不能接入。撤回仍保留 R8 保护 |
| 跟进 | 原生创建 once / daily；完整时区、安静起止、联系同意 / 话题 / 窗口。每日完成只提交当前 occurrence，推进后按 created_due_at 核对原请求；暂停 / 恢复 / 整项取消；未知规则只读 |
| 跟进恢复 | 普通表单也持久化。新 pending 冻结所有参数；旧 pending 不补入新字段。首次明确 400 / 422 回到可编辑草稿；先前超时后的 4xx 不释放 ID；严格内容 / 时间 / 范围和已知终态核对 |
| 统一边界 | GET / PUT companion-boundary，expected_revision CAS；今天安静 / 暂停到时间 / 无限暂停 / 明确恢复；409 或未知结果只读核对，不自动覆盖。默认 rev0 用设备时区配置今天边界 |
| 轻问许可 | 默认 false，逐项确认话题和 5–180 分钟窗口；daily 明示每次窗口最多一次。边界改变、拒绝或撤源使全部旧许可失效（包括未来项），待办保留；恢复不复活旧许可。当前 iOS **不自动呈现轻问，也不调用 claim 或系统通知** |
| 被动待办 | 使用 review_available，不以 contact available 判定是否可查看；即使没有联系许可，任务仍可被动查看 / 完成 / 取消 |
| 连接 | 飞书 / Notion / Git / GitHub / Mac 日历和提醒走服务端真实路径，取决于已有 CLI / 权限；不是读取 iPhone 日历。Gmail 未配置则明确未接入；不新增登录 |
| 动作与硬件 | 动作先计划后确认，commit 固定 real:false。Rokid / EEG 待联调；没有假接通、情绪解码或未经确认系统写入 |

## 开发入口

1. 有完整 Xcode 的开发同学打开 `Echo.xcodeproj`，选择共享 **Echo** scheme；工程没有 Team、证书或描述文件。不要自行代入账号。
2. 旧开发路径仍默认 `http://127.0.0.1:18787`，仅本机 / 模拟器调试；真机回环是手机自身。R13 真机需使用本人部署、设备可达且证书被系统信任的 HTTPS 配对入口，再在设置中手动验证令牌；不会自动开放局域网、安装证书或使用匿名 HTTP。
3. 本工程没有 Swift 第三方依赖。`Sources/EchoCore` 是 Foundation API / DTO / 状态规则；`App/EchoStore.swift` 管理恢复；SwiftUI 页面在 `App/`。
4. 新 Swift 文件后运行 `python3 generate_project.py` 更新生成的 project / scheme；脚本会重写它们，先保留开发同学的手工工程改动。
5. 共享资源由根 `shared/` 生成后运行 `python3 sync_shared.py`；`--check` 检查漂移。保留已保存的用户偏好，系统减少动态 / 透明度优先。

本机可复现源码检查：

```sh
sh validate.sh
sh validate_host.sh
```

只有需要实际 HTTP 时，使用已安装 FastAPI / uvicorn 的项目 Python 在完整项目根运行：

```sh
python native/ios/HostChecks/run_round10_mood_smoke.py
```

该脚本只新建临时合成 DB / 随机 loopback 服务，完成后停止。不要把历史脚本的固定端口当作隔离环境。Core 合成检查本身没有联网、模型或系统写入。

## 开发同学第一轮

1. iOS SDK 构建与模拟器运行，确认 UIKit 分支、工程设置、完整动态字体 / VoiceOver / 键盘安全区。
2. 点按持续对话、搜索定位、原话候选、CAS 冲突、飞书完整预览和逐份撤回；真机文件选择 / 安全作用域。
3. 前台到点、后台 / 杀进程 / 断网恢复，确认pending不变payload、不自动重发；daily当前次完成、边界冲突和旧许可失效；心情unknown只GET、409保留草稿、跨日期恢复和原聊天草稿追加。
4. 真机需要可达 HTTPS 与身份验证方案；当前后端 `local_single_user`，不能直接公开本机服务。
5. 若将来做原生主动轻问，必须另做统一 claim → 重新校验 → 呈现 → finish、前后台生命周期与去重；本轮仅有任务查看和许可设置，不能把 UI 开关当已经投递。

UserDefaults 保存普通草稿、话题、偏好和 pending，并非独立加密保险箱或跨设备同步。打包排除 `.build/`、DerivedData、xcuserdata、DB、凭据、证书与本机模型配置。签名、图标、安装包、分发和 App Store 提交另验。
