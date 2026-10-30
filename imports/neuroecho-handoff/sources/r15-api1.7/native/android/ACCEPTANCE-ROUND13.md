# Android 第13轮：设备连接与原身份恢复

交付源码为本目录；本轮只实现 Android 源码与可在无SDK环境运行的 Core / Host HTTP 验证。未访问用户真实设备、凭据或数据库。测试数据全部临时合成，TLS入口仅监听随机回环端口，结束即停止。

## 实际变化

- `Connection.kt`：规范化 HTTPS origin，精确校验 Bearer 格式、服务实例、唯一对话、设备、有效期和 personal_core 边界。每份数据按 origin + service_instance_id + conversation_id + device_id + credential-generation 分空间。原始请求标识、冻结正文和心情账本不改写。
- `Api.kt`：配对请求固定 Bearer 和 X-Echo-Service-Instance；首个配对验证可无实例头。请求与回执都检查捕获的连接代次；晚401不能清理新身份。禁止重定向，不覆盖证书/主机名验证；不向HTTP发送令牌。401清当前代次令牌，精确409 service_instance_mismatch只停用隔离，403/428或普通冲突不擦凭据。
- `DeviceVault`：AES-256-GCM随机IV，AAD绑定密文名称/空间；凭据、chat/memory/followup/mood草稿、话题及pending均加密。错误密钥、篡改、跨空间读取及存储失败均拒绝，无明文回退。密钥缺失且已有密文时不生成替代密钥覆盖内容。`AndroidCredentialVault.kt`为AndroidKeyStore/SharedPreferences薄适配；不声称硬件backing或设备实测。
- 换连接时旧token继续按精确scope加密封存，不自动使用。设置中本人点“恢复此身份”才读取原凭据，在线精确匹配同origin/实例/对话/设备后恢复旧generation；保留原unknown请求，仅GET核对，不自动POST。令牌已移除或401时才要求有效原码；失效后可到电脑查看原记录。
- “停止使用此设备令牌”清本机当前token、清私人RAM并保留隔离账本；不冒称撤销服务端许可。“移除此身份的本机资料”二次说明后只删除该scope的token、草稿、pending和descriptor；不取消已发操作、不删除电脑数据。当前活跃身份须先停止使用。
- `EchoViewModel.kt`：HTTPS验证及加密写入成功后才激活，验证失败保留原连接与草稿。恢复前重验设备与主对话；403不当撤销处理。失效时保留已有work锁直到旧操作结束，避免旧finally关闭新连接的busy状态。无法解码原pending时阻止新发送，不覆盖未知账本。取消请求捕获原client和epoch。
- `MainActivity.kt`：沿现有白卡/48dp控件增加连接状态、有效期、密码键盘/遮罩令牌框、验证/恢复/停止使用/单身份移除。实际引用共享 title/scope/verify/invalid。跨身份清理旧弹层；文件选择捕获身份且防重入，旧选择不进入新连接。配对模式隐藏电脑动作与CLI入口，仅安全目录、本人所选上传/撤回和被动跟进可用；任务页可查看跟进。
- manifest仍只有INTERNET权限。release禁止明文；debug HTTP只用于原USB/模拟器回环连接且不带token。原地址空间不自动迁移到新配对身份。补Android 11及以下备份规则、Android12+云/设备转移规则，显式排除SharedPreferences；没有开启备份或额外权限。

## 已运行的证据

| 范围 | 结果与日志 | 证据界限 |
|---|---|---|
| Temurin17 / Kotlin2.1.20编译纯Core与JUnit | 164项；`verification-jvm-ROUND13.log` | 保留R12 130项，新增34项身份/AEAD/隔离/保存失败/恢复/移除；fake vault/JCA key，不是AndroidKeyStore |
| 实际Kotlin → 原本机FastAPI/SQLite | 85项；`verification-backend-http-ROUND13.log` | 原F5/记忆/来源/心情账本回归；临时DB，无模型或CLI调用 |
| 实际Kotlin → 本轮真实配对HTTPS入口 | 30项；`verification-paired-backend-ROUND13.log` | 两个临时设备码、同一对话、原scope恢复与拒绝错设备、候选记忆/版本删除、心情ledger、被动跟进、403/428/409/401及撤销；非Android运行 |
| 合成HTTPS传输夹具 | 17项；`verification-pairing-transport-ROUND13.log` | Bearer/实例头、403保留、401/实例409、重定向不跟随、错主机名拒绝、旧代次发前拦截与晚401隔离 |
| Kotlin PSI、XML/结构、共享生成资源 | 37份Kotlin/KTS语法、24项结构及共享检查通过；对应 `verification-syntax-ROUND13.log` / `verification-static-ROUND13.log` / `verification-shared-ROUND13.log` | 仅语法/结构/资源一致性，不能代替Android/Compose类型解析 |

真实HTTPS测试用新建合成CA，**只该子JVM的临时trustStore信任**；生产代码没有测试SSL factory、信任全部证书或主机名绕过。实际配对后端测试使用一份临时DB、owner lifespan一次及remote lifespan off；没有第二个main worker或用户服务。原型的模型Key/CLI凭据从未传给手机。

复跑（已有JDK和经SHA校验的公开Maven缓存，不安装任何依赖）：

```sh
python3 scripts/test_rules_cached.py /absolute/jdk17 /absolute/maven-cache
python3 scripts/check_kotlin_cached.py /absolute/jdk17 /absolute/maven-cache
python3 scripts/verify_project.py
python3 scripts/sync_shared.py --check
python3 scripts/test_pairing_transport_cached.py /absolute/jdk17 /absolute/maven-cache
# 以下使用已有FastAPI/uvicorn Python环境，并在完整源码包内运行：
python scripts/test_backend_http_cached.py /absolute/jdk17 /absolute/maven-cache
python scripts/test_paired_backend_cached.py /absolute/jdk17 /absolute/maven-cache
```

## 平台验收仍未执行

**无Android SDK类型编译、Compose构建、lint、APK/AAB、模拟器、真机或实际Keystore操作。** JVM规则、JCA密钥与Host HTTPS均不能算Android平台验收。系统证书信任、Keystore失败/重装/厂商转移行为、硬件安全级别、持久写入性能、界面/键盘/200%字号/TalkBack、后台/旋转及离线朗读停止仍需开发同学真机验收。JDK URLConnection不支持PATCH，因此Host回归不冒充Android记忆PATCH执行。

这仍是同一成年人的多设备个人服务，不是多账号平台、端到端加密云同步、手机后台推送或任意电脑遥控。没有安装证书、开放LAN/公网、发起新账号授权，Rokid/EEG与录音ASR仍待设备条件。PRD第04节的“本人确认→下次正确续接”、第08节的身份/授权职责边界及第10节的unknown回执/隐私边界是本轮依据；不把源码进度表述为整产品完成比例。

## 官方依据（2026-10-30实际读取）

- [Android Keystore](https://developer.android.com/privacy-and-security/keystore)：应用专有非导出密钥；硬件支持依设备而异。
- [Cryptography](https://developer.android.com/privacy-and-security/cryptography)：推荐AES-256-GCM；本轮使用平台API，未引入已弃用的security-crypto封装。
- [Network security configuration](https://developer.android.com/privacy-and-security/security-config)：声明式明文流量边界与系统证书信任。
- [Auto Backup](https://developer.android.com/identity/data/autobackup)：Android12+部分厂商设备转移不单由allowBackup=false控制，因此增加明确规则。
- [KeyboardOptions](https://developer.android.com/reference/kotlin/androidx/compose/foundation/text/KeyboardOptions)：令牌输入请求密码布局且禁用自动纠正；键盘最终行为仍待平台验收。
