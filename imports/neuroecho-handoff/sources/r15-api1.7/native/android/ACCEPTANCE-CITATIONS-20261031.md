# Android 文档引用兼容补丁 · 2026-10-31

当前补丁在完整、可见的 assistant 回复下展示飞书文档标题按钮，点击交给系统 ACTION_VIEW。仅补消息引用；飞书连接和文档权限仍在电脑端管理，不新增手机账户授权、CLI、正文读取或记忆编辑入口。

| 边界 | 当前行为 |
|---|---|
| JSON 逐项容错 | `citations` 缺失、null、非数组兼容；未知 kind、坏类型、不完整引用和坏 URL 单项跳过，保留回复及其他有效引用。文档须精确 `kind=feishu_document`，title/url/text 为实际字符串；text 可空，title 非空且最多 500 Unicode code points。 |
| 旧格式兼容 | 旧记忆引用仅在 kind 键缺失、id 非空、version 为实际正整数、text 为字符串时保留 DTO；本补丁不展示或编辑旧记忆引用。现有 Message 构造保留默认空引用列表。 |
| 展示范围 | 仅完整、delivery flag 类型有效、可见正文非空的 assistant 消息展示文档；user/system、待展开、无效 delivery flag、空白正文和话题隐藏消息不展示。标题最多两行，触控区域至少 48dp。 |
| URL | 只允许 HTTPS 官方 feishu.cn／larksuite.com 及合法 DNS 子域、默认端口或精确 `:443`、`/docx|docs|wiki/<token>` 可尾斜杠。拒绝 userinfo、原始空白/控制/反斜杠、编码控制/反斜杠、编码 authority/path、dot segments、非法 DNS label、非默认端口和 UTF-8 超过 4096 字节；普通 query/fragment 编码与中文可保留。 |
| 点击重核 | 根据最新 endpoint、scope+连接 epoch、session、message、话题可见性、可见正文、完整状态和精确文档再核；后台、切连接或消息/引用变化时拒绝旧按钮。失败显示明确提示，不假称已打开。 |
| 系统打开 | 只在显式点击后调用系统 ACTION_VIEW+BROWSABLE；不调用 EchoApi，不附设备 Bearer，不自动读取正文，不自动授权。系统调用异常显示失败说明。 |

验证使用本机已校验缓存的 Kotlin 2.1.20、Temurin JDK 17.0.21+9、org.json 20240303 和 JUnit 4.13.2，无下载、安装、账户授权或服务启动：

- 实际 Core/parser 编译和 JUnit：**213/213**，其中新增 CitationRulesTest **15 项**。覆盖新旧 payload、逐项坏引用、URL 白名单与混淆、完整可见消息、身份/正文/文档变化后的点击守卫。不是 Android UI 测试。
- 官方 Kotlin compiler PSI：**44 份 KT/KTS，0 语法错误**。首次因缺 helper 受阻的日志和隔离副本检查保留为历史记录；现已将实际使用过、SHA256 `71c4b18e2b51e0d927e21266e9bfa7f0a6950d6b00b502a404f2ce448a3dd4e4` 的本机既存37行 `KotlinSyntaxCheck.java` 补齐到活跃 `scripts/`，检查文件原先不存在并以独占创建写入，没有覆盖已有文件。随后**直接调用活跃源码的 `scripts/check_kotlin_cached.py`**，再次得到44份、0语法错误；未重跑其他无变更测试。
- 当前 KT/KTS 与隔离验证副本逐文件哈希一致；`git diff --check` 通过。补丁所涉文件见 `CITATIONS-20261031-SOURCE-MANIFEST.json`，不修改历史 R15 封板 manifest。

日志位于工作区 `work/android-feishu-citations-20261031/verification-core.log`、`verification-syntax.log`；完整 Core 源码哈希在 `validation/verification-jvm.log`。首次 PSI 因缺历史 helper 失败的日志独立保留为 `verification-syntax-first-helper-missing.log`。

活跃源码复跑日志另见 `CITATIONS-SYNTAX-ACTIVE-20261031.log`，输出只在仓库忽略的 `rules-jvm/build/syntax` 缓存内，不修改既有历史日志或全局目录。后续接手可在 native/android 目录直接运行：

```sh
python3 -B scripts/check_kotlin_cached.py /absolute/jdk17/home /absolute/verified/maven/cache
```

该脚本先核对 `scripts/jvm-dependencies.sha256.json` 中的现存公共 JAR，不下载或安装依赖；helper 是语法解析器，不解析 Android/Compose 类型。

未执行 Android SDK/Compose 类型编译、Gradle APK 构建、模拟器、真机或实际外链打开验收；未生成 APK。上述结果不能证明实际账号权限、手机浏览器处理、飞书 App 路由或跨设备接通。
