# 第15轮当前结果

见 `ACCEPTANCE-ROUND15.md`：只读草稿/反馈纯策略与原回归共 198 项 Core/JUnit 通过；PSI、结构和共享检查另记录。弹层布局与剪贴板尚待 Android 运行验收；本轮无协议变更，未重复历史 HTTP/HTTPS 套件。以下为历史记录。

# 第14轮当前结果

先读 `ACCEPTANCE-ROUND14.md`；最终计数/源码哈希见 `ROUND14-SOURCE-MANIFEST.json`。新增只读变化发现、两次游标复核、暂存后原子替换及前台/编辑/unknown/身份守卫。Android SDK / Compose 类型编译 / APK / 设备仍未执行；纯 Core、Host HTTPS 与 PSI 不代表平台验收。以下是历史记录。

# 第12轮当前结果

先读 `ACCEPTANCE-ROUND12.md`：实际Core130项（含26项朗读状态机）、Host HTTP85项、32份PSI语法、结构22项、共享同步通过。系统TTS driver和Compose没有SDK类型编译，未生成APK或进行听感/生命周期设备验收。历史记录见下文，各轮日志独立保留。

# 第10轮当前结果

先读 `ACCEPTANCE-ROUND10.md`：94项Core / 67项真实Host HTTP / 27份PSI。新增心情日记不自动调用模型；Android SDK和设备仍未验。下方内容为历史记录。

# 第九轮当前结果

先读 [ACCEPTANCE-ROUND9.md](ACCEPTANCE-ROUND9.md)：84 项 Core JUnit、51 项真实 Host HTTP、24 份 Kotlin PSI 零语法错误；Android SDK/设备尚未验收。下方第八轮为历史记录。

# Android 验证记录 · 2026-10-30 Round 8

| 层次 | 本次实际结果 |
|---|---|
| Kotlin Core / JSON / 路由 / Unicode / 草稿 / 冲突 / 跟进规则 | Kotlin 2.1.20 实际编译工程源代码；JUnit **71/71** 通过，见 `verification-jvm.log` |
| 原生 API 客户端至真实后端 | 实际 Kotlin EchoApi → loopback FastAPI → 临时 SQLite，**34/34** 通过：唯一对话、跟进能力、创建、同ID幂等、列表、丢回执核对、POST transition取消、重复取消、409终态冲突、最终持久状态，以及单来源精确撤回、另一份保留、重复撤回404与未明回执不报成功；以及精确delivery-stop能力、无ID/旧ID无变异、最新pending保留、true停止、重复停止false与首段保留；见 `verification-backend-http.log` |
| 全部 KT/KTS 语法 | 经校验官方 Kotlin compiler PSI；`verification-syntax.log`。不解析 Android / Compose 类型 |
| 共享资源 | `scripts/sync_shared.py --check` 通过；App 真正引用生成颜色、文案、字体/触控/圆角和默认偏好；不覆盖已有用户偏好 |
| 工程结构、XML、权限、API 路径、Host / Origin | `scripts/verify_project.py` 22项通过；这是结构检查 |
| JDK | 复用工作区已校验 Temurin17.0.21+9，没有全局安装或修改 shell |
| Android SDK、Compose 类型编译、lint、APK/AAB、模拟器、真机 | **未执行。用户明确暂不安装SDK；没有生成APK/AAB** |
| 200%字号、TalkBack、手机进程/生命周期和真实Android HTTP | **未完成运行验收**，不会用Host结果代替 |

Host 的真实HTTP烟测没有接触用户数据库、调用CLI来源、访问账号或调用模型。数据库在临时目录，服务绑定随机 loopback 端口，检查完成后退出并移除合成数据。

JDK URLConnection 不支持 PATCH。Host 记忆HTTP用例以POST验证实际 JSON body 与409解码，不能证明 Android PATCH 已运行。Android API35系统 URLConnection 实现的允许方法包含 PATCH，且有对应方法覆盖；[AOSP官方源码](https://android.googlesource.com/platform/prebuilts/fullsdk/sources/+/refs/heads/androidx-constraintlayout-release/android-35/com/android/okhttp/internal/huc/HttpURLConnectionImpl.java)支持源码判断，但真机验收仍单独保留。跟进状态变更采用已评审的 POST `/api/followups/{id}/transition`，Host烟测验证的是这个实际路径。

主要源码：`Api.kt`、`Rules.kt`、`SourcePreview.kt`、`ProductRules.kt`、`FollowupRules.kt`、`EchoViewModel.kt`、`MainActivity.kt`。纯Core编译日志含被测源码SHA256。UI与ViewModel有真实代码，但尚未用Android SDK解析类型或运行。

## 既往记录 · 2026-10-29（历史，不覆盖本轮结果）

| 层次 | 实际结果 |
|---|---|
| 工程结构、XML、权限、API 路径、默认 URL、Host/Origin 边界 | `python3 scripts/verify_project.py`：22 项通过 |
| Kotlin/Gradle Kotlin 语法树 | Tree-sitter 0.26.0 + Kotlin grammar 1.1.0：8 个文件、0 grammar error；这不解析 Android/Compose 类型 |
| Shell/Python 工具语法 | `sh -n gradlew`、`sh -n scripts/build.sh`、Python 编译检查通过 |
| Wrapper 来源 | Gradle 官方 v8.11.1 JAR SHA256 与官方 `wrapper.jar.sha256` 相同；发行 ZIP SHA256 锁定 |
| Maven 元数据存在性 | AGP8.9.2、BOM2025.04.01、Activity Compose1.10.1、Lifecycle ViewModel Compose2.8.7 在 Google Maven 返回200；Coroutines Android1.10.1 在 Maven Central 返回200；POM可解析 |
| JDK / SDK 构建 | 最初 `./scripts/build.sh` 因缺 JDK 退出2；后续便携 JDK17 已通过校验并真实执行，但 Android SDK Platform35 仍未发现；未执行 Android/Compose 编译、lint、assemble |
| JVM 规则与预览合同单测 | 便携 Temurin17 + Kotlin2.1.20 实际编译当前 Rules.kt/SourcePreview.kt 及对应测试；JUnit4.13.2：**14/14通过**，详见 `verification-jvm.log` |
| APK/AAB、模拟器、真机、200%字号、TalkBack、原生HTTP到后端 | **没有验证；没有生成APK/AAB** |

Gradle Wrapper JAR SHA256：

```text
2db75c40782f5e8ba1fc278a5574bab070adccb2d21ca5a6e5ed840888448046
```

Gradle 8.11.1 binary ZIP SHA256：

```text
f397b287023acdba1e9f6fc5ea72d22dd63669d59ed4a289a29b1a76eee151c6
```

调试路径固定为 `http://127.0.0.1:18787` + 开发者明确执行 `adb reverse tcp:18787 tcp:18787`。未运行转发，没有宣称连接成功；没有改服务端 Host guard、监听、LAN 或公网配置。

语法解析工具临时安装于工程内隔离目录，完成后已移除；重复语法检查可用 README 的隔离 venv 指令。它们不属于 Android 运行依赖。

## 后续真实 JVM 验证

便携 JDK 从 Adoptium 官方 `adoptium/temurin17-binaries` 发布下载，仅解压于上级工作区 `work/android-jvm-validation/`；没有安装到全局、修改用户 shell 环境或接受 Android SDK 许可。实际执行 `java -version` 为 Temurin17.0.21+9。官方源 URL 与 release 信息见 `verification-jdk.json`。

官方 archive SHA256 与本地完整文件一致：

```text
78b08c7f5a0598242d5719c022e19479cb4a3aa45c37c19726a757a469ed1c15
```

Kotlin 编译器及 JUnit、JSON-java 等公开 JAR 来自 Maven Central，并校验各自发布的摘要；重复运行用的 SHA256 清单保存在 `scripts/jvm-dependencies.sha256.json`。本次直接运行 Kotlin 编译器编译**工程实际源文件**，再运行 JUnit；没有使用 Android stub 或复制实现替代测试。`rules-jvm/` 也提供独立 Gradle JVM 入口，但本次没有为它再下载整份 Gradle 发行包。

14 项测试包含真实飞书 `title+preview` 字段（无 items）仍能显示正文、日历 items 和事实/推测分别展示、空内容或缺失单次 preview_id 不可确认，以及明确 budget_exceeded/429 与普通 unknown 的不同处理。原生 UI 与 ViewModel 都使用同一实际预览解析器。

**边界仍在：这不是 Android/Compose 类型检查；SDK35、APK/AAB、adb reverse、设备 HTTP、200% 字号和 TalkBack 均未验收。** 没有因 JVM 测试通过而把任何来源标成“已连接”。


### 跟进未知账本修复 · 历史阶段记录

`FollowupDraft` 现在持久保存 `started`，在发 HTTP 前先写下同一个请求标识、原内容、原时间和已开始状态。旧版本没有 `started` 字段但已有请求 ID 时，按已尝试处理。

只有从未尝试的新请求，第一次收到后端明确 `400 invalid_request / confirmation_required` 或 `422 validation_error`，才返回可修改草稿并释放 ID。超时/连接丢失之后的重试即使返回 400/422，仍保留原 ID；401/403/404/408/409/429/5xx 和未识别错误也不自动换号。只有实际匹配 session、request ID、内容、同一时刻以及已知状态的列表记录，才确认已保存并清除未决账本。成功回执后的列表刷新失败不会再把已确认请求放回未知状态。

此次修改后**重新编译实际 Core 并运行47项JUnit通过**，新增7项保存状态转换测试，以及实际 Native EchoApi 的 `503 → 400` HTTP序列，断言两次 payload 和 ID 保持一致。真实 Kotlin → 隔离 FastAPI / SQLite 10项也重新执行通过；20份 KT/KTS 重新解析无语法错误。日志已经更新，先前39项结果不作为本次新修复证据。Android SDK/Compose/APK/真机门槛仍未完成。


### 合并后再次验证的撤回规则

最新结果为 **71项实际Core编译JUnit、34项真实Kotlin→隔离后端HTTP、22份官方Kotlin PSI解析0错误**。撤回只在严格 true / 精确来源 / 当前操作与对话 / 已知状态 / 合法计数 / 同一对话再次读取目标消失都成立时确认；其他情况不按回执乐观删除、不报成功、不自动重试，只读刷新保留服务的实际来源状态。新增测试覆盖HTTP200 false、缺字段、字符串true、未知状态、计数异常、错误/额外来源ID、已变化资料、跨endpoint/sid/token迟到回执，以及真实后端A撤回/B保留。上述结果已重新执行，旧47项/10项不作为此P2修改的新证据。


## 三方合并最终验证

合并后重新执行71项Core JUnit、34项真实Kotlin HTTP→当前隔离后端、22份Kotlin/KTS PSI及22项结构检查，当前日志覆盖合并后的源码，不拼接原作者36项、先前58项或沙箱失败日志。Core保留503→400稳定请求账本、撤回false/缺字段/未知/race并新增服务端气泡顺序/旧格式、recurring只读与禁止一次性误对账、stop能力门和精确回执规则。HTTP脚本在临时DB直接写入公开的合成assistant两段文字；不调用模型、CLI、TTS或读取用户数据库。日志记录被测Android脚本与server main/core/chat_delivery/api_contract/followups的SHA256，并在运行前后核对无变动。

分段停止使用新契约；旧服务缺 targeted-stop 能力时禁止发送，不能用事后回执校验代替事前能力门。前台轮询/服务地址草稿迁移/Compose按钮的真实设备行为仍属源码交付，未做Android平台运行验收。周期跟进在原生只读展示，完整编辑与调度需Web/服务端及后续设备验收。


### 最终记忆一致性追加

71项Core包含PendingTurn的记忆提议选项序列化/取消保留/旧记录false，按当次请求绑定原话offer、已确认literal回执、409仅生成本地review、手动候选不携带confirm/status及跨对话/陈旧文字拒绝。34项真实后端HTTP新增普通原话proposal409、没有自动存储、保留原话、显式第二次请求保存及读取仍为candidate。没有为验证调用聊天模型，偏好开关持久化与Compose操作仍属待平台运行验收。
