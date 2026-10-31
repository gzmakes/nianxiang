# 跨平台 CLI 来源接入设计

## 目标

让念响网页在 Windows 和 macOS 上使用同一套来源接口接入本机 CLI。Git、GitHub、Notion、Gmail CLI 的调用由服务端统一封装，网页只展示来源状态和预览结果。系统日历与提醒事项保留 macOS 适配，并为 Windows 提供 Outlook/To Do PowerShell 适配；未安装、未登录或平台不支持时返回可解释状态，不伪造数据。

## 范围

- 合入附件中的 CLI 运行时、授权状态和来源读取增量。
- 新增跨平台 CLI 路径解析、环境变量覆盖和 Windows 启动脚本。
- 让 GitHub、Notion、Gmail、Git 来源使用统一的进程环境与状态模型。
- 将 Apple 日历/提醒事项抽象成系统来源；macOS 走 `osascript`，Windows 走 PowerShell 的 Outlook/To Do 查询，失败时保留错误提示。
- 网页继续调用现有 `/api/onboarding` 和来源目录接口，不直接执行 CLI。

## 不在本次范围

- 不自动安装第三方 CLI、OAuth 客户端或 Outlook/To Do。
- 不上传凭据，不读取 CLI 原始输出并直接显示。
- 不把 Windows 的 Outlook/To Do 当作 Apple 来源的完全等价实现；状态中会标明具体提供方。
- 不处理手机系统日历、远程多设备同步或公网暴露。

## 约束

- 服务默认只监听 `127.0.0.1`。
- CLI 凭据留在各自工具的安全存储中。
- 读取范围沿用附件约束：Git 最近 8 条提交、GitHub 当前账号最近 PR 摘要、Notion 指定页顶层文本块、Gmail 最近 5 封未读邮件头。
- 所有来源状态必须区分 `available`、`needs_install`、`needs_login`、`platform_unsupported` 和 `error`。
- Windows 与 macOS 共用 Python 代码；平台特有命令只存在于对应适配器。

## 方案选择

1. 统一跨平台适配器：网页调用稳定接口，服务端按平台选择 CLI 和系统适配器。改动集中、可测试、后续可添加 Linux 或其他来源。采用此方案。
2. 只把 GitHub、Notion、Gmail、Git 跨平台化：改动更小，但 Windows 仍缺系统日程来源，不满足完整跨平台目标。
3. 浏览器直接调用本机 CLI：浏览器权限和凭据边界不安全，也无法覆盖系统日历/提醒事项，因此不采用。

## 接口设计

- `server/cli_runtime.py` 提供 `resolve(name, override=None)`、`environment()`、`probe(name)`，负责 Windows/macOS 可执行文件查找、环境变量覆盖、版本/登录状态探测。
- 连接器授权接口沿用附件的 `/api/connector-auth/{provider}/start` 和 `/status`，只返回受限登录 URL、设备码或状态消息。
- `/api/onboarding/catalog` 返回每个来源的 `platform_status` 和 `availability_reason`；网页按这些字段渲染按钮和提示。
- `server/system_source.py` 根据 `sys.platform` 调用 `apple_source` 或 Windows PowerShell 适配器，返回统一的来源预览结构。

## 验收

- Windows：服务可启动；CLI 探测不会因缺少 Mac 命令崩溃；Git/CLI 来源返回明确的未安装或未登录状态；Windows 系统来源返回 Outlook/To Do 状态或可恢复错误。
- macOS：保留 `osascript` 路径和附件中的启动脚本；CLI 环境变量和 Finder 启动时的 PATH 解析可用。
- 两端：网页只依赖统一 API；来源状态不会把演示数据标成真实数据；现有来源和飞书回归测试继续通过。
