# Android Round 8 三方合并记录

本记录只涉及 `integration-src/native/android`。权威输出目录、原作者源目录、server、iOS与共享根目录均未写入。合并前ours保存在本端 `rules-jvm/build/threeway/ours-before`，输入清单与冲突中间件在同级 `threeway/`；这些是工作中间件，不打入交付代码包。

## 输入与逐项决议

- base：`work/round8-integration-base/native/android`，共同基线。
- ours：合并前integration版本，58项Core / 19项实际HTTP阶段，含started/unknown持久账本与严格来源撤回。
- theirs：`work/round8-parallel-current/native/android`只读快照。保留其Api分段字段、分段测试、普通草稿的endpoint隔离、前台GET轮询及repeat/paused/quiet展示。

| 文件 | 合并方式与保留内容 |
|---|---|
| Api.kt、ApiMetadataTest.kt | theirs单边新增分段字段/顺序/旧格式回退；ours已有来源与时间元数据均保留 |
| MainActivity.kt | git merge-file清洁三方合并，保留双方UI；再增加精确停止入口，仅当前最新assistant且能力flag为true时可用 |
| EchoViewModel.kt | 手工解两个冲突：sourceRevokeToken与endpoint草稿迁移init并存；跟进失败取更严格的persisted started与已知错误码逻辑，保留theirs分段GET和重复跟进只读guard |
| FollowupRules.kt | recurring字段/状态文案并入，保留stable UUID、started迁移、body与encode分离和POST transition；一次性对账额外要求repeat_rule=once，重复类型禁止一次性转换 |
| FollowupRulesTest.kt | 清洁三方合并保留两边测试；追加重复记录不得解除一次性未决账本或走一次性操作 |
| Rules.kt、RulesTest.kt | 在双方稳定PendingTurn上追加memory_proposals快照与序列化；旧未决记录缺字段默认false，取消保持相同选项和请求ID |
| ProductRules.kt、ProductRulesTest.kt | 保留ours CAS、话题、连接与真实状态文案；追加targeted-stop能力门、当前assistant绑定和严格true回执/GET规则 |
| SourceRevocationRules/Test、ApiContractTest、HTTP工具等ours单边文件 | 全部保留；真实回执/race和503→400测试继续执行 |
| README/验证日志 | 手工更新当前能力与边界；日志重新生成，没有合并历史数字 |

没有原作者新增Kotlin文件被遗漏；其新增日志不冒充本次结果。原作者README称重复DST时间也拒绝，但源码仅拒绝不存在时间，记录已纠正，未在本轮扩大行为。完整路径/变更hash见本端manifest。

## 语义和兼容性

持续关心：原生可显示daily/未知重复类型及paused/quiet状态，操作提示去Web；未实现原生周期创建、暂停恢复或安静时段编辑。缺新增字段默认旧的一次性行为。不将new字段显示、纯规则验证或服务端响应当作Android周期调度验收。

未知账本：只有从未发送的新请求第一次明确400/422已知拒绝才释放ID；已started/unknown后任何拒绝保留原ID和payload。原作者的HTTP类别helper保留为纯分类，不决定生产账本退休。成功后列表刷新失败不复活未知账本。

来源：精确endpoint/sid/token/source快照；严格ok Boolean true/单来源ID/已知state/合法计数，且GET同一对话确认目标消失才报成功。false、缺字段、迟到或刷新失败没有乐观删除和自动POST重试。另份来源与输入草稿保留。

停止：模型cancel和分段delivery stop为独立动作。只有新能力 `chat_delivery_targeted_stop=true` 才POST `/api/session/{sid}/delivery/stop`，body必须为当前assistant.id；旧同名路由不试探。false/unknown仅GET，true还需精确message_id、reason=stopped及同对话读取确认；新回复在场时不宣称旧请求停止了当前回复。

## 本次重新验证与未验证

- 71项Core实际Kotlin编译JUnit通过（含真实loopback HTTP fixture），`verification-jvm.log`附源hash。
- 34项实际Kotlin EchoApi→隔离FastAPI/临时SQLite通过，`verification-backend-http.log`附本次客户端/后端源hash。含跟进幂等/409、精确来源撤回A保留B，以及无ID/旧ID不能停止最新分段、准确停止/重复false。无模型/CLI/TTS/账号调用。
- 22份KT/KTS官方Kotlin PSI解析0错误；22项结构/权限/路由检查；共享生成资源一致。
- 用户明确暂不安装Android SDK；没有运行Android/Compose类型编译、lint、APK/AAB、模拟器、真机、TalkBack、200%字号或手机生命周期验收。JDK Host不支持PATCH，因此记忆HTTP409用POST fixture只验证body/decoder，不能冒充Android PATCH执行。

命令在README/VERIFICATION中；先运行 `scripts/test_rules_cached.py`，再以含FastAPI的既有Python运行 `scripts/test_backend_http_cached.py`。根整合后若server再次变化，必须重新运行实际HTTP脚本，旧server hash不能代替新版本验证。


## 最终记忆一致性收口

新增设备持久偏好开关（默认false）；发送把当时选择冻结到PendingTurn，本次的核对/恢复不会因后来切换开关而改body。自动原话提议只展示与本次user_message_id、文字匹配的literal，并等待明确选择。普通原话proposal409后只显示手动review，点「整理为候选记忆」才预填MemoryDraft，已有草稿保留；再显式保存才创建candidate，不能自动confirm或绕过白名单。记忆提议回执严格检查confirmed/fact/原话source/源消息ID/literal才说已记下。

本追加后所有受影响Core和真实HTTP已重新执行，最终为71 / 34；不是合并前65 / 28或58 / 19的数字。其余SDK与硬件边界不变。
