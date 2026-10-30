# 设备连接 API — R13 冻结合同

这是同一电脑、同一持续对话的受限设备入口，不是账号、云同步或手机系统资源连接。默认仅本机回环；远程 listener 不自动启动。所有本轮测试仅临时数据/合成 token/回环 TLS，不开启局域网、不读取现有密钥或授权。

## 本机明确授权（仅原本机 Origin guard 可达）

- `POST /api/paired-devices`：`{label:string(1..80),expires_in_seconds:int(300..2592000,默认86400),confirmed:true}`，201 返回 `{service_instance_id,conversation_id,scope:"personal_core",local_actions_allowed:false,device:{id,label,created_at,expires_at,revoked_at:null},token}`。Web 可固定7天604800秒。`token` 为 `echo_pair_` 加43位 base64url（32随机字节，总53字符），仅此次响应显示。SQLite只存 SHA256，GET/日志/导出不返 token/hash。丢创建回执不能找回 token：本机列表核对、撤销该设备、再明确创建；不自动重新创建。
- `GET /api/paired-devices`：`{service_instance_id,conversation_id,scope:"personal_core",local_actions_allowed:false,devices:[device...]}`；列表包括已撤销/过期元数据，不提供凭据恢复。
- `POST /api/paired-devices/{device_id}/revoke`：`{confirmed:true}` → `{service_instance_id,device_id,revoked:true,in_flight_may_have_committed:true}`，已撤销幂等200，未知ID404。新请求立即失效；晚到敏感响应在发送前复核。已提交的日记/记忆/回合不能谎称回滚；已显示或已在网络传输的内容不能保证收回。

`personal_core` 表示可访问该持续对话、记忆、手记、已接入资料，以及显式上传/撤回/跟进修改；不是单个 connector 的授权。本机展示明示范围后才生成。CLI、凭据、模型设置、系统动作、设备/脑电、owner管理全部禁止远程访问。本机 guard 本身不是同用户恶意本机进程的身份隔离，本轮不声称解决该威胁。

## 手机验证和请求头

`GET /api/paired-device`：必须 HTTPS 与 `Authorization: Bearer <token>`；初次验证可省略实例头。200 返回 `{service_instance_id:string,conversation_id:string,scope:"personal_core",local_actions_allowed:false,device:{id:string,label:string,created_at:ISO8601UTC,expires_at:ISO8601UTC非null,revoked_at:ISO|null}}`。时间为服务端 UTC、带 `+00:00` 的 ISO；字段当 opaque 值保留。

验证后其它远程请求必须带 `X-Echo-Service-Instance:<刚验证的实例ID>`；验证端点若提供该头也严格校验。客户端在 HTTPS、token、实例/设备/对话及凭据代次核对后才激活，将凭据由本端安全存储保存；不得按URL自动迁移旧 pending 或重写原始请求。绑定旧 canonical 被删除/更换时该凭据失效，不追随新对话。

| 状态 | error_code | 客户端语义 |
| --- | --- | --- |
| 401 | paired_authentication_required | 无效/过期/撤销/原canonical失效统一错误，停止使用该凭据，不自动重新授权 |
| 409 | service_instance_mismatch | 已认证但实例不符，保留草稿/unknown，明确重新核对 |
| 428 | service_instance_required | 后续请求缺实例头，不当写入成功 |
| 403 | paired_operation_forbidden | 路径/方法/范围/SID禁止，保留凭据，隐藏不支持入口 |
| 400 | paired_https_required / paired_invalid_request | 传输/请求无效，无HTTP回退 |
| 413 | paired_request_too_large | 有界上传拒绝，不自动重发 |

所有配对响应 no-store；不回显 Authorization/token。只允许 Authorization 传 token，不接受 URL、cookie、body 凭据。禁止跨源/重定向/伪造 Host 或 Forwarded。HTTPS 必须正常验证证书；若没有受信证书，需后续在原生端实现仅该 origin 的明确证书指纹配对，不能关闭全局 TLS 验证或安装全局信任来冒充安全连通。H5 自签证书信任另行解决，不属于本轮原生配对已完成。

## 远程白名单

允许 `(method,path)` 精确匹配：paired-device、受限 capabilities/sources目录、conversation与绑定SID详情、chat（必须request_id）/turn查询取消/当前message_id停止交付、memory CRUD/history/proposal（CAS不变）、moods与mood-operations（原精确字符串身份不变）、mood-suggestions、用户选择内容的preview-document/confirm、source/revoke、followups GET/POST/transition、companion-boundary GET/PUT。所有 body/query/path SID、memory/followup资源所有者都必须绑定发证时 canonical；文件确认缺SID不能进入旧版创建新会话支路。

远程 sources 目录仅返回手选上传，不调用现有 real_sources/CLI/账号探测。禁止所有 actions（包括real:false）、contactclaim/系统通知设置、auth/lark/notion/gmail/realread、模型设置/测试、debug/audit/export/download、硬件、session创建/删除、carryover、bookmark系统动作及未知路由。原始path含百分号、反斜线、重复slash或dot段均拒绝；新路由默认拒绝，不能依靠prefix放行。

## 单worker与发布边界

原 `main.py:88–117` Origin/Host guard 保留；只有 remote_app 在认证后设置的进程内 ASGI principal/sentinel 能进入远程白名单，不信任网络标记头。`runtime_lock.py` 和 `chat_turns.py:83–113` 要求单worker：新TLS入口共享同一进程的main业务，main lifespan/DB lease仅执行一次，不另起第二个main worker开同库。TLS入口 `proxy_headers=False`，只在用户显式配置证书/地址后启用；开发工具不自动开启非回环端口。

验收需覆盖：无配对无数据、同ID原payload账本、错实例/错SID/资源越权/别名路径拒绝、token错误不回显、撤销期间阻止晚到响应而不伪称撤回已提交、过期/重启、CLI/模型设置/硬件负向调用0、TLS实际回环访问及单lease、客户端安全存储/endpoint切换。TLS与配对不是实时同步：第一轮仍采用前台显式刷新，不做自动离线合并/后台推送。两原生SDK/真机仍须独立验收。

## R13 后端验证（临时数据）

- 配对/API、Origin、runtime 与 runner 共48项通过。runner 真实回环 HTTPS 使用临时证书、正常 CA/hostname 验证；未安装全局信任、未开启非回环端口。测试的 urllib 显式禁用继承代理，避免回环测试误经外部代理。
- 双监听均关闭自己的 lifespan，由外层 main lifespan 保持唯一 DB lease；延迟 TLS 请求排空前另进程不能取锁，所有 listener 退出后才能重新取锁。新数据目录0700，已有目录权限过宽则拒绝、不自动修改。
- 撤销在途请求后晚到响应被拒绝；已提交的合成记忆保留，回执不声称回滚。错实例/错对话/重复及编码路径、CLI/设置/硬件/系统动作均有负向覆盖。
- 本轮证明服务端临时回环 TLS 与边界行为；不代表 iOS/Android SDK、手机设备、局域网/公网、真实证书部署或实时同步完成。
