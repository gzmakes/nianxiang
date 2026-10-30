# Android 开发交接 · Round 10

原生 Kotlin / Jetpack Compose 工程：`native/android/`。本轮按用户要求不安装 Android SDK；没有 APK/AAB，未完成 Compose/Android 类型编译、模拟器或真机验收。

先读 [第10轮多端交接](第10轮多端交接.md)、`native/android/README.md`、`native/android/VERIFICATION.md`、最新 verification 日志与 `SOUL.md`。JDK 17、SDK Platform 35 / Build Tools 35.0.0 等构建要求见本端 README；缺环境时 build.sh 如实显示 BUILD_NOT_RUN。

当前原生源码包括消息/记忆搜索与定位、手动候选记忆、话题视图、持久草稿和 CAS 冲突核对、条件只读 CLI 来源、前台刷新和共享资源。R9补完整 once / daily 跟进、时区 / 安静范围、每日当前 occurrence 完成、暂停 / 恢复 / 整项取消，以及飞书完整有界原文预览；未知重复规则只读。跟进 request ID 与 started 持久化，新请求冻结全部范围，旧 pending 不补新字段；daily 推进后按 created_due_at 对账。发生过 unknown 后，即便重试收到拒绝也保留原 ID，避免重复创建。

F5统一边界使用 companion-boundary 的 GET / PUT与expected_revision CAS；每条轻问默认false，明确选择话题与有效窗口。边界变化 / 拒绝 / 撤源会使旧许可（包括未来项）失效，恢复不补问，待办保留；实际回执与未知状态须严格核对。**当前Android只显示被动跟进和许可设置，不自动主动问、不调用contact claim、不发后台手机通知。**

R10新增真正Compose手动心情界面与MoodRules：日期 / 两轴 / 选填文字、历史记录、持久草稿、未决写入只读核对、CAS冲突保留并由本人明确采用已读版本。初始0/0不是已选择；保存回执和读取结果核对后才确认。日记默认独立于模型、长期记忆和F5联系；“带到聊天”只取本人已核对的记录并追加原聊天草稿，仍需本人另按发送。当前不接规则建议、心理练习、设备情绪识别或自动主动问。

当前R10证据：实际Kotlin Core/JVM编译与JUnit **94项**、真正Kotlin EchoApi→临时FastAPI/SQLite **67项Host HTTP**、官方Kotlin PSI **27份KT/KTS解析零语法错误**；另有22项静态工程结构检查。Core与HTTP见 `verification-jvm.log`、`verification-backend-http.log`，最终PSI与结构范围见 [本轮PSI日志](验证记录/round10-android-syntax.log)、[结构日志](验证记录/round10-android-structure.log)。较早84/51及24份解析是此前快照，不替代本轮结果。PSI不解析Android/Compose类型，结构检查不证明编译；这些均不是App运行、文件选择器、键盘或系统生命周期验收，HTTP也不证明真实账号、模型或硬件成功。

日记合同没有操作账本，unknown不能因为GET空就当作明确未执行，不能自动重发或换版本。CAS token为精确ISO字符串，冲突先读最新并明确决定，不能静默覆盖。
接手顺序：

1. 准备已接受许可的 SDK，运行 build.sh 完成 test/lint/assembleDebug。
2. 开发联调使用显式 adb reverse；手机回环不指向电脑，不伪造 Host 或关闭现有服务保护。
3. 验收稳定 request ID、unknown 不盲重发、停止、记忆 CAS、逐份撤回与回执、同 ID 动作确认。
4. 验收 200% 字号、TalkBack、键盘、安全区、后台/杀进程恢复，再产出首个可装 APK。
5. 验收跨时区选择 / 核对、daily当前次完成和取消整个周期、完整草稿 / pending恢复、边界CAS冲突与旧许可失效；许可不足的任务仍可被动查看。若后续新增原生主动呈现，需另做统一claim / recheck / finish与前后台去重，不能把当前许可开关当已投递。

6. 验收心情两轴未知、草稿存储失败、unknown只GET、已读版本冲突、删除重建与带入原聊天草稿；切换日期前先保存或明确放弃未提交草稿，不能把历史读取当已保存。

手机不保存模型 key；后端来源不是读取手机日历。语音、推送、Rokid/脑电和安全远程后端仍需独立实现与验证。不打包 local.properties、SDK、构建缓存、keystore、数据库或凭据。
