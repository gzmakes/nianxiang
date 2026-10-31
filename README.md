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

## Windows 本地语音

语音代码和无密钥配置模板在 `imports/neuroecho-handoff/sources/r15-api1.7`。clone 后进入该目录，在 PowerShell 执行：

```powershell
.\scripts\setup_windows_voice.ps1
```

这一步会自动使用 PATH 中的 `ffmpeg.exe`。如果 FFmpeg 不在 PATH，可显式指定：

```powershell
.\scripts\setup_windows_voice.ps1 -FfmpegPath 'C:\\Tools\\ffmpeg\\bin\\ffmpeg.exe'
```

需要小鲸鱼音色时，再加上本机的 GPT-SoVITS 参考音频：

```powershell
.\scripts\setup_windows_voice.ps1 -EnableTts -ReferenceAudio 'C:\\path\\to\\reference.wav'
```

ASR 使用每台电脑自己的腾讯云凭证，放在 `%USERPROFILE%\.tencentcloud\credentials`，不要提交到 GitHub：

```ini
[default]
secret_id = 你的 SecretId
secret_key = 你的 SecretKey
```

最小 CAM 权限是 `asr:SentenceRecognition` 和 `asr:GetUsageByDate`。小鲸鱼 TTS 还需要本机运行 GPT-SoVITS `127.0.0.1:9880`，参考音频路径可以通过脚本参数调整。运行 `.\scripts\check_windows_voice.ps1` 检查配置、念响服务、FFmpeg、ASR 凭证和 TTS 端口。
