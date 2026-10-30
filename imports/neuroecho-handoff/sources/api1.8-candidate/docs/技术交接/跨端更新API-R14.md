# 跨端更新 API — R14 冻结合同

API `1.7.0`；能力 `features.conversation_change_cursor=true`。这是同一服务/同一持续对话的只读更新发现，不能当云同步、推送、离线合并或写入确认。不会自动 POST，不运行模型、CLI、账号或设备探测。远程受限配对入口同样允许此 GET，仍必须 Bearer/实例头并绑定原持续对话。

## GET /api/conversation/changes

可选 query `after=<opaque cursor>`。响应200、`Cache-Control:no-store`：

```json
{"service_instance_id":"svc_...","conversation_id":"ses_...","cursor":"URLsafeOpaque","reset_required":false,"domains":[],"reset_reason":null}
```

`domains` 只含以下稳定值，按此顺序返回：`conversation`, `messages`, `memories`, `sources`, `moods`, `followups`, `boundary`, `actions`, `turns`。它们表示需重读，不包含正文、删除前内容、来源内容、操作请求或秘密。客户端应保留未来未知域，不能把未知值当成功写入。`actions` 仍受本端能力/配对范围限制；远程客户端不能因此调用被禁止的动作 API。

- 首次无 `after`：`reset_required:true`, `reset_reason:"initial"`，全9域。
- 游标实例/对话/变更schema epoch不符：200、reset=true、`identity_changed`，全9域；客户端仍须核对已激活身份，不得静默重绑或迁移草稿。
- 超过保守4096 revision窗口：200、reset=true、`too_old`，全9域。
- 游标revision超前：200、reset=true、`ahead`，全9域。
- 畸形/重复/超过2048字符的 `after`：400 `error_code:"invalid_changes_cursor"`，不回显游标。
- 正常无新变化：reset=false、domains空，cursor与前值字节相同。其它旧SID变化不产生本持续对话的domains。

cursor为URL-safe ASCII `[A-Za-z0-9_-]+`，最多2048字符；必须按opaque字符串原样保存和回传，不解析、拼接或比较内部数值。重启同一DB不使游标自动失效；更换实例/对话/变更schema会要求重新读快照。服务启动期准备唯一持续对话，因此GET本身只读取既有状态，不初始化用户数据。直接无lifespan的开发调用若没有canonical会返回409 `conversation_not_initialized`。

## 一次读取如何提交

1. 在已确认服务/持续对话/凭据generation下，先GET changes（首次不带after）。
2. 记录这份响应cursor，再GET当前conversation及需要的memory/mood/followup/boundary等快照。所有需要的读取都成功、身份/generation未变化且本机编辑/unknown/上传/活跃回合未阻挡时，才把快照与**第一步cursor**一起采用。不能在读取后取一个更新的baseline cursor而不读它对应的数据。
3. 快照读取期间有新写入时，后续GET(after=第一步cursor)仍能发现。客户端可在提交前再GET(after=第一步cursor)复核；若非空/reset，则保留或提示并再次完整读取，不能直接推进到第二份cursor。
4. 离线/403/401/不兼容回执/页面编辑阻挡时保留原cursor与草稿，显式提示；未知写入账本仍按原恢复协议处理，GET更新不是写入成功凭据。

## 后端记录边界

SQLite触发器在原写事务内仅更新 `session_id/domain/revision` 失效向量，每对话最多9条，另有单行全DB单调时钟与随机schema epoch；不存事件正文/来源/秘密/请求payload，不维护无限事件历史。删除会话清理其向量，保留不含内容的全DB时钟，避免回拨复用。新旧数据无需回写内容；首次reset覆盖迁移前快照。

除真实事务变化，还对分段交付、跟进到期/静默/联系资格、边界到期计算只读派生状态指纹，避免只有时间经过却没有SQL写入时漏掉更新。指纹只用于失效，不能作为情绪、设备或医学推断。这个GET不驱动发送或完成任务。

## R14 后端证据与迁移夹具

新游标相关37项检查与旧迁移/记忆血缘/回复模式组合最终 **62项通过**；此前新游标初版加旧聊天取消、多来源撤回、配对TLS/Origin/runtime、心情/F5组合 **199项通过**。首次全Python回归（暂排并行shared gate）为765通过+37 subtests、3个旧schema模拟夹具失败：夹具在最新DB上直接DROP被新触发器引用的列。现已在临时夹具中先清除R14 tracker，再模拟旧schema，保留全部原用户数据断言；最终62项验证这3条旧迁移恢复。最终完整回归及客户端HTTP以根验收日志为准，不能把这些服务端测试当手机SDK/设备验收。

触发器清理只匹配本模块的字面 `cc_v1_` 前缀，不移除其它自定义trigger；复装、未来列迁移、回滚、读快照期间并发提交、旧游标/独立DB替换、删除会话清理、元数据有限保留均有临时DB测试。源清单只记录代码哈希；没有读取真实DB、密钥、授权或开启非回环监听。
