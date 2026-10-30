# Android 第15轮：弹层反馈与离线本机草稿

修复两条实际路径：编辑/设置弹层固定显示当前更新和错误，正文独立滚动；当前有效身份冷启动暂时离线时，可以只读查看/复制已载本机草稿。不会发送、保存、迁移或恢复未决请求；连接与模型配置提供静态电脑端指引。验证与限制见 `ACCEPTANCE-ROUND15.md`，未生成最终包；以下旧轮次按历史证据阅读。

# Android 第14轮：前台检查另一端的更新

新增只读变化游标和轻量“检查更新”入口。另一端记忆、来源、心情、跟进或陪伴边界变更后，先暂存全部快照，再复核读取期间没有新变化才完整替换；正在编辑、上传确认、unknown 或活动聊天时保留本机状态并提示。不会自动提交、重发、迁移草稿，也不把这称为云同步或后台推送。旧服务保留显式重读入口。

本轮结果与证据界限见 `ACCEPTANCE-ROUND14.md`、`ROUND14-SOURCE-MANIFEST.json`。Android SDK / Compose 类型编译 / APK / 设备 / 真实 Keystore 仍未验收；以下 R13 及旧轮次为历史记录。

# Android 第13轮：同一后端的设备配对

新增 HTTPS 设备连接：电脑为手机生成一次显示的独立令牌，手机验证服务实例、唯一对话及设备身份后才激活。失败保留原连接；令牌及配对身份的敏感草稿用 Android Keystore 密钥 + AES-256-GCM 加密。设置可明确恢复或移除旧身份；未决请求只在原身份核对，不自动换号、迁移或重发。

已运行：**164 项纯Core/JUnit、85 项本机真实HTTP、30 项真实配对后端HTTPS、17 项合成TLS传输检查**；Android平台、Compose类型编译、APK和真机仍未执行。详情与边界见 `ACCEPTANCE-ROUND13.md`。R12及以下记录是对应轮次历史证据。

配对手机是同一成年人的设备入口，不是多账号平台。仅开放聊天、记忆、心情、所选资料上传/撤回与被动跟进；电脑 CLI、系统动作、设置和通知控制不可由手机令牌执行。TLS入口默认关闭；本轮没有开放任何局域网/公网或安装证书、SDK、账号。

# 第12轮当前状态

新增显式本机朗读：只在本人点击完整可见的回响回复后，选择已安装、无需网络且语言可用的系统 voice；提供停止入口。没有自动播放、麦克风/ASR、语音文件或服务端 TTS 调用。切地址、后台、消息删改和新播放会请求停止旧朗读；停止未确认时不会开始新播放。纯Core130项、实际Kotlin到隔离后端HTTP85项、32份Kotlin PSI语法和22项结构检查通过。详见 `ACCEPTANCE-ROUND12.md`。

**这是原生源码与Host验证；Android语音适配和Compose尚未通过SDK类型编译或设备验收，无APK。** 仍遵守暂不安装SDK。下方R11及更早说明为历史轮次。

# 第11轮当前状态

新增心情提交的持久请求账本、核对、原请求重试和预取消；取消不回滚已有记录。纯Core104项、实际Kotlin到隔离后端HTTP85项、29份Kotlin PSI语法通过。详见 `ACCEPTANCE-ROUND11.md`。这些不是Compose/Android SDK构建或设备验收；仍无APK。下方R10/R9/R8均为对应轮次历史说明。

# 第10轮当前状态

新增原生手动心情记录与可控的聊天衔接，细节及证据见 `ACCEPTANCE-ROUND10.md`。当前纯Core 94项、Host HTTP 67项、27份Kotlin PSI零语法错误；无Android SDK/安装包或设备验收。下方R9/R8说明按轮次阅读。

# 回响 · Android 原生工程

## 第九轮源码

新增统一陪伴边界、每天跟进、明确时区、安静时段与默认关闭的轻问许可；飞书预览展示实际同一快照的完整限长内容。详见 `ACCEPTANCE-ROUND9.md`。原生端目前仅管理、查看这些事项，自动轻问和系统通知仍未接入。

## 分段回复与恢复（本轮源码）

原生解析服务端 `bubbles`、`delivery_pending` 与 `delivery_next_ms`，在前台以只读请求更新有序片段，离开前台后停止轮询。地址、主对话或当前快照变化时丢弃过期结果；旧服务缺字段时按单条文字显示。普通输入草稿按服务地址隔离，升级时只迁移到当时使用的地址。Kotlin/JVM 合成数据检查了顺序与旧格式；尚未有 Android SDK 构建、App 生命周期、切换地址或真机验收。原生表情图片和语音回复尚未在本轮接通。

用 Android Studio 打开本目录。界面由 **Kotlin + Jetpack Compose + Material 3** 构成，没有 WebView。

**交付状态：真正的 Compose 原生源码已提供，实际 Kotlin/JVM 编译与 84 项单测通过；真实 Kotlin HTTP 客户端 → 隔离 FastAPI / SQLite 的 51 项链路检查通过。便携 JDK 17 已在工作区校验并运行；按本轮约定未安装 Android SDK，没有生成 APK，也未做 Android 设备验收。** JVM 结果不代表 Compose/Android 安装包已通过。

## 构建与本机联调

1. 在 Android Studio 配置 JDK 17、Android SDK Platform 35、Build Tools 35.0.0；用 SDK 设置生成本机 `local.properties`，不要提交它。
2. 执行 `./scripts/build.sh`。它先检查工程与契约，再运行 `testDebugUnitTest`、`lintDebug` 和 `assembleDebug`；缺前置环境会退出 2，并打印 `BUILD_NOT_RUN`。
3. 选择 USB 调试设备或模拟器，在开发电脑执行 `adb reverse tcp:18787 tcp:18787`，然后运行 debug App。多个设备时用 `adb -s <serial> reverse tcp:18787 tcp:18787` 指定设备。
4. 后端保持 `127.0.0.1:18787`，App 默认 `http://127.0.0.1:18787`。未配置反向转发时会如实显示无法连接；完成后点“重新连接”。

构建成功的预期位置是 `app/build/outputs/apk/debug/app-debug.apk`；**当前没有这个 APK**。Gradle Wrapper 来自 Gradle 官方 v8.11.1，JAR 与发行包 SHA256 均校验/锁定。首次构建需要访问官方依赖仓库；不会安装 JDK/SDK、修改服务端监听或打开新账号授权。

`10.0.2.2` 是常见模拟器主机别名，但当前服务端的 Host guard 不接受它。客户端不覆盖 `Host`、不伪造 `Origin`，也不要求服务端添加例外。因此本工程使用显式 `adb reverse` 保留回环防护。

真机通过网络连接仍需实际可达的 HTTPS 和受信任证书。R13已提供默认关闭的逐设备鉴权入口；手机先验证再激活。它仍是单owner个人服务，不是公网多用户产品；此次未开放 LAN/公网、反代、证书安装或新账号。

## 已连接的代码路径（下表CLI和动作仅限本机开发连接）

| 原生功能 | 实际 API / 行为 |
|---|---|
| 唯一对话 | `GET /api/conversation`；客户端不创建、拆分或选择历史会话 |
| 发送与恢复 | `POST /api/chat` 使用持久 UUID `request_id`、原 sid/原文；`GET /api/chat/turn/{id}?session_id=...` 核对，`POST .../cancel` 停止；断网保留同 ID，显式重试不会另建请求 |
| 今天续聊 | 真实 bookmark/next-step；把当前卡的内容追加到原输入草稿，再由用户点发送；另有任务、记忆和来源入口 |
| 文件选择 | Android Storage Access Framework；最多 3 份 UTF-8 文本，每份 ≤256 KB；仅在本页预览前 4000 个 Unicode 字符，显式确认后 `POST /api/local-files/confirm`，始终携带 canonical sid |
| 来源 | 飞书单文档；Notion 复用后端已有 ntn CLI；显式指定 Mac Git 目录；GitHub 已有 gh 登录；Mac 日历/提醒仅目录 ready 时读取。先说明范围，真实预览有内容和单次 token 才确认；needs_auth / needs_click 不发起新授权 |
| 记忆 | 手动新增候选、原话留存、确认、纠正、忘掉、版本历史；PATCH JSON / DELETE query 携带 expected_version；409 保留本机草稿、显示最新内容并等待显式核对；旧后端未声明 CAS 能力则阻止修改 |
| 搜索与话题 | 统一搜索已加载消息和记忆，点结果定位消息/打开记忆；话题仅本设备视图，不新建对话、不写个人记忆 |
| 本机跟进 | `GET/POST /api/followups`；完成/取消走已评审 `POST /api/followups/{id}/transition`。保存前持久 request_id；丢回执先核对同 ID，不自动重试。到期状态从服务端读取；R14由统一前台安全更新协调器刷新，编辑/unknown时暂缓，不承诺手机后台通知 |
| 任务结果 | `GET /api/actions`；新建 `POST /api/action → /{id}/commit`；继续旧预览先查同 sid、同 ID、状态 previewed，再 commit 原 ID；unknown/executing 只核对；正文可查看和复制 |
| 动作范围 | 每次 commit 都是 `real:false`；消息不发送，日历/提醒只保存本机对象，不写系统、不触发通知；用户取消创建时，晚到响应不会继续 commit |
| 来源撤回 | 显式说明后单次 `POST /api/source/revoke`；精确 endpoint/sid/操作token/source快照绑定。严格 true 回执与目标ID、已知状态和计数，再读同一对话确认目标消失才报成功；不明回执保留现有展示并只读刷新，不自动重发 |

没有模型 Key 输入；也没有读取 Keychain、CLI token、浏览器登录态或私有配置。配对模式的令牌、发送原文、草稿和请求ID保存在 App 私有 SharedPreferences 的 AES-GCM 密文中；Keystore密钥不可导出且无明文回退。云备份与设备转移显式排除这些偏好数据。R12本机开发模式的旧地址空间按原样保留，不迁入配对身份；后端才持有模型与CLI配置。旧profile按服务/对话/设备/credential-generation隔离，只有本人选恢复且在线身份匹配后才能读取原账本。

## 设计与可访问性

遵循交接 `design.md`：雾蓝 `#DCE5FF`、淡杏 `#FFE3D3`，内容用白卡，正文 16sp / 24–25sp 行高，Android 输入使用白色实底。三底部页：回响 / 对话 / 记忆。连接和任务位于回响内的主要标签页。

文字使用系统字体缩放，没有固定 `fontScale` 或单行截断；顶部、卡片和滚动弹层随内容增高。主要按钮与开关有 ≥48dp 热区。设置支持减少动态、降低透明度、光的强度；系统关闭动画时不播放呼吸。低性能设备使用半透明/不透明 M3 材质回退，**没有声称实现 Android 真背景模糊**。

本版遵循规范的浅色方案。暗色视觉在 design.md 中标为未设计，本工程不伪造完成的深色设计；需要后续设计与真机对比度验收。Rokid、脑电、录音/ASR、通知渠道/推送仍未接入，不显示“已连接”；本人点选的离线系统朗读见R12说明。

## 检查与验收

不需要 Android 环境的检查：

```sh
python3 scripts/verify_project.py
# 可选 Kotlin 语法树检查（隔离环境，仍不等于编译）：
python3 -m venv .syntax-venv
.syntax-venv/bin/pip install -r scripts/syntax-requirements.txt
.syntax-venv/bin/python scripts/check_syntax.py
```

已用便携 Temurin 17.0.21+9 和 Kotlin 2.1.20 **真实编译当前 Rules / SourcePreview / Api / ProductRules / FollowupRules / 共享资源，并通过 84 项 JUnit 测试**（记录见 `verification-jvm.log`）。涵盖默认 loopback、调试/正式 URL 边界、稳定请求 ID、unknown 不盲重发、明确 429/额度拒绝、Unicode 文件前缀，以及后端真实飞书 title/preview、日历 items/understanding、空资料/缺 token 拒绝接入。UI 按钮和 ViewModel 都会检查预览有效；推测内容不能替代可见源资料。

无需 Android SDK 的重复执行入口：

```sh
./scripts/test_rules_jvm.sh /absolute/path/to/jdk17
# 此命令使用独立 rules-jvm 工程，首次会下载 Gradle 和公开 Maven 依赖。
# 已有本次经校验的 Maven JAR 缓存时，也可完全离线复跑实际源码：
python3 scripts/test_rules_cached.py /absolute/path/to/jdk17 /absolute/path/to/verified/maven/cache
```

本次缓存仅位于上级工作区 `work/android-jvm-validation/`，没有将便携 JDK 安装到系统。缓存复跑脚本逐个核对 `scripts/jvm-dependencies.sha256.json` 中的公开依赖 SHA256；不联网、不需要 Android 许可。Android 工程编译仍由 `scripts/build.sh` 在 SDK 齐备后完成。

首次可运行后需验收：

| 验收 | 必须观察到 |
|---|---|
| 200% 系统字号 + TalkBack | 三页、白输入、长记忆、所有弹层能滚动；按钮无截断，可完整操作 |
| 断网/杀进程/重启 | 原文、sid、request_id 保留；查询或同 ID 重试；无重复用户消息/回复 |
| 停止与晚响应 | 取消后不显示过期回复；创建动作时点不用，晚到 create 不会自动 commit |
| 文件选择→预览→确认 | 取消不上传；只上传用户实际看过的前缀；接入后同一条聊天、来源可撤回 |
| 任务预览/unknown | 继续原 ID；unknown 不 POST 重试；只在真实持久结果后显示保存/回执 |

这些都是待完成的 Android 运行验收，不由 Web 或静态检查代替。

## 版本来源（2026-10-29 核对）

采用一组已发布稳定版本以降低工具链迁移风险，**不是声称它们是最新版本**：

- AGP 8.9.2 / Gradle 8.11.1 / JDK 17 / API 35：[官方 AGP 8.9 发布与兼容表](https://developer.android.com/build/releases/agp-8-9-0-release-notes)；[当前 AGP 官方入口](https://developer.android.com/build/releases/gradle-plugin)。
- Compose BOM 2025.04.01：[Android Developers 官方 April 2025 发布](https://android-developers.googleblog.com/2025/04/whats-new-in-jetpack-compose-april-25.html)；[BOM 使用说明](https://developer.android.com/develop/ui/compose/bom)。
- Kotlin / Compose 编译插件同为 2.1.20：[Kotlin Team Gradle Plugin Portal](https://plugins.gradle.org/plugin/org.jetbrains.kotlin.plugin.compose/2.1.20)。BOM 不管理 Compose 编译器。
- Activity Compose 1.10.1 与 Lifecycle 2.8.7：[Activity 官方记录](https://developer.android.com/jetpack/androidx/releases/activity#1.10.1)、[Lifecycle 官方记录](https://developer.android.com/jetpack/androidx/releases/lifecycle#2.8.7)。
- Wrapper：[Gradle v8.11.1 官方脚本/JAR](https://github.com/gradle/gradle/tree/v8.11.1/gradle/wrapper)，SHA256 文本来自 `services.gradle.org/distributions/` 对应版本文件。

## 交接前元数据修复

本轮追加Message.createdAt与Memory.sourceMessageId可选默认字段，记忆详情按真实原话消息关联时间，缺失时明确未提供；来源标签另列。忘记说明明确关联来源可能暂停、无关独立资料保留。实际Api.kt编译与元数据兼容检查3项通过，见verification-api-metadata.log；此前Rules/SourcePreview14项记录独立保留。MainActivity尚未由Android/Compose SDK编译。


## Round 8 核心补齐 · 2026-10-30

本轮实际代码增加统一搜索与定位、本机话题、手动新增记忆候选、可保留/恢复的记忆编辑草稿与 CAS 冲突对照、既有 CLI 只读连接路由、本机跟进创建/查看/到期/完成/取消。回到前台会重新读取唯一对话并核对 pending，不自动重发。来源目录和能力均来自真实后端；不可用入口显示条件，不虚构已接入。

`shared/EchoSharedReference.kt` 已被 UI 和默认偏好真实引用。完整仓库修改共享设计后，运行根目录生成器，再执行本端 `python3 scripts/sync_shared.py`；构建入口会先检查共享资源漂移。独立 Android 代码包已带生成后的 Kotlin 源文件，不需要手动拷贝。已有用户偏好保留；仅新用户使用减少动态 false / 降低透明度 false / 光强 .70，系统关闭动画仍优先。

进一步的无需 Android SDK 验证：

```sh
python3 scripts/check_kotlin_cached.py /jdk17/home /verified/maven/cache
# 使用经校验的官方 Kotlin PSI 解析所有 KT/KTS；不代表 Compose 类型编译。

# 在完整仓库中，以已经安装 FastAPI/uvicorn 的 Python 环境执行：
python scripts/test_backend_http_cached.py /jdk17/home /verified/maven/cache
# 实际 Kotlin EchoApi -> 临时 SQLite + loopback FastAPI，共34项；无用户数据、无模型、无CLI调用。
```

本轮日志：`verification-jvm.log`（71项）、`verification-backend-http.log`（实际后端HTTP34项）、`verification-syntax.log`（Kotlin解析）。JDK 的 URLConnection 不支持 PATCH，Host HTTP 的记忆用例只验证 JSON 与 409 解码，**没有冒充 Android PATCH 验收**。Android API 35 的系统实现支持 PATCH（[AOSP 源码](https://android.googlesource.com/platform/prebuilts/fullsdk/sources/+/refs/heads/androidx-constraintlayout-release/android-35/com/android/okhttp/internal/huc/HttpURLConnectionImpl.java)）；仍需真实 Android 平台验收。

**用户暂不安装 Android SDK，因此 Compose/Android 类型编译、APK、200% 字号、TalkBack 和手机端后台/进程恢复仍未验收。** 当前交付可供 Android 开发同学接续打磨，不能标为已安装或已完成上架。Web 与桌面测试不能替代这些门槛。


### 跟进未知账本修复 · 历史阶段与当前保留规则

`FollowupDraft` 现在持久保存 `started`，在发 HTTP 前先写下同一个请求标识、原内容、原时间和已开始状态。旧版本没有 `started` 字段但已有请求 ID 时，按已尝试处理。

只有从未尝试的新请求，第一次收到后端明确 `400 invalid_request / confirmation_required` 或 `422 validation_error`，才返回可修改草稿并释放 ID。超时/连接丢失之后的重试即使返回 400/422，仍保留原 ID；401/403/404/408/409/429/5xx 和未识别错误也不自动换号。只有实际匹配 session、request ID、内容、同一时刻以及已知状态的列表记录，才确认已保存并清除未决账本。成功回执后的列表刷新失败不会再把已确认请求放回未知状态。

该历史阶段**重新编译实际 Core 并运行47项JUnit通过**，新增7项保存状态转换测试，以及实际 Native EchoApi 的 `503 → 400` HTTP序列，断言两次 payload 和 ID 保持一致。真实 Kotlin → 隔离 FastAPI / SQLite 10项也重新执行通过；20份 KT/KTS 重新解析无语法错误。日志已经更新，先前39项结果不作为本次新修复证据。Android SDK/Compose/APK/真机门槛仍未完成。


### 单来源撤回回执修复

不再把 HTTP200 当作撤回成功。新 `SourceRevocationAttempt` 绑定当前 endpoint / canonical sid / 本机操作 token / 精确 source 快照；开始前资料变更则不发送请求。只有真正的 Boolean `ok:true`、精确单来源 `revoked_source_ids`、已知状态、有效计数，以及同一对话读取结果确认目标不再存在，才显示“已移除”。`ok:false`、缺字段、错误来源、未知状态、请求/页面过期或刷新失败一律不报成功；没有乐观删除或盲目重发POST。只读刷新可反映当前服务的实际资料列表，其他来源和输入草稿保留。

修改后重新编译实际 Core 并通过 **71项JUnit**。新增10项撤回状态/race测试和1项实际HTTP200 false/缺字段/未知状态序列，断言每次只有一个POST与一次GET、原来源仍可见。真实 Kotlin EchoApi → 隔离FastAPI/SQLite烟测现为 **34项**，新增两份合成资料的单独撤回、另一份保留、重复撤回404及未明回执不能报成功。22份KT/KTS重新解析无语法错误。日志均为本次源码新跑；这仍不替代Android SDK/Compose或真机验收。


## 三方合并与精确停止 · 最终复核

合并保留了两边的分段回复、按服务地址隔离的普通草稿、一次性跟进账本、来源撤回和记忆CAS。周期跟进按服务返回的 `repeat_rule/paused/quiet` 展示；缺字段默认 once / false / false。每日或未知重复类型只读并提示去 Web 管理，不能按一次性按钮完成或取消，也不能误清一次性未决请求。新建周期跟进、暂停、恢复、安静时段编辑和手机后台调度尚未实现。

分段展开的“停止展开”与模型生成的“停止回复”分开。只有后端明确声明 `features.chat_delivery_targeted_stop=true` 才显示和发送前者，POST必须携带当前最新 assistant 的 `message_id`；旧服务即使有同名路由也不试探。只有严格 Boolean true、精确 ID / reason 回执及同一主对话GET核对后才说已停止；false、旧ID、未知回执或刷新失败仅提示核对，没有自动重发。此次真实HTTP检查包含无ID和旧ID不能停止最新消息、正向精确停止及重复请求false，未调用模型或语音服务。

最终记录见 `ROUND8-MERGE.md`、`VERIFICATION.md` 和 `round8-change-manifest.json`。当前新日志为 **71项Core JUnit、34项真实本机HTTP、22份Kotlin PSI 0语法错误**。这不代表 Compose/Android类型编译、APK或手机验收已完成。本地时间不存在（DST跳变）会拒绝；重复的本地时间目前采用Java默认offset，不能声称该交互已完整验收。


### 记忆提议的用户选择与409回退

设置中的「聊天后，可以提议记住一件小事」默认关闭，明确保存到本设备；已发送请求会持久冻结当时的 `memory_proposals`。恢复、取消和状态核对不读取新的开关值重写旧payload；旧未决记录缺字段按原始false处理。服务返回的原话提议必须匹配当前请求的用户消息和字面文字才显示，仍由你选择「记住这句」，没有自动保存或确认。

对普通原话明确「记下这句」遇到409时，原话保留并显示「整理为候选记忆」。点该入口仅预填持久编辑草稿；已有草稿不覆盖。再一次明确保存才POST `/api/memory`，不传confirm/status、不伪造原话来源关联，默认仍为待确认候选；需要用户另外确认才能作为确认事实。71项Core与34项实际后端HTTP已覆盖选择快照/旧pending、严格原话提议回执和真实409→显式手动候选的边界。Android设置持久化和UI设备操作仍待SDK/真机验收。
