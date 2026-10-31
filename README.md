## 目录说明

请将项目源文件放入此目录，并避免提交本地配置、密钥、依赖缓存和构建产物。

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
