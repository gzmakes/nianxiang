# iOS R10 手动心情日记验收

交付为SwiftUI原生源码。没有安装Xcode / SDK，没有IPA、模拟器、签名或真机验收。以下宿主检查和实际HTTP不等于iOS App运行。

## 范围与边界

从并行快照仅提取Mood DTO / CRUD语义，新增独立 `Sources/EchoCore/Moods.swift`、`App/MoodStore.swift`、`App/MoodViews.swift`。APIClient只追加3个日记方法并修正query中加号的百分号编码；RootViews只插入能力准入的卡片和sheet，原R9被动待办仍用isReviewAvailable。没有覆盖R9 Models / EchoStore / ActionViews / BoundaryViews。

| 流程 | 实现 |
|---|---|
| 主动日记 | 日期、愉快/精力两轴、可选文字；初始0/0不等于已选择，两轴均由本人选定才可保存；图仅示意，滑杆可操作 |
| 本机草稿 | 按服务地址 / 对话 / 日期保存完整位置、已选标记、文字、已读版本与未决快照；切日、关闭或重建恢复；不是跨设备同步或独立加密保险箱 |
| CRUD与CAS | confirmed:true、精确expected_updated_at；保存严格匹配date/x/y/note及新ISO token；删除必须deleted:true。409保留草稿，GET最新并明确采用版本仅改本机状态，仍需本人另按保存 |
| unknown | 传输/解码/错回执保留不可变快照，禁止再次PUT/DELETE，只提供GET核对；新建unknown读空不证明未执行，仍锁定；删除unknown读空只说当前无记录，不补造删除回执 |
| 日期版本变化 | 原已存在的CAS版本被删除/替换时转明确冲突核对；不自动采用null或新token重试。版本按精确字符串比较，不自行生成token |
| 迟到隔离 | origin / session ID / generation / 请求序号 / mutation ID一起核对；旧成功、旧失败或后台前一次结果不覆盖新界面；回前台只读恢复 |
| 带到聊天 | 先展示内容，本人选择后核对当前来源范围，只追加原聊天草稿；不发chat、不给记忆或联系许可。只有本人再按发送才交给当前聊天模型 |
| 默认模型边界 | 日记默认不读聊天、不调用模型、不存长期记忆、不影响F5；不接规则建议、设备情绪识别、自动练习或主动弹问 |
| 共享 | 真实使用8个copy_mood_*生成常量，包含title/save/context/to_chat；R9偏好与F5共享资源保留 |

后端合同1.4.0，能力daily_mood_entries / mood_self_report_suggestions；本iOS只使用前者的手动CRUD，不给未实现建议入口。服务端以全DB严格递增ISO token防旧版本在删除重建后复用；**没有新增操作账本**，因此unknown空结果不当成未执行证明。

## 本轮证据

- `VALIDATION-ROUND10.log`：工程生成、plist / pbxproj、Swift语法、Foundation实际编译与 **54 / 54**合成契约（R9原49保留，加5项Mood契约）。XcodeTests源码同步了场景，但未接入scheme或运行XCTest。
- `HOST-ROUND10.log`：全App / Core在宿主macOS SwiftUI类型检查；R9实际EchoStore **30 / 30**组，新MoodStore **13 / 13**组。新增覆盖默认未知轴、日期/服务/对话草稿恢复、未知只GET、409保留/显式采用、false删除、同源同对话重绑generation、迟到失败与成功、存储失败零上传、明确422与带到聊天零请求。
- `HOST-LIVE-MOODS-ROUND10.log`：真正Swift URLSession → fresh临时DB/随机loopback，**21请求 / 4流程组**；cap1.4、手动创建/读取/编辑、旧PUT/DELETE409、删除重建不同token拒绝旧操作、清理后主对话/记忆/F5/跟进不变。无模型 / suggestion / contact claim / 账号 / 来源 / CLI / 通知 / 硬件。
- `HOST-LIVE-R9-REGRESSION-ROUND10.log`：R9原始18请求 / 4流程组在新1.4后端重跑；daily完整参数、暂停恢复、边界CAS、旧未来许可失效和created_due_at对账保留。不是手机或原生主动触达。

真实HTTP暴露过ISO token的wire编码问题：URLComponents默认保留 `+00:00` 中的字面加号，服务端query解析成空格导致正确版本DELETE冲突。现query中的字面+编码为%2B，保留精确CAS token；新增wire断言，真实删除和旧token拒绝均通过。失败尝试不当作通过证据。

## 仍待iOS设备验收

1. 完整Xcode/iOS SDK编译与UIKit分支、模拟器/签名安装、VoiceOver / 动态字体 / 键盘安全区。
2. 真机DatePicker/滑杆/长文、跨时区日期、文件和app生命周期；后台/杀进程恢复与网络断开/未知结果点按。
3. 多端真实CAS冲突、删除重建、草稿恢复、带入原聊天草稿后本人发送与真实模型表现。
4. 当前服务本机单用户，真机回环不指宿主；可达HTTPS / 身份配对和发布存储保护另验。没有新增账号授权。
5. 原生直接地图拖动、建议/多设备融合/心理练习/自动联系没有实现。MindLink专注度不作为心情结论。

打包排除.build（包含改前备份和临时测试数据）、DerivedData、xcuserdata、凭据、证书和DB。R10源码hash见ROUND10-SOURCE-MANIFEST.json；R9manifest / 日志仅为历史。
