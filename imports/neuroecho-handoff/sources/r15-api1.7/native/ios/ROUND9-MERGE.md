# iOS R9 分块合并记录

本轮唯一写入 `work/round9-integration-src/native/ios`；原始工程、R8 交付、parallel snapshot 均未覆盖。改前副本在 `work/backup-before-round9/ios`。

从 parallel-current 只合入两类有效语义：飞书实际完整有界预览与 length / extracted_length / truncated、daily 当前 occurrence 完成及暂停 / 恢复 / 取消。没有目录全覆盖；保留 R8 targeted stop、memory CAS、unknown 稳定请求、来源与晚回执保护、普通聊天草稿和单一对话。

随后按冻结的 1.3.0 F5 合同补完整原生周期 form / draft / pending、联系窗口同意和统一边界 CAS。旧 pending 的新增字段保持 nil，重试不补默认值。daily 已推进后匹配 created_due_at。被动待办使用 review_available；没有调用 contact claim，也没有原生自动弹出 / 系统通知。

共享 F5 文案由根 shared/product/copy.zh-CN.json 生成并 sync，界面实际引用生成常量。边界恢复与撤源文案明确旧许可失效，包括未来项，待办保留。

验证在当前整合源码重新执行：Foundation 49 / 49、实际 Store 30 / 30、宿主 macOS SwiftUI 类型检查、全新临时服务下实际 Swift URLSession 18 请求 / 4 流程。详见 ACCEPTANCE-ROUND9.md；无 iOS SDK / 真机验收，没有安装 Xcode。R8 证据保留为历史，不冒充 R9 或设备验收。
