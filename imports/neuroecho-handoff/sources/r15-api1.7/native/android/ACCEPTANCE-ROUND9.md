# Android 第九轮源码验收

本轮新增：每天／一次跟进、明确时区与安静时段、默认关闭的轻问许可、统一陪伴边界 CAS、完整飞书限长预览。原有 unknown 恢复、原始 request_id/payload、目标精确停止、记忆版本冲突、来源撤回保护保留。

- 实际 Kotlin 2.1.20 + Temurin 17 编译纯 Core：84 项 JUnit 通过。
- 实际 Kotlin EchoApi → 独立 FastAPI / 临时 SQLite：51 项 HTTP 检查通过，无模型或外部来源调用。
- Kotlin PSI：24 份 KT/KTS，0 语法错误；不解析 Android/Compose 类型。
- 工程结构检查：22 项通过；共享生成资源进入实际 UI/规则源码。

纯 Core 覆盖新旧草稿 wire 格式、每日 created_due_at 幂等核对、明确 occurrence 完成、暂停/恢复严格 Boolean 回执、时区显示、当前许可失效原因、今日静默 DST、边界 CAS 和旧聊天 payload 不变。HTTP 检查另覆盖跨版本边界409、每天创建/暂停/恢复/取消、重复领取、暂停后 recheck 拒绝、恢复不复活、晚 finish 冲突和原有 R8 路径。

原生端目前只创建、管理、展示跟进和许可，不自动发起轻问，不创建 OS 通知；其他支持的同服务客户端才可能按用户约定尝试提示。通知已提交也不等于用户看见。

用户明确暂不安装 Android SDK：没有 Compose 类型编译、lint、APK/AAB、模拟器、真机、TalkBack 或手机生命周期验收。所有 host 结果均不能代替这些门槛。

复现入口和依赖校验见 README。verification-jvm.log、verification-backend-http.log、verification-syntax.log 是本轮记录；ROUND8-MERGE.md 和 round8-change-manifest.json 仅保留历史。
