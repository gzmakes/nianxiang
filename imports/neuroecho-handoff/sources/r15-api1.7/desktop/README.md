# 回响 · macOS / Windows 桌面端

Electron 可显式连接已有 Web 的本机服务，继续同一条持续对话；桌面默认 1000×830 双栏，直接进入聊天，连接范围由用户主动打开。记忆输入与确认使用应用内对话框。状态光、搜索、话题、草稿、来源与记忆沿用共用页面。

## 连接已有 Web 的服务（R15）

从菜单／托盘「连接与空间…」、快捷键 `⌘⇧L` / `Ctrl+Shift+L` 或设置按钮进入。输入已有 `http://127.0.0.1:端口`，先核对再明确连接；不扫描端口，不复制模型 key 或数据。共享空间使用独立存储分区和受限桥，桌面原生文件桥、主进程系统通知、摘要与快捷输入条停用。离线或身份变化返回连接页，不静默切回空空间；原空间可明确返回，原草稿与 unknown 请求不迁移、不重发。

完整操作、接口与 HTTP 身份检查限制见 [CONNECTING-local.md](CONNECTING-local.md)。共享服务不会被桌面结束；仅桌面自己启动的后端由其退出流程管理。

## macOS 本机开发版

`回响-本机开发版.app` 依赖旁边源码目录和可用 Python 环境。运行时固定为官方 Electron 43.3.0，构建脚本可做 ad-hoc 完整性签名；没有 Developer ID、公证、自动更新或跨机器发行保证。系统拦截时保留原提示，不关闭防护。

从 Dock 重开会恢复最小化并聚焦；加载失败会显示原因，可按 ⌘R 重试。退出只停止本次自己启动的后端，借用的 Web 服务继续运行。

以下默认命令仅适用于源码目录中已有可执行 `.venv/bin/python` 的情况；缺失时，打包器会在复制 Electron 前明确拒绝，并要求同时提供下面的 `--python` 与 `--backend-data-dir`。已有 Web 服务能被借用，不代表开发壳具备自行启动能力。

```sh
python3 desktop/package-local.py --runtime /path/to/official/Electron.app --project-root /path/to/project --output /new/path/回响.app --adhoc-sign
```

源码下没有 `.venv`，或 Web 使用外部数据目录时，打包必须同时明确指定现有解释器与原数据目录。下面的配置只写路径到本机开发壳的 `project-root.json`，不读取或复制模型 key、账号、数据库，也不会创建或更改数据目录权限：

```sh
python3 desktop/package-local.py --runtime /path/to/official/Electron.app --project-root /path/to/project --output /new/path/回响.app --port 18827 --python /path/to/existing/.venv/bin/python --backend-data-dir /path/to/original-private-data --adhoc-sign
```

`--python` 保留 `.venv/bin/python` 的符号链接入口，不改成其指向的全局 Python；这样才能保留已有依赖环境。`--backend-data-dir` 必须是源码与任何 `.app` 包体外、已存在的私有目录（0700），与桌面 UI 的 `--profile` 是两种不同用途。两项必须成对提供，路径失效时明确失败，不回退到源码中的空数据库。

此开发配置使用 `scripts/run_paired_service.py --data-dir … --local-port …` 自启，默认只有固定回环 HTTP，不启用 TLS／局域网入口。端口已有服务时，除产品健康响应、相同源码 cwd 和两次稳定监听 PID，还核对该 PID 是否打开了所选数据目录的 `data.db.server.lock` 数字文件描述符；只查该文件的元数据，不读取文件、模型配置、进程环境或完整 argv。macOS 的此项检查不是排他锁证明；无法核验时拒绝借用，可从「连接与空间」另行明确选择已有服务。退出只停止桌面自己启动的子进程，借用服务不会被结束。

此处只提供本机开发壳修复；Mac 自包含便携包的独立 profile/bootstrap 与 Windows 启动行为保持原路径。重新打包、Dock 启动、自启／借用与窗口交互仍需分别验收，单测不代表 App 已重建或实际打开。

## macOS Apple Silicon 自包含便携路径（R12）

`package-macos.py` 从本地已校验的 Electron 43.3.0 arm64、Astral CPython 3.13.18 发行归档和 hash-lock/wheelhouse 组装。`.app` 内包含 server、Web、shared、Python 和依赖，移动整个 `.app` 后不再依赖兄弟源码、外部 venv 或全局 Python。范围是 Apple Silicon；Electron 声明最低 macOS 12、Python 声明 11，旧系统/Intel/GUI 仍需单独验收。Astral 构建不是 python.org 签名安装程序。

便携版使用独立 profile（默认 `cn.xinji.echo.portable`）中的 `backend/data.db` 与 `backend/model-settings.json`，不会导入开发者的对话、模型设置或账号。`-I -B` 启动隔离 Python，禁止运行产生包内字节码。退出只停止自己的子进程；端口占用时不借用服务，因为程序目录相同不能证明数据 profile 相同。旧 `package-local.py` 的开发启动方式继续保留。

构建脚本自身不下载、不安装 SDK、不访问账号、不更改权限，也不自动连接模型/CLI。Python 的完整归档只用于核对同构建解释器及补全 `PYTHON.json` 引用的第三方许可证，不会把构建产物装入 App。命令和离线准备方法见 [PACKAGING-macOS.md](PACKAGING-macOS.md)。ad-hoc 签名只校验本机完整性，不是 Developer ID、公证或 Gatekeeper 放行。子进程 HTTP 验证不等于锁屏状态下未完成的 GUI 验收。

## Windows x64 便携开发包

`package-windows.py` 从经过 SHA256 核验的 Electron ZIP、Python 3.13.13 嵌入包、带 hash 的依赖锁和本地 wheelhouse 组装。包含可用布局的 exe、Python 与依赖；不携带私人数据库、模型 key 或既有账号。须解压到可写目录，先创建全新的本机数据，配置自己的模型。

本轮在 Mac 完成了离线组装、归属规则单测与内容审计，**未在 Windows 上运行 exe**。首次启动、中文路径、PowerShell/CIM 权限、托盘/快捷条、文件选择、退出/重开和网络/CLI适配仍待 Windows 验收。Windows 不支持 Apple 日历/提醒读取；来源目录必须显示真实平台边界。

Windows 使用隐藏标题栏与系统按钮预留、彩色托盘图标、Ctrl 快捷键。通知仅提供点击查看，不能把 macOS 通知动作按钮当作 Windows 能力。

## 服务归属与开发配置

默认 `http://127.0.0.1:18787`，不开放网络。

- macOS：lsof 核对监听仅 127.0.0.1、真实进程目录属于本副本；显式外部数据目录的开发壳另核对该监听 PID 打开的所选 profile 专用锁文件描述符。
- Windows：PowerShell Get-NetTCPConnection/CIM 核对本端口、PID、Python 路径和包含明确 --app-dir 的启动参数；未知归属拒绝复用。
- 空闲端口才自行启动；不扫描其他端口，不结束未知进程。退出仅停止自己的子进程。

开发测试可指定 XINJI_PORT / XINJI_PROJECT_ROOT / XINJI_PYTHON / XINJI_DESKTOP_DATA_DIR；macOS 开发壳可用 XINJI_BACKEND_DATA_DIR 指定外部后端数据目录。XINJI_DESKTOP_DATA_DIR 只决定桌面偏好与分区位置，不能替代后端目录。不要把本机用户数据目录或模型配置打进包。

## 桌面操作与验证

菜单栏/托盘提供打开回响、唤起输入条、本机系统通知暂停到次日09:00与设置。输入条只追加草稿，仍需本人发送。快捷键被占用时可从菜单进入。

原生文本选择只读明确选取的 md/markdown/txt/json，单份上限 1MB，之后仍须预览确认；网页统一选择器上限以页面说明为准。通知仅是受系统权限和签名影响的适配，不是可靠后台提醒服务；后台推送尚未提供；对应桌面进程或浏览器页面需保持运行。

```sh
(cd desktop && node --test test/*.test.js)
python3 -m unittest discover -s desktop/test -p 'test_*.py' -v
```

单测不替代系统 UI。最终本轮运行证据见开发验收说明；macOS/Windows、窗口/托盘/通知、借用/自启后端分别列出，不把组装成功称为全平台运行成功。

## R9：按约定窗口轻问

对话中的「今天先安静 / 暂停轻问 / 恢复按约定轻问」使用同一本机服务的 CAS 边界，聊天和待办保留。更改或恢复边界、撤回来源会使旧联系许可失效，旧未来任务也不会自动重新授权；需本人重新安排。托盘的暂停仅控制本机系统通知，不能当作跨端边界。

新增跟进默认只保存待办；明确勾选允许联系后，才在本人选择的 5–180 分钟窗口尝试一次提示。前台提示、后台浏览器系统通知及 Electron 系统通知共用后端 claim/recheck/finish；同主题重叠窗口共用一次机会。系统通知另需显式开启，默认关闭，不在启动时请求权限。旧服务缺能力键时不调用新路径。

提示前校验标识、渠道、发生时间与有效期；false、晚到或未知结果不当作成功、不自动重发。尝试编号先落盘，隐藏/离开页面、改变设置、回到桌面主窗或过期会清理本地提示；系统已显示的信息可能被看见，不能保证收回。submitted 只表示本机调用呈现接口，不能证明送达、已读或任务完成。「先收起」不完成事项。

安静时间、间隔、次数与临时暂停也控制应用内轻问；即使 H5 不支持 Notification，仍可读取并保存这些规则。未配置时的本地时区仅是待确认草稿，服务按各条明确时区执行默认静默规则。

本轮使用系统通知和 DOM 替身测试，并以随机回环端口临时数据库验证真实 HTTP；不等于 macOS/Windows 系统通知或签名发行验收。开发证据由工作区 work/round9-web-desktop.md 记录。


## R13 独立设备服务入口

便携包增加两个明确白名单文件：`resources/project/scripts/run_paired_service.py` 与 `resources/project/paired_service_bootstrap.py`（Mac位于App的Contents/Resources）。此辅助入口只使用包内依赖，不读取或复制已有配置，不自动选择TLS证书，不自动启用远程listener。GUI正常启动仍沿原本机方式。

如需开发同学配置同一worker的本机与TLS入口，先退出使用同一数据目录的App，再用包内Python执行辅助入口；私有数据目录必须在签名包/源码树外，不借用占用端口，也不写包体。例如Mac从包内Python传入 `-I -B /path/回响.app/Contents/Resources/project/paired_service_bootstrap.py --data-dir /path/private-profile --local-port 18809`；Windows用 `resources/project/python/python.exe -I -B resources/project/paired_service_bootstrap.py --data-dir C:/path/private-profile --local-port 18787`。这些命令默认只有回环HTTP。

显式TLS参数为 `--enable-paired-tls --paired-host 127.0.0.1 --paired-port 18810 --tls-certfile /本人选择的证书 --tls-keyfile /本人选择的私钥`，证书需按客户端的正常信任与主机名检查通过。私有接口绑定还需单独明确选项；本轮没有实际开启LAN/公网或安装系统信任。客户端不能用自己的127.0.0.1访问电脑，真实手机可达地址与证书准备仍待后续。入口及权限合同在完整源码包 `docs/技术交接/设备连接API-R13.md`。

此路径的Mac包内解释器检查与Windows静态组装分别记录在本轮平台报告，不将它们混称手机已配对或Windows已运行。
