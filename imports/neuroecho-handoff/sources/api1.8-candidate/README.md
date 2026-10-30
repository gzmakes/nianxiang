# 回响 · 团队整合源码候选（2026-10-30）

这份源码是独立候选，基于 R14 合入拒谈保护、跨设备发送冲突处理、Word 预览和设置实验区。API 契约为 **1.8.0**。它尚未部署到当前运行的服务，也不包含已经构建的本版桌面 App。先读 `docs/技术交接/本轮整合与验收边界.md`。

依赖需要按下方历史开发说明安装；模型密钥、账号授权和数据由使用者自行配置。iOS/Android 是源码和宿主检查，仍需 SDK 构建和真机验收。R14 和更早的包、日志、运行结论仅是历史证据，不能替代本候选实际验收。

---

以下保留 R14 原始说明，版本号、测试数量及桌面包状态只适用于 R14：

# 回响 · 第14轮多端开发交付

版本 `2026.10.30-round14-integrated`，API **1.7.0**。先读 `docs/技术交接/第14轮多端交接.md`、`跨端更新API-R14.md`。R13设备连接合同继续有效。早期轮次的日志是历史证据；源码、包体、平台运行和真实使用效果分别验收。

## 本轮解决的问题

同一持续对话在另一端改变后，长期打开的页面曾只能靠切回或手动刷新。R14新增只读变更游标：消息、记忆、来源、心情、跟进、边界、动作和时间驱动呈现都会使相关域失效。SQLite触发器和原写入同事务，只保存每域最新revision，不存旧正文、来源内容或凭据。

各端先读changes，再读取当前快照，再复核原游标没有新变化，最后一起发布快照与第一份游标。当前端正在编辑、上传确认、发送/分段呈现或有unknown请求时，保留原草稿并提示，不推进游标、不自动POST。删除和来源撤回以完整替换传播；旧Today、任务、来源、分段GET不能把过期内容带回来。后台停止轮询，错误退避；这不是云推送、离线写入队列或冲突自动合并。

Web/H5的更新栏保持轻量，不新增欢迎弹窗。共享的检查/待编辑/已更新/暂时离线文案实际用于Swift、Kotlin和Web。原生依旧只交付源码；没有SDK/IPA/APK或真机验证。

## 交付和运行边界

| 端 | 本轮交付 | 未证明的部分 |
|---|---|---|
| Web/H5 | 前台更新、编辑保护、原单一持续对话和连接体验 | 真手机浏览器、线上部署、完整无障碍验收 |
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
python -m pytest -q
node --test tests/*.js
node --test desktop/test/*.js
```

原生宿主/HTTP脚本按各端README显式运行。最终日志在`docs/技术交接/验证记录/`及两端`ACCEPTANCE-ROUND14.md`。资源生成不替代手写布局与平台权限验收，不以测试数推算90%产品完成率。
