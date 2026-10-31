# 公网 Web/API 部署

`voice.aicloudsky.com` 是纯 TTS Gateway，不是网页入口。要让团队成员直接打开网页，
需要把本目录上一级的 R15 FastAPI 容器部署为 Cloud Run 服务；容器会同时提供最新 Web
页面、聊天 API 和 `/api/voice/clip`，再由服务端调用现有语音 Gateway。

先完成一次 `tcb login`，然后在仓库根目录执行（把环境 ID 换成自己的 CloudBase 环境）：

```powershell
$source = (Resolve-Path 'imports/neuroecho-handoff/sources/r15-api1.7').Path
tcb cloudrun deploy `
  --env-id yuntun-5g1u97p56054130d `
  --service-name nianxiang-web `
  --source $source `
  --port 80 `
  --install-dependency true `
  --open-access-types PUBLIC `
  --min-num 1 --max-num 1 --force --wait --json
```

部署完成后，把 Cloud Run 返回的 HTTPS URL 写入服务环境变量
`XINJI_PUBLIC_ORIGIN`，并按 `cloudrun.env.example` 设置其余变量后重新部署。至少需要：

* `XINJI_VISITOR_ISOLATION=1`、稳定的 `XINJI_VISITOR_SECRET`；
* `XINJI_MODEL_PUBLIC=1`（文本回复通过腾讯云 DeepSeek 公共代理）；
* `NIANXIANG_TTS_PROVIDER=remote`、Gateway URL、个人 Gateway Token 和 `whale` 人格。

完成后用 `https://<cloudrun-url>/api/health` 和网页首页检查服务。浏览器只访问 R15
服务，不会拿到 TTS Token；R15 服务端再请求 `https://voice.aicloudsky.com/v1/tts`。
因此其他人只需打开同一个 HTTPS 网页即可得到文本和小鲸鱼语音。真实密钥、Token、
`server/voice-settings.json` 和本地数据库都不会进入 GitHub。
