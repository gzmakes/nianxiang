# iOS 开发交接 · Round 10

原生 SwiftUI 工程：`native/ios/Echo.xcodeproj`。本轮继续开发源码，按用户要求不安装 Xcode；没有 IPA 或 iOS SDK / 模拟器 / 真机验收保证。

先读 [第10轮多端交接](第10轮多端交接.md)、`native/ios/README.md`、`native/ios/ACCEPTANCE-ROUND10.md` 与 `SOUL.md`。后端单独运行；手机不保存模型 key。模拟器与真机的回环语义不同，当前后端不对局域网/公网开放。

当前原生源码包括导航容器、消息/记忆搜索与定位、手动候选记忆、原话入口、话题视图、普通草稿持久化、记忆 CAS 冲突保留、前台核对和共享资源。R9补完整 once / daily 跟进表单、所选时区 / 安静范围、完成当前 occurrence、暂停 / 恢复 / 整项取消，以及完整飞书有界原文预览。首次明确拒绝和先前 unknown 分开处理；旧 pending 不补新字段，daily 推进后按 created_due_at 对账，未知结果不换 ID 盲重发。

F5统一边界使用 companion-boundary 的 GET / PUT 与 expected_revision CAS；今天安静、暂停、恢复都约束共用服务。每项 allow_contact 默认false，明确确认话题与5–180分钟窗口。边界变化 / 拒绝 / 撤源使全部旧许可失效（包括未来项），待办保留，恢复不复活旧许可。界面实际使用共享生成文案。**当前iOS只显示被动跟进和许可设置，不自动主动问、不调用contact claim、不发系统通知。**

R10新增独立手动心情日记：按日期选择感受 / 精力两轴与选填文字，初始0/0仍未选择；持久草稿、不可变unknown快照、CRUD/CAS409保留草稿并显式采用最新版本，旧origin / sid / generation回应不能覆盖新状态。日记默认不被模型读取，不成为长期记忆，不触发联系；“带到聊天，由我发送”先展示选定内容，只追加原聊天草稿，本人另按发送后才进入当前聊天模型。原生当前用滑杆选位置，没有直接拖动画布、规则建议、心理练习或设备情绪识别。

当前R10证据：Foundation **54/54**（含保留R9原49项）、原EchoStore宿主 **30/30**、独立MoodStore **13/13**，全App/Core宿主macOS SwiftUI类型检查；真正URLSession→新建临时FastAPI/SQLite完成 **21请求 / 4组Mood流程**，另 **18请求 / 4组R9 daily/F5回归**。新证据分别见 `VALIDATION-ROUND10.log`、`HOST-ROUND10.log`、`HOST-LIVE-MOODS-ROUND10.log`、`HOST-LIVE-R9-REGRESSION-ROUND10.log`；hash与边界见 `ACCEPTANCE-ROUND10.md`、`ROUND10-SOURCE-MANIFEST.json`。这些数量不累加成完成率，均不是iOS SDK、UIKit或手机体验验收；HTTP冒烟不调用真实模型、账号、通知或硬件。

日记合同没有操作账本：新建unknown后GET为空，不能证明未执行，仍只读核对不重发；删除unknown读空只证明当前无记录。ISO版本token按原值传递，URL query中的+须编码为%2B，不能重算或自动换版本。
接手顺序：

1. 完成 iOS SDK 编译、模拟器与真机安装，加入 XCTest target。
2. 验收文件选择、连接详情、中文长文、大字号、VoiceOver、键盘、安全区和前后台/杀进程恢复。
3. 验收消息 unknown/停止、记忆旧版本冲突、来源逐份撤回、动作同 ID 且 real:false。
4. 手机远程使用需要身份/配对与安全后端；手机日历、语音、推送、Rokid/脑电另接 adapter。
5. 验收跨时区显示 / 保存范围、每日当前次完成与整项取消、完整草稿 / pending恢复、边界409与旧许可失效；没有联系资格的任务仍可被动查看。若将来实现原生主动呈现，需另验claim → recheck → 呈现 → finish和前后台去重，不能把当前同意开关当已通知。

6. 在设备上验收心情两轴未知、跨日草稿、unknown只GET、409查看最新后明确采用、删除重建与带入原聊天草稿；日记删除不删除本人已发送到聊天的文字。

共享文案/色板经 `scripts/sync_clients.py` 更新；行为和布局仍需平台负责人同步。已有用户偏好不覆盖。账号、CLI、Mac 日历权限和读取成功是独立验收项。
