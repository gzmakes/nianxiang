# iOS 核心流程验收 · 2026-10-30

本轮交付 SwiftUI 原生源码。用户明确暂不安装 Xcode，本轮没有安装 Xcode / iOS SDK；没有 IPA、模拟器、签名或真机验收。“源码核心可用”与“手机安装可用”必须分别记录。

## 核心流程

| 流程 | 当前实现 |
|---|---|
| 唯一对话 / 导航 | 根 NavigationStack，首页连接详情有导航容器；各页继续用同一 canonical ID |
| 检索 | 搜当前已加载消息与未删除记忆；消息定位并取消话题筛选；记忆直接进详情；不上传搜索词 |
| 记忆 | 手动新增候选、确认 / 修改 / 版本 / 忘掉；消息长按确认原话选存；不符合服务端原话规则时预填为可编辑候选，再确认才新增 |
| 记忆提议 | 默认关闭；设置可打开；每次发送将该选项存入原 pending，重试不改变 payload |
| 草稿与恢复 | 普通聊天草稿按服务地址持久化；前台仅 GET 更新 / 核对 pending；忙时不并发恢复，不自动重发 |
| 话题视图 | 长按本机标记；全部 / 日常 / 自定义话题；仅筛选，不创建新对话或记忆 |
| 共享设计 | 实际引用生成 Swift 的色板 / 主导航 / 状态 / 默认偏好；系统减少动态与透明度优先；旧偏好保留 |
| 记忆并发 | PATCH JSON、DELETE query 携带 expected_version；409 保留编辑内容，读最新版本并显式再次核对，读失败不放开覆盖 |
| 资料 | 范围 → 实际内容预览 → 确认；只有标题 / 生成理解不可接入；事实、推测、问题分开；系统来源依服务端平台能力显示 |
| 分段回复 | 接收服务端 bubbles / delivery_pending / delivery_next_ms；前台 GET 依次展开，不再次调用模型；定向停止只针对当前 assistant ID，以真实回执和 GET 核对结果 |
| 周期关心兼容 | 识别重复、暂停、安静时段；原生对 daily / 未来重复类型只读并提示 Web 管理；不是原生周期 CRUD 完成 |
| 一次跟进 | 真实 GET / POST / PATCH；用户确认内容与时间；可见来源 / 状态、完成 / 取消；前台 45 秒刷新；只在打开时展示，不发系统通知 |

## 本次实际执行

- ./validate.sh：工程生成、plist / pbxproj 格式、Swift 语法、Core 实际编译和 **40 / 40 合成契约**通过，见最新 VALIDATION-round8-merge.log。
- sh validate_host.sh：**全部 App / Core 在宿主 macOS SwiftUI SDK 类型检查通过**，实际 EchoStore **23 / 23 宿主合成生命周期检查组**通过，见最新 HOST-ROUND8-MERGE.log。
- 新检查覆盖新旧 pending 兼容、提议快照、手动候选、原话明确确认、CAS 409 不重试、消息和记忆检索、本机话题、能力元数据、空预览不可接入、跟进稳定 ID / 错误回执 / 未知状态。
- 实际 Store 覆盖草稿重建、地址隔离、前台只读恢复、话题持久化、跟进丢回执后重建及内容 / 时间比对。首次明确 400 / 422 保留可编辑草稿；先前请求不确定后的再次 400 不释放原 ID。

合并分段 / 周期兼容前，另用真正 Foundation URLSession 对 root 新建的 127.0.0.1:18789 / round8-preview.db 完成 **3 组宿主 HTTP 冒烟**，见 HOST-INTEGRATION-ROUND8.log：

1. 只创建自己的合成记忆，v1 → v2；旧版 PATCH / DELETE 均 409，确认未覆盖，再以 v2 删除这一条。
2. 合成跟进同 request 重复保存返回同 ID，列表只一条；完成后再取消为 409。
3. 第二条合成跟进明确取消，真实回执为 cancelled。

以上不调用模型、CLI 或真实账号，不读真实用户 DB、文件、硬件。合成 HTTP 与宿主 Mac HTTP 都不代表 iOS App 运行。旧 HOST-API-SMOKE.log 仅是上一轮证据，不重复算为本轮新功能验收。最新 40 / 23 是本机合成验证，不补称真机。

### 新后端增量宿主 HTTP

root 重启隔离服务后，编译并运行实际 Core + `HostChecks/IncrementalSmoke.swift --isolated-synthetic-db`，由真正 Swift URLSession 请求 `127.0.0.1:18789`，见 `HOST-LIVE-INCREMENTAL-ROUND8.log`（同份原始日志 `work/round8-ios-live-incremental.log`）：

- 实际解码 contract 1.2.0、`chat_delivery_targeted_stop=true`、主对话，以及现有一次跟进的 repeat_rule / paused / quiet / available 元数据。
- no-body、空 JSON 缺 ID、随机旧 message_id 三种 stop 都返回 stopped:false。逐次只读导出核对，所有基线已有 message 行逐字段不变；未发送当前 assistant 的有效 stop，不中断 root 的回复。
- 只创建本代理前缀 `iOS-R8-LIVE-INC-EF281725…` 的一次跟进 `fup_ca1917066737`，真实取消后再次 GET 核对为 cancelled；没有修改其他记忆、来源或跟进。
- **NOT_COVERED**：当时 3 条 assistant 都无 bubbles，2 条既有跟进都不是 daily，因此真实 bubbles / daily 样本与活跃 pending 的有效定向停止未覆盖。按 root 指示不补造样本；这些仍只有上述合成契约 / Store 证据。

没有调用模型、CLI、账号、硬件或系统写入，也没有重启服务。该增量证明宿主 HTTP 与返回契约，仍不是 iOS App 编译、安装或设备网络验收。

## 交接与限制

普通草稿、本机话题、偏好、pending 聊天 / 跟进和明确被拒绝的跟进草稿存于 UserDefaults，没有独立加密保险箱，也不是跨设备同步。核对成功清除对应 pending。用户可在已有服务读取同一份数据；远程认证与即时同步仍未实现。

共享资源：根 shared/ → python3 sync_shared.py → App/SharedDesign.generated.swift。单端包保留生成副本；有根 shared/ 时 --check 可发现漂移。首次默认减少动态 false、降低透明度 false、光强 0.7，范围 0–1；不覆盖用户已保存设置，系统可访问性优先。

## 尚未验收

1. iOS SDK 构建、模拟器、真机、签名安装；XcodeTests 源码还未接入当前 App scheme。
2. 连接返回、搜索定位 / 记忆详情、消息长按、候选新增 / 确认、真实多设备 CAS 冲突点按。
3. 手机文件选择、安全作用域、确认前不上传、逐份撤回、VoiceOver、至少 +2 档动态字体、键盘安全区。
4. 后台 / 杀进程 / 网络断开恢复；前台实际等到时间、跟进取消和失败恢复。
5. 当前仅 Mac 回环服务。模拟器可指宿主，iPhone 回环是自身；手机远程使用需要可达 HTTPS 与身份认证，不可直接公开当前本机服务。
6. 没有后台提醒、系统通知、自动消息、手机日历写入；Rokid / EEG / 语音 / 分发材料另验。

打包保留 App、Sources、Checks、HostChecks、XcodeTests、共享 scheme、Package.swift、生成 / 同步 / 验证脚本、README、验收与日志。排除 .build、DerivedData、xcuserdata、凭据、证书、DB、模型配置和本机绝对路径配置。
