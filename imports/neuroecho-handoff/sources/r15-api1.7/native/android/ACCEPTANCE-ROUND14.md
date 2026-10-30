# Android R14：前台检查另一端的更新

## 实现与边界

这是同一服务、同一持续对话的**只读更新发现**，不是云同步、离线合并或后台推送。Android SDK、Compose 类型编译、APK、模拟器、真机和真实 Keystore 本轮仍未执行；原 R13 配对与 R12 显式离线朗读保留。

- `ChangeUpdates.kt` 是实际调用的纯 Kotlin coordinator。能力仅在 `conversation_change_cursor === true` 时开启；游标按 opaque 字节保留，不解析内部含义。严格验证服务实例、持续对话、Boolean、reset reason、唯一域和游标格式；未来未知域不当已支持，也不推进标记。
- 先 GET changes，暂存完整 conversation 与已支持的 moods / followups / boundary；本机开发连接另读 actions / next-step。配对手机不探测动作、CLI、通知设置或 contact claim。`turns` 失效重读 conversation；本机 unknown 继续原恢复协议。
- 再 GET `changes?after=C1`，只有同身份、无 reset、无变化域且字节仍等于 C1，才在一个 State 赋值里替换快照并提交 **C1**。读取期间再有变化时保留原标记，不直接采用 C2。删除与撤回替换完整列表；缺失、畸形、重复 ID 的列表不会被当作空列表清除。全新对话的合法 `context:null` 表示尚无资料。
- 前台每约 10 秒检查；失败退避 20 / 40 / 60 秒。单次 HTTP 连接/读取各 8 秒，整个协程使用 25 秒预算；阻塞 URLConnection 的取消仍须等 IO 收尾，**不是硬实时截止**。单 flight 保留到旧请求完全退出，暂停/后台立即使 attempt 失效；旧 callback / finally 不能发布进新身份或开启并发检查。
- 输入草稿、记忆/跟进/心情编辑、任何 pending/unknown、上传确认、文件选择、来源确认、活动聊天/分段回复、设置及操作弹层阻挡发布。只提示“有新内容”，不覆盖、迁移、合并或自动重发。用户完成/明确处理原编辑后可再次检查。
- 401 沿 R13 锁定原身份；实例冲突隔离，403 保留凭据。配对过期停止使用当前令牌。scope 包含实例/对话/设备/credential-generation 与本次 epoch；旧回应不会清新连接。游标仅存在当前模型内存，重启后完整初读。`identity_changed` 也可能由服务变更 schema epoch 引起；本端保守停用该轮自动检查，需本人核对并重新连接，不承诺同 ID 的所有 reset 都自动恢复。
- `MainActivity.kt` 移除旧 ON_RESUME 无条件全量重载及 45 秒跟进重载，改为生命周期驱动的统一 coordinator；原活动分段呈现专用轮询保留。沿既有雾蓝/白卡与 48dp 控件使用轻量更新栏，真实消费五个共享 sync 文案。旧服务显示不支持自动更新，并提供显式手动重读；不自动提交任何内容。

冻结 R13 候选是本轮的恢复基线，未覆盖原工程或其他端。具体 API 以完整交付包 `docs/技术交接/跨端更新API-R14.md` 为准。

## 验证记录

| 本轮实际验证 | 结果 | 界限 |
|---|---:|---|
| 纯 Kotlin Core / JUnit | 188项（原164 + 新24） | 实际 coordinator / transport 编译；无 Android 类型 |
| 双设备真实后端 HTTPS | 19项 | 临时 SQLite / 合成两个设备 / Host JVM |
| 原本机 HTTP 回归 | 85项 | 隔离 FastAPI / 无模型、CLI |
| 合成 TLS 传输回归 | 17项 | 正常证书/主机名校验 / 子 JVM 临时信任 |
| Kotlin PSI | 40份零语法错误 | 不解析 Compose / Android 类型 |
| XML/结构与共享字节 | 24项 + shared check | 结构性检查 |

最终实际计数与源码 SHA 由 `ROUND14-SOURCE-MANIFEST.json` 和以下独立日志记录；旧轮次日志仅代表各轮历史。

- `verification-jvm-ROUND14.log`：真实 Kotlin 2.1.20 / JDK17 Core 编译与 JUnit。coordinator 测试使用可控时钟/Deferred，不靠真实 sleep；覆盖游标、未来域、全部读取失败、先后两份变化、编辑与 unknown 阻挡、后台晚回包、单 flight、身份错配、退避、删除/撤回完整替换、空 context 和畸形列表。
- `verification-changes-backend-ROUND14.log`：实际生产 coordinator + EchoApi → 真 FastAPI 配对 HTTPS → 一份临时 SQLite；两个合成设备。验证另一端记忆增删、资料上传/撤回保留独立来源、心情 ledger、被动跟进、边界、暂存后再写入竞态、后台与撤销 401。所有写入明确来自合成第二客户端/测试 owner；coordinator 本身仅 GET。
- `verification-backend-http-ROUND14.log`：原 85 项本机 HTTP 回归；F5、记忆、来源撤回、心情账本与精确分段停止。
- `verification-pairing-transport-ROUND14.log`：原 17 项合成 TLS 传输回归，含证书/主机名验证、重定向拒绝、403 与 401/实例冲突区别、旧代次/晚响应隔离。
- `verification-syntax-ROUND14.log` 仅 Kotlin PSI；`verification-static-ROUND14.log` 仅结构/XML；`verification-shared-ROUND14.log` 仅共享字节一致。

测试仅复用已有 JDK / 经 SHA 校验的 Maven 缓存及 Python 环境；HTTPS 合成 CA 只加入测试子 JVM 的临时 trustStore。未安装 SDK、证书、账号、通知权限，未读取真实凭据或用户 DB、触发模型/CLI、开放 LAN/公网或修改其他端。**这些 Host/Core 证据不能代替 Android/Compose 构建、生命周期、UI、系统证书或设备验收。**

复跑（完整源码包内，使用既有依赖，禁止读真实数据库）：

```sh
python3 scripts/test_rules_cached.py /absolute/jdk17 /absolute/maven-cache
python3 scripts/check_kotlin_cached.py /absolute/jdk17 /absolute/maven-cache
python3 scripts/verify_project.py
python3 scripts/sync_shared.py --check
python3 scripts/test_pairing_transport_cached.py /absolute/jdk17 /absolute/maven-cache
PYTHONDONTWRITEBYTECODE=1 /existing/python scripts/test_backend_http_cached.py /absolute/jdk17 /absolute/maven-cache
PYTHONDONTWRITEBYTECODE=1 /existing/python scripts/test_changes_backend_cached.py /absolute/jdk17 /absolute/maven-cache
```

后续设备验收需检查：前后台/旋转/进程重启、200% 字号和 TalkBack、断网慢网、电量、真实输入与文件选择期间跨端删除/撤回、同设备凭据失效/恢复，以及 Android 平台 TLS 与 Keystore 行为。本轮没有将它们标为完成。
