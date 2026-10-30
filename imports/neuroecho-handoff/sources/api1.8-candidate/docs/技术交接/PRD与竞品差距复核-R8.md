# Round 8 产品／设计差距复核（只读）

结论：持续对话、受控来源、可纠正记忆已形成可继续打磨的底座；**不能据此说全产品或各端完成90%**。现在最需补的是「明确拒绝后真的不问」及一次真实陪伴闭环，原生安装／网络与硬件分别验收。

**阅读依据。** 已按交接入口读 `README-HANDOFF.md → HANDOFF.md`；读取原PRD HTML正文及其链接的《开发执行PRD》V0.2、design.md；核对Today规格包的《Soul还原》《MVP范围决策》。旧PRD的“场景未冻结”“首版不做四端”已经被其置顶更新及本次用户明确新增原生端的要求更新，不重新当作限制。Today的mock、契约和文案只说明可借鉴结构，其真实服务端人格提示词仍unknown；没有将逆向包内容当当前用户授权或现款实测。

## 当前能确认到哪层

| 主要求 | integration当前状态与边界 |
|---|---|
| 一条持续对话 | Web、Electron、两原生客户端均走canonical GET；话题仅视图，不创建第二会话。Android同ID/unknown/草稿已有Core与隔离HTTP验证；手机进程恢复仍待运行。 |
| 情感／chat-first | Web有首屏招呼、先听／梳理和飞书／Rokid等渐进入口；无必经欢迎弹窗。SOUL与服务端有倾听意图、已确认回应偏好、自然分段及精确停止。光／白卡／共享tokens已接入源码；自然、被理解的效果仍须真人使用验证。 |
| source／CLI | 选定文档／文件→真实预览→明确接入→逐份撤回路径存在。Notion/gh/Git、Mac日历提醒是后端适配，不能说手机系统已连接；能力目录也不是授权探测结果。仍遵守不新增账号授权。 |
| 记忆 | 候选与确认分开、来源／版本、编辑／忘记／历史、CAS冲突与未决草稿。两原生默认关闭提议、冻结发送选择；Android普通原话409只预填候选，不自动保存／confirm。跨端同库可重读，不是云同步。 |
| 主动陪伴 | 应用内一次跟进可创建／核对／完成／取消；Web另有daily/quiet/暂停，原生重复跟进只读。关闭期间无后台push。**这尚不等于PRD F5的完整分寸策略。** |
| Rokid／EEG | Rokid仍占位，符合用户“稍后联调”。MindLink只读、质量／时效校验适配源码存在，未把专注度解释为情绪；device_bridge明确synthetic。未验证队友真设备→有效帧→实体输出／ACK→停止。 |
| 多端交付 | iOS有SwiftUI工程、Foundation/宿主检查；Android有Compose工程，最终71项实际Core、34项Kotlin→隔离后端HTTP、22份PSI通过。用户暂不安装Xcode/Android SDK：没有IPA/APK、iOS/Android类型编译或真机验收；Electron复用Web，但安装／系统快捷键通知另验。 |

## 真正剩余的P1／P2

1. **P1：把“不问”做成确定策略。** 执行PRD F2/F5要求“今天先别问”、拒绝／静默优先、约定话题和窗口最多一次、离线不补发过期追问。当前 `core.py` 的quiet回应、`followups.py` 的due/paused/quiet、Electron暂停提示是分开的；Web `startReminder`重开按available显示到期项，没有统一topic/window/expiry/拒绝失效。应共享一条可见的拒绝／到期政策，先区分“历史待办仍可查看”与“重新主动追问”。验收：说别问→跨端重开→旧队列及迟到结果不再触达；换日／过期／撤源亦测。
2. **P1：验一次“纠正后，下次真的变”。** 选一份真实有界资料，说“先听，别给建议”→保存本人确认偏好→纠正→重开／换端→按新版本回应→撤回后不再引用。服务端已有受控策略与CAS；源码／合成测试不能代替真实模型、账号资料和人的感受。记录误解、纠正后再犯、拒绝成本与愿意再用，避免继续堆连接器。
3. **P1（手机交付）：安装与可达网络。** 完整SDK下编译、签名、模拟器／真机，验选择文件、键盘、取消／unknown、生命周期与200%字体／读屏。iPhone的127.0.0.1是手机本身；目前服务本机单用户、无远程用户鉴权、无实时多设备同步。需先明确USB/模拟器联调或另建受保护远程服务，不能只填HTTPS就称打通。
4. **P1（硬件展示条件）：真机闭环。** 队友设备可用后验证质量／时间戳、动作噪声、断流、本人停止与真实反馈；Rokid按到手型号验证一条真实显示链。暂时不纳入软件完成度，不用模拟ACK抵消未联调，也不扩成情绪解码。
5. **P2：自然回合与平台能力差异。** 原生发送仍受busy/pending锁，尚不具备与Web等价的连发合并体验；周期编辑、表情／语音、导出入口也未完全对齐。优先做能力矩阵和一致文案，缺能力明确说明；按design.md保留平台导航和材质差异，不强求像素相同。
6. **P2：经历时间／分寸可解释。** 已有原话时间与记下时间，事件有效期、临时状态失效、统一“别提这个”规则入口、为何使用某条记忆及“忍住未提醒”的记录还未形成完整产品。优先补最薄数据和详情，不先建设全人生图谱／关系积分。
7. **P2：商业化证据。** 当前没有可核验支付／订阅流程或付费试验；PRD也要求先验证再次使用、佩戴与付出真实成本。为商业化赛道准备一个明确人群／触发时刻、单次价值、真实使用分母、推理成本上限和访谈／试用反馈；不把聊天时长、设备连接数、喜欢或候补当付费。不擅自接支付。

## 本地依据索引

- [原PRD 0.4 HTML](</Users/yuntun/Documents/yuntun_karpathy/outputs/personal-agent-prd-20261027/index.html>)；[其链接的开发执行PRD V0.2 F1—F5/T1—T5](</Users/yuntun/Documents/yuntun_karpathy/outputs/personal-agent-dev-prd-20261028/开发执行PRD.md>)。
- [design.md：§1、7—11](</Users/yuntun/Downloads/design.md>)；[交接说明](</Users/yuntun/Downloads/xinji-echo-handoff-20261029/README-HANDOFF.md>)；[HANDOFF](</Users/yuntun/Downloads/xinji-echo-handoff-20261029/HANDOFF.md>)。
- [Today Soul：证据范围及记忆／主动结构](</Users/yuntun/Downloads/xinji-echo-handoff-20261029/reverse/today-spec-pack/05-reconstruction/soul.md>)；[Today MVP取舍](</Users/yuntun/Downloads/xinji-echo-handoff-20261029/reverse/today-spec-pack/05-reconstruction/mvp-scope.md>)。
- 源码核对：integration `server/api_contract.py`、`conversation_intent.py`、`core.py`、`followups.py`、`mindlink.py`、`device_bridge.py`；`web/index.html/app.js/followups.js`；`desktop/main.js`；两原生README及主界面／Store／ViewModel。Android新验证见本端 `ROUND8-MERGE.md/VERIFICATION.md`。本复核未联网、未读凭据、未重跑整产品／平台或硬件验收。
