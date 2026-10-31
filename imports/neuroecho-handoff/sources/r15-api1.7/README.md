# 回响 · 第15轮多端开发交付

版本 `2026.10.30-round15-integrated`，API **1.7.0**。先读 `docs/技术交接/第15轮多端交接.md`、`多端同步与架构方案.md`；变更协议见 `跨端更新API-R14.md`。R13设备连接合同继续有效。早期轮次的日志是历史证据；源码、包体、平台运行和真实使用效果分别验收。

## 本轮解决的问题

桌面版增加明确的「连接与空间」选择：本人填写已经运行的本机地址，先只读核对服务和持续对话，再明确确认，才切换到该服务。数据和模型留在原后端；不同服务/身份的窗口、草稿和待核对请求不混用。断线或身份变化不会悄悄建立一个新空空间。共享服务不获得桌面文件、通知、状态或快捷条权限，也不会在退出时被桌面停止。

H5更新栏出现在记忆/设置等实际弹层内。记忆页可明确点「检查更新」核对完整列表，保留聊天草稿；编辑、确认、unknown和其它表单仍阻挡替换。记忆正文使用实底避免底页透字。iOS/Android弹层也有可见反馈，离线或失效连接的本机文字按各端明确范围提供只读查看/复制，不能迁移或重发请求。iOS能力清单临时失败后可显式GET重新核对，不误称服务不支持。

R14同一后端的metadata-only变更游标、稳定快照采用、来源撤回、记忆CAS和请求账本继续保留。没有新增欢迎弹窗、账号、后台推送或自动离线合并；原生仍是源码交付，没有SDK/IPA/APK或真机验证。

## 交付和运行边界

| 端 | 本轮交付 | 未证明的部分 |
|---|---|---|
| Web/H5 | 弹层内更新、记忆页明确核对、编辑保护和单一持续对话 | 真手机浏览器、线上部署、完整无障碍验收 |
| macOS arm64 | 自包含Electron/Python App，窗口和组装证据分别记录 | Developer ID/公证、其他Mac、Intel |
| Windows x64 | 离线便携包、源/依赖/许可证核对 | EXE实际运行 |
| iOS | SwiftUI工程、原生连接与更新协调器、实际URLSession临时HTTPS | Xcode/iOS SDK、IPA、真机/Keychain |
| Android | Compose工程、原生连接与更新协调器、实际JVM Kotlin临时HTTPS | Android SDK/Compose类型编译、APK、真机/Keystore |

包内没有账号、模型密钥、个人历史、TLS私钥/证书、SDK。按用户决定没有安装Xcode/Android SDK、新增授权/支付或开放LAN/公网。EEG仍仅专注度接口，Rokid框架待真机联调。

## 本机开发与协作

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/run_paired_service.py --data-dir <源树外的私有目录>
```

默认只有127.0.0.1本机入口。手机访问需要可信且可达HTTPS；明确选择证书/地址后才能启用受限设备入口，见`设备连接API-R13.md`。不要关闭证书验证或将owner本机服务直接开放公网。

在同一仓库维护server/web/desktop/native/shared，ZIP只作快照。修改共享资源或API后：

```sh
python3 scripts/sync_clients.py
python3 scripts/export_api_contract.py
python3 scripts/stamp_web_assets.py
python3 scripts/sync_clients.py --check
python3 scripts/export_api_contract.py --check
python3 scripts/stamp_web_assets.py --check
python3 scripts/check_consistency.py --require-response-models --require-runtime-adoption
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
node --test tests/*.js
node --test desktop/test/*.js
```

原生宿主/HTTP脚本按各端README显式运行。最终日志在`docs/技术交接/验证记录/`及两端`ACCEPTANCE-ROUND15.md`。资源生成不替代手写布局与平台权限验收，不以测试数推算90%产品完成率。

## NeuroEcho v1.2 只读增强

R15 服务端可选读取 NeuroEcho Backend Handoff v1.2 的远程最新快照。配置只放在服务端环境：

```text
NEUROECHO_CONNECTION_FILE=<交接包 remote_connection.json 的绝对路径>
```

也可以分别设置 `NEUROECHO_BASE_URL`、`NEUROECHO_CHANNEL` 和
`NEUROECHO_READ_TOKEN`。服务端只调用交接包定义的
`GET /api/v1/share/{channel}`，使用 `Authorization: Bearer <read_token>`；不会把凭据放进 URL，
不会调用 owner 的 `/api/v1/policy`、`/eeg`、`/scene` 或写入接口。

通过校验的同一用户原话决策会作为内容层的模式约束，允许的 EEG、BPM 和场景摘要只作为低优先级观察，
不作为情绪、心理或健康诊断。A 会保持安静；B/C/D/E/F 分别对应短文本、短语音文本、步骤、澄清和倾听提议。
所有时效、来源、`decision_id`、`interaction_id` 和输出长度约束都在服务端重新检查。

远程未配置、鉴权失败、`available=false`、Windows 发布端过期、数据不属于当前用户原话或响应不符合契约时，
R15 继续使用原有 SOUL、记忆、来源、模型和规则回退流程。当前交接包的只读凭据不能把 R15 用户话语写回云端，
也不能单独触发新的 LoRA 决策；这需要队友补充独立的受信写入接口和凭据。`/api/config` 会显示只读增强是否已配置。

## 云端小鲸鱼语音（可选）

语音输入仍由浏览器的本地 `SpeechRecognition` 处理。小鲸鱼 TTS 默认保留本机
GPT-SoVITS；团队后端也可以把 R15 配置为调用 `voice-gateway`：

```text
NIANXIANG_TTS_ENABLED=true
NIANXIANG_TTS_PROVIDER=remote
NIANXIANG_TTS_BASE_URL=https://你的网关域名/v1
NIANXIANG_TTS_TOKEN=仅服务端保存的个人 Token
NIANXIANG_TTS_PERSONA_ID=whale
NIANXIANG_TTS_TIMEOUT=120
```

Token 只由 R15 后端读取，不会进入浏览器或静态资源。网关应通过可信 HTTPS 或
私有网络访问；GPT-SoVITS 的 `9880` 只监听云主机回环地址。没有网关配置时，
Windows 本机模式仍使用 `XINJI_TTS_URL` 和 `voice-settings.json` 中的本地设置。
网关的部署、Token 哈希轮换和 Nginx 模板见 `voice-gateway/README.md`。Windows 配置脚本会把配置写入启动器实际读取的 `%LOCALAPPDATA%\Nianxiang\data\voice-settings.json`，不会写入源码目录。
