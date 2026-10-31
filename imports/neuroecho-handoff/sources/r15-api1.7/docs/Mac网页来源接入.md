# 本机网页来源接入：接口与验收

本变更面向运行念响服务的本机浏览器。Git、GitHub、Notion、Gmail CLI 在 Windows/macOS 共用；系统日历和任务按平台走 macOS AppleScript 或 Windows Outlook 适配器。浏览器访问远程服务不会获得运行服务电脑的本地日历、任务或磁盘权限。

## 协作说明

已尝试推送独立分支以建立 PR，但 GitHub 凭据助手无法在非交互环境提供凭据，返回 Cannot prompt because user interactivity has been disabled。无法先发布 Issue/PR；本地先记录新增接口，不宣称已同步团队。不修改 main 或其它来源候选。

## 新增接口

- POST /api/connector-auth/{provider}/start：provider 只允许 github/notion/gmail；仅用户点击发起。不读取资料。
- GET /api/connector-auth/{provider}/status：idle/starting/pending/success/error/needs_install；仅返回受限登录链接、GitHub 一次性设备码和固定提示，不转发 CLI 输出或凭据。
- /api/gmail/preview 新增可选 method=cli；默认 imap，现有 address/password 调用兼容。

所有路由沿用本机同源防护，不加入远程配对端允许列表。状态只在内存保存，重复点击复用进行中的任务，最长十分钟；关闭网页不会撤销服务商授权。

## 读取范围

| 来源 | 方式 | 范围 |
|---|---|---|
| 本地文件 | 浏览器文件选择 | 仅主动选择的文本/Word，经预览确认 |
| 本地代码库 | git | 指定仓库最近最多 8 条提交，不上传源码树 |
| Notion | 官方 ntn / 既有 Token | 指定单页前 50 个顶层文本块；Token 模式保留原能力 |
| Gmail | Google Workspace gws / 既有 IMAP | 最近最多 5 封未读收件箱邮件头，不读取正文、不标为已读、不发邮件 |
| GitHub | gh | 当前账号创建的最近 PR 摘要 |
| 提醒/任务 | macOS osascript 或 Windows Outlook | 未完成事项/任务，最多保留 8 条 |
| 日历 | macOS osascript 或 Windows Outlook | 未来 7 天日程，最多保留 8 条 |

CLI 登录权限由官方服务商显示；本项目只调用表中的读取命令。GitHub CLI 自身可能申请 repo 等较宽权限，用户应在官方页面核对。Google 仅请求 gmail.metadata；不读取邮件正文。

## 管理员首次准备

macOS 运行 `scripts/start_mac_web.command`，Windows 运行 `scripts/start_windows_web.cmd` 或 `scripts/start_windows_web.ps1`。需要 Python 3、Node/npm；CLI 装在用户目录或系统 PATH，登录凭据留在各 CLI 自己的安全存储，不写项目。Google 必须由管理员预先配置 Desktop OAuth 客户端，Windows 的日历/任务需要已安装并登录 Outlook 桌面应用。

之后普通用户可在网页点“连接”，在运行服务的同一台电脑浏览器完成登录，再选择资料预览、确认接入并聊天。资料摘要会交给该项目已配置的模型服务。写入日历/提醒事项仍保留原有逐次预览确认，批量开发授权不替代产品内确认。

## 真实运行边界

开发电脑为 Windows；Mac 系统权限弹窗、Safari、AppleScript、Keychain 与真实账号登录均须 Mac 实测。模拟测试不能证明上述流程已真机完成。飞书此前 21001 独立存在，不在这七项连接器中冒充已修复。

## 本次自动验证

- 相关后端测试：161 项通过，覆盖授权状态、来源读取、同源保护、旧 Gmail 调用及飞书回归。
- 网页测试：581 项通过。
- 共享接口一致性：16 项检查通过；网页资源哈希检查通过。
- 以上在 Windows 上运行，AppleScript 使用模拟测试，不等于 Mac 真机验收。

## 官方参考

- https://cli.github.com/manual/gh_auth_login
- https://www.notion.com/help/use-notion-from-your-terminal-with-notion-cli
- https://github.com/googleworkspace/cli
