# 念响 · Personal Agent

以一条持续对话为主的陪伴型个人助理。资料按本人选择或明确启用的只读账号范围使用；记忆可确认、纠正和移除，回答应区分实际依据、推测和暂不可用的来源。

## 从哪里继续开发

当前应用位于 [`imports/neuroecho-handoff/sources/r15-api1.7`](imports/neuroecho-handoff/sources/r15-api1.7/)。`api1.8-candidate` 是未合并候选，不能把两套服务混着启动或验收。

| 目录 | 用途 |
|---|---|
| `web/` | Web与H5，共用当前服务；页面和手机布局仍分别维护 |
| `server/` | 对话、模型、记忆、来源、只读工具与动作边界 |
| `desktop/` | macOS/Windows Electron壳及离线组装脚本 |
| `native/ios/`、`native/android/` | SwiftUI、Compose原生源码及平台交接说明 |
| `shared/` | 共享设计、文案、能力与API快照；生成检查不能替代平台运行 |

以上路径均相对于当前应用目录。先读[应用说明](imports/neuroecho-handoff/sources/r15-api1.7/README.md)及[多端交接](imports/neuroecho-handoff/sources/r15-api1.7/docs/技术交接/第15轮多端交接.md)，再按对应端README运行。服务默认只监听本机；手机真机需要本人部署的可信可达HTTPS和设备配对，不把手机的127.0.0.1当作电脑。

## 当前实际边界

- 已有真实DeepSeek调用、飞书指定文档的授权/读取/确认/单份撤回、Mac日历和提醒事项读取、本地文件/Git，以及受支持WaytoAGI/即刻公开正文读取的记录。公开网页读取不是绑定对应平台账号。
- 飞书账号级检索支持按问题搜索与读取获授权文档，并在断开后停止读取；逐篇快照仍是独立可选方式。首次创建 CLI 应用 bootstrap 尚未完成验收。
- GitHub、Notion等未完成账号验收的来源不声称已连接；不新增这些账号授权。Rokid及脑电设备留待真机联调，脑电当前只考虑队友接口提供的专注度，不宣称情绪解码。
- iOS/Android交付为源码，新增文档引用容错与安全链接展示已通过Foundation/JVM及可用宿主检查；未安装Xcode或Android SDK，未生成/验收IPA、APK。Mac开发壳已完成独立自启/退出/重开及主空间借用验证，仍依赖本机源码与指定环境；其他便携包属于各自历史版本，不能据文件名当作最新版本。
- 旧样例读取、故障注入和合成设备控制已从正式服务退役。测试目录中的明确替身只用于隔离回归，不能成为运行时成功回退。

## 交接与验收记录

| 记录 | 内容 |
|---|---|
| [PRD逐项差距](imports/neuroecho-handoff/docs/handoff/念响-PRD逐项差距与决策清单.md) | 2026-10-30的需求对照；历史状态须结合后续验收更新，不能当作当前全部结论 |
| [桌面端](imports/neuroecho-handoff/sources/r15-api1.7/desktop/README.md) | 开发壳、macOS/Windows便携组装与实际运行门槛 |
| [iOS](imports/neuroecho-handoff/sources/r15-api1.7/native/ios/README.md)、[Android](imports/neuroecho-handoff/sources/r15-api1.7/native/android/README.md) | 各端工程、宿主检查与尚未完成的平台验证 |

本机数据库、模型设置、授权信息、TLS私钥和验收用私人正文保留在源码外的私有目录，不能加入Git或交付包。复用现有服务时继续沿用原data-dir，不能因换源码而改成新的空数据目录；重启后分别核验数据保留和真实模型调用。

支付暂不绑定钱包，也未发起付款。

## Windows 快速启动

在仓库根目录双击 `start_windows_web.cmd`，或在 PowerShell 运行：

```powershell
.\start_windows_web.cmd
```

脚本会自动进入实际服务目录 `imports/neuroecho-handoff/sources/r15-api1.7`，使用本机可用的 Python 3.10+ 创建 `.venv` 并安装依赖。服务启动后打开 <http://127.0.0.1:18787>。

启动后可检查：

```powershell
Invoke-RestMethod http://127.0.0.1:18787/api/health
Invoke-RestMethod http://127.0.0.1:18787/api/config
Invoke-RestMethod http://127.0.0.1:18787/api/plugins
```

`/api/config` 中 `model.source=public` 表示使用 CloudBase 公共模型代理；`/api/plugins` 中应能看到 `dafeiyu-001` 表情包。表情图片已随仓库进入服务，不需要每位协作者单独上传 COS。不要把 COS 密钥提交到仓库。

Linux/macOS 的完整开发命令和跨端同步说明见 `imports/neuroecho-handoff/sources/r15-api1.7/README.md`。
