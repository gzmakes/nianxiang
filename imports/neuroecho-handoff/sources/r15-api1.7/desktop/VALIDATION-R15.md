# R15 桌面连接验收记录

本轮仅修改 `desktop/**`；后端 API、Web、原生端与共享资源由各自负责人处理。没有启动账号授权、真实模型／CLI／系统写入，没有开放网络监听，没有构建最终 App 或 Windows 包。

- `node --test desktop/test/*.test.js`：93/93 通过。覆盖真实 Node HTTP、小体积／整体超时／取消／无重定向、身份与分区、nonce 明确确认、latest-wins、磁盘失败、实际 selector 事件、只读 shared preload、owner IPC、真实 main.js 在 Electron adapter 下的空间／窗口／通知隔离、托盘／快捷条调用，以及启动中退出／迟到完成。独立审查发现的 TDZ、已隔离窗口被快捷键重展、pending owned 后端退出遗漏及缓存窗口导航 origin 随全局切换均已修复并加回归。
- `python3 -B -m unittest discover -s desktop/test -p 'test_package_*.py'`：21/21 通过。包括 Mac/Windows 新资源必需门、普通文件／symlink、精确复制、隐私、旧打包路径、许可证、离线依赖与原有归档安全规则。
- 实际官方 Electron 43.3.0 开发运行：用既有 R14 只读嵌入 runtime、全新合成 profile 和空 DB；own 18823 回环 HTTP 可用，退出只结束其 owned 子进程；独立共享服务 18825 继续可用。最终业务源码再次启动 shared profile，已创建身份绑定分区、未启动 own 端口、无主进程错误日志；退出后共享服务仍 200。所有本轮测试创建进程均已停止，root 的 18819 未触碰。
- GUI：CUA 明确返回 Mac 锁屏，**NOT_RUN**。未点击连接确认，不能称界面流程验收完成；没有绕锁屏、CDP、Playwright 或 osascript 替代。实际 Electron 启动／HTTP 证据也不等于 GUI 连接成功。
- Windows exe：**NOT_RUN**；本轮仅通过共同主逻辑与打包测试。

保留限制：本机 owner 服务没有原子 instance 写前置条件。共享新文档和写请求前的只读身份核对、后台核对和隔离可减少错误转发，但不能把多个 HTTP 请求称为原子身份绑定，也不保证阻止本机同端口恶意替换。旧草稿／unknown 不迁移、不重发；系统通知与原生文件桥不授予共享页面。

日志与合成运行报告位于工作区 `work/round15-desktop-node.log`、`work/round15-desktop-packager.log`、`work/round15-desktop-qa/runtime-report.json`；最终源清单由 `work/round15-desktop-seal.json` 记录。最终冻结、离线组装、搬移与 GUI 门另行记录。
