# iOS 三方整合记录 · 2026-10-30

仅整合隔离候选 `work/round8-integration-src/native/ios`，未写回 outputs 或原作者目录。

- base：`work/round8-integration-base/native/ios`
- ours：合并前 37 项 Foundation / 15 组 Store 候选。
- theirs：`work/round8-parallel-current/native/ios`
- ours 完整现场备份：`work/backup-before-round8/ios-three-way-ours`，不含 .build。
- 三方临时结果：`work/ios-three-way-merge`。6 个冲突文件逐处整合；Models / README 自动三方合并后语义审查。没有采用单侧全覆盖，也未机械复制日志。

## 保留与整合

| 位置 | 最终行为 |
|---|---|
| Models.swift | 保留 ours 的能力、CAS、未知状态及精确跟进回执核对；加入 bubbles / delivery_pending / delivery_next_ms 与周期字段。旧消息无字段仍兼容；用户原话不使用 bubbles 替代。 |
| EchoStore.swift | 保留 pending 原 ID / payload、前台只读恢复、来源守卫、followupSequence、首次明确拒绝草稿、未知状态不解锁；加入 conversationRevision 与交付 GET，晚 GET 不覆盖新快照。 |
| 草稿兼容 | 读取 `followup-draft.v1` 和并行版 `followup-rejected-draft.v1`。后续明确更新 / 清除时统一到主 key，防旧 key 使草稿复活；有未解决草稿时不切服务。 |
| RootViews.swift | 保留搜索、话题与原话候选回退；采用 Today scope / request 代次保护、前台 45 秒刷新和有序气泡。错误时保留上次结果并明确不是最新。 |
| ActionViews.swift | 保留能力准入与原草稿；显示 paused / quiet。daily 及未知重复类型只读，明确交由 Web 管理，不把每日完成错误转换为一次任务 done。 |
| 停止呈现 | 新增绑定 assistant ID 的 `POST /api/session/{sid}/delivery/stop`。仅能力 `chat_delivery_targeted_stop=true` 才请求；只有 `ok/stopped/message_id/reason` 匹配，且 GET 当前消息明确不再 pending 才显示已停止。false、格式错误、旧请求、读取失败均需核对，不自动重发。模型请求取消仍是另一条路径。 |
| 检查 | 合并双方场景并加气泡旧字段兼容、定向停止假成功拒绝、实际 Store GET 晚到、双 key 草稿兼容。XcodeTests 源码同步场景，仍未接入 app scheme。 |

`isAvailableNow` 同时要求 pending / due / 非暂停 / 非安静，并尊重 available=false；矛盾的 available=true 不会绕过暂停。原生没有周期任务创建、规则编辑、暂停 / 恢复 UI，不称各端此项齐平。

## 实际验证

- `sh native/ios/validate.sh`：生成工程、共享资源、plist / pbxproj、全部 Swift 语法、Foundation 编译及 **40 / 40 合成契约**通过。日志 `VALIDATION-round8-merge.log`。
- `sh native/ios/validate_host.sh`：全部 App / Core 在 **宿主 macOS SwiftUI SDK 类型检查**通过；实际 EchoStore **23 / 23 合成检查组**通过。日志 `HOST-ROUND8-MERGE.log`。
- 没有调用真实模型、账号、硬件或系统写入；没有安装 Xcode，没有 iOS SDK 编译 / 模拟器 / 签名 / 真机证据。
- 历史 `HOST-INTEGRATION-ROUND8.log` 只证明合并前的 CAS / 一次跟进宿主 URLSession 路径，不作为新功能证据。
- 新服务增量日志 `HOST-LIVE-INCREMENTAL-ROUND8.log`：真正宿主 Swift URLSession 解码 1.2.0 能力 / 主对话 / 一次跟进的重复元数据；缺 ID 与旧 ID stop 为 false、基线已有消息行不变；仅新建并取消自己前缀的一次跟进。没有 bubbles / daily / 活跃 pending 样本，明确 NOT_COVERED，不造样本、不调用模型，不能称该部分已真实联调。

请打包源码与最新说明 / 新日志，排除 .build、DerivedData、xcuserdata、凭据、证书、DB 与模型配置；旧日志如保留，按历史证据阅读。
