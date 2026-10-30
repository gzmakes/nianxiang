# R14 iOS：只读变更发现与安全前台刷新

这是 SwiftUI / Foundation 源码交付。没有安装 Xcode，没有 iOS SDK / UIKit 编译、模拟器、签名、IPA 或手机设备验收。下文宿主编译、假 Vault、临时 HTTPS 与生命周期函数检查都不能替代这些门槛。

## 当前真实路径

- `Sources/EchoCore/ConversationChanges.swift` 与 `APIClient.swift`：使用 API 1.7.0 的 `features.conversation_change_cursor`。`GET /api/conversation/changes?after=...` 仅收失效域与 opaque cursor，不接事件正文、不解码游标、不把它作为写入回执。按合同限制 URL-safe ASCII / 2048 字符，检查 reset / nullable reason / 身份；保留未来未知域，遇到不支持的域先保留原 cursor，不静默忽略后确认成功。
- `App/EchoStore.swift`：先 changes，再暂存 conversation 和需要的 followups / boundary / moods；仅电脑本机开发连接可以读取 actions / next-step。全部读取成功后，再用第一份 cursor 做一次只读稳定性复核。第二份必须同实例 / 主对话、非 reset、domains 空、cursor 字节相同；否则本次不发布、不推进，等待下一轮完整读取。只提交第一份 cursor，不用更晚的 baseline 跳过未读内容。
- 提交前再次检查 immutable client、原连接 generation、canonical、编辑租约及本地读取屏障。所有快照在一次 MainActor 无 await 区间替换；消息删除、记忆删除、来源撤回和心情删除不会用 append 留下旧条目。缺失 / 畸形列表不当作合法空值；conversation 的显式 `context:null` 合法，缺失 context 或缺失 sources 不会被当作撤回。
- 初次/重启/切身份都从无 cursor 开始，先 changes 再读全部需要的域。R13 连接验证中的 conversation GET 只用于核对唯一对话，**不建立 cursor 基线**。本轮 cursor 只在 RAM，不写 UserDefaults、不跨实例 / 设备 / credential-generation 迁移；原始 unknown ID / body 继续原恢复协议。
- 正常前台约每 15 秒检查一次，读取错误退避到 30 / 60 秒；只有完整成功才清连续失败计数。单飞；取消先使票据无效，旧请求完成前不释放其飞行槽。退后台取消监测 task，不继续开始后续域读取；前台恢复沿原 cursor 检查。单个 URLSession 请求仍沿用原 45 秒超时，批次不承诺实时完成。
- 编辑/普通聊天草稿/发送或 unknown/分段仍在呈现/跟进未决时，能发现 metadata，但不替换内容或推进 cursor。`ChangeRefreshViews.swift` 为记忆、心情、来源读取/上传确认、跟进、边界、设备设置、话题/确认弹层登记保护租约。开始编辑、独立读取或本地状态变化会作废正在暂存的批次；“检查更新”不会强制覆盖草稿。
- 心情页采用保守策略：打开整页即保护当前编辑；出现更新先提示，关闭后再安全检查。当前页仍可本人点原有“只读刷新并核对”，其草稿/CAS/unknown 规则不变。刷新协调器不会把远端日记自动写入正在编辑的 MoodStore 草稿。
- 首页/设置/编辑页实际使用共享 `connection.sync.check/pending/updated/offline/unsupported` 文案。首页和跟进列表采用已提交的完整数组，并使更早的独立列表 GET 无效。全量更新时停止原有朗读，不自动播放新内容。原生弹层及真实前后台事件仍须设备验证。
- 401 / 实例409 / 403 沿用 R13：精确401清对应凭据与私密 RAM；实例409仅停用并保留原身份凭据；403/断网不当撤销。wrong metadata 身份不能悄悄重绑。旧回调不能清新身份或继承旧 cursor。无能力键服务不发 changes 请求，保留原有显式刷新。

所有自动更新均为 GET。没有自动发送、重试写入、cancel、确认记忆、日记保存、followup claim、系统通知或模型调用。当前仍是同一后端的前台只读发现，不能称实时云同步、推送或离线合并。

## 本轮证据

- `VALIDATION-ROUND14.log`：工程生成、plist / pbxproj、Swift parse、Foundation **78/78**；在 R13 70 项上增加 8 组 cursor/DTO/单飞/取消/失败退避/身份/集合形状检查。`XcodeTests` 同步源码并只作语法检查，不称已执行 XCTest。
- `HOST-ROUND14.log`：完整 App / Core 的 **macOS** 类型检查；R13 原 EchoStore **30**、MoodStore **13**、MoodLedgerStore **17**、SpeechController **9**、设备连接 **18** 组仍通过；新增实际 EchoStore 变更刷新 **18** 组。全为 URLProtocol / fake vault / fake speech driver，不运行 iOS SDK、真实 Keychain 或声音输出。
- `HOST-CHANGES-ROUND14.log`：上述新 18 组独立日志。覆盖 baseline 顺序、空更新只 GET metadata、删除/撤源替换、域失败原子保留、编辑/普通草稿/unknown 阻塞、读途中开始编辑、二次复核发现写入、空域不同 cursor 不跳读、未知域/缺失列表、后台作废/单飞、同 canonical 新 device/generation、wrong instance、401 与旧服务 fallback。监测周期/退避的状态机与 Store 路径已测；没有把手动调用生命周期函数当 iOS 事件实测。
- `HOST-CHANGES-HTTPS-ROUND14.log`：两个真实 macOS URLSession / EchoStore 客户端 → 最终 API1.7.0 的临时 paired TLS runner，**10 流程组**。同一 canonical、不同 device/generation；对端记忆新增/修改/删除、本人所选内容确认/撤回、心情 ledger 保存/删除、被动跟进取消、边界暂停恢复；编辑/unknown 保留、后台停止与前台读取、读快照后对端写入能被复核发现、精确401清理。正常业务读写与后台 API 是真实 HTTP；读途中编辑竞态的自动协调器验证在合成 Store 组中，不冒称所有真实 UI 竞态已在设备上复现。
- 实际 HTTPS 使用新建临时 DB / 两份合成设备令牌 / 临时独立 CA；只有测试注入的 session 将该 CA 作为唯一 anchor，同时执行 `SecTrustEvaluateWithError` 与 SSL hostname 校验。没有改产品默认 trust、安装全局证书或访问真实钥匙串。后端 seal 的 **44 文件 hash 前后核对不变**，具体 seal hash 记在日志和本端 manifest；测试服务及 DB / cert / key 均已停止/删除。没有 DeepSeek、chat POST、账号、CLI、硬件或联系 claim。
- `HOST-R13-PAIRED-REGRESSION-ROUND14.log`：R13 真正 URLSession HTTPS **10 流程**在 R14 上回归，仍有默认产品信任拒绝未安装 CA、302/307/308 不跟随、目标 TLS listener **0 请求/0 凭据**、CAS/ledger/来源操作和撤销401。旧 helper 为新前台入口明确注入 `automaticChangePolling:false` 并激活前台标记，未放宽 TLS / 身份策略。

复跑：`sh validate.sh`、`sh validate_host.sh`；真实 API 使用已有 FastAPI/uvicorn Python 环境运行 `HostChecks/run_round14_changes_smoke.py`。`HostChecks/run_round13_paired_smoke.py` 为保留的传输回归。脚本只创建自己拥有的临时数据，不启动/修改用户预览服务，不安装 SDK / 依赖 / 证书。

R9–R13 历史日志仍保留为历史：本轮没有重跑 DeepSeek 对话体验、R12 WAV 或所有旧 HTTP 流程。不得用日志总数推算产品完成率。

## 设备接手清单

1. Xcode/iOS17+ SDK 类型编译、签名/IPA/安装、UIKit、Keychain entitlement/锁屏；按用户决定本轮暂不安装 Xcode。
2. 真机前台/后台/锁屏/杀进程、断网/慢网/取消、15秒轮询与30/60秒退避、电量/流量、两个实体客户端操作及旧回执；验证没有后台自动请求或循环重发。
3. 每种 sheet / navigation / file picker / 记忆原话确认 / 心情页的保护租约生命周期、关闭后更新、键盘/读屏/动态字号；宿主 SwiftUI 编译不证明这些交互。
4. 实际手机可达且被系统信任的 HTTPS、owner 许可/收回、实例变化及只恢复原身份；本轮仍不开放 LAN/公网，不自动部署证书或隧道。
5. 真实已授权模型的对话/分段/取消体验，以及朗读声音/音频中断；R14 本轮未调用模型或播放真实声音。自动只读刷新不是通知或原生主动陪伴投递。

## 存储与交付

R13 设备令牌仍走 Keychain 适配器；普通本机草稿、话题、pending 仍为应用 UserDefaults，不是独立加密保险箱。cursor 无持久化，只在原身份当前内存持有；存储/unknown/cancel 规则未被替换。本人明确恢复旧身份仍需验证，不会为了同步给原请求重编号。

只更新本轮独立 `native/ios`；冻结 R13 与其他作者源码未覆盖。打包排除 `.build/`、DerivedData、xcuserdata、DB、TLS材料、凭据和模型配置。`ROUND14-SOURCE-MANIFEST.json` 排除自身，历史 manifests 不表示当前源码仍与历史轮次相同。
