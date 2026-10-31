# 念响公共模型代理（cloud function）

让 `git clone` 下来的人**不用自带 key** 也能跑真模型：key 只在云端函数的环境变量里，
客户端拿不到。

```
客户端 server/model.py
   POST https://<env>.service.tcloudbase.com/nxproxy/chat/completions
      ↓  （OpenAI 兼容协议）
本函数（Node 18，无依赖）
   → 加 Authorization: Bearer <真 key>
      ↓
腾讯云开发 AI 网关  →  DeepSeek deepseek-v4-flash
```

## 客户端怎么用它

`server/model_settings.py` 里的 `PUBLIC_BASE_URL` 就是它的地址；优先级：

```
环境变量 XINJI_MODEL_*  >  server/model-settings.json  >  公共节点
```

想强制走「无模型 → 规则引擎」（例如跑测试、离线演示）：

```bash
XINJI_MODEL_PUBLIC=0
```

想换成别的公共节点：

```bash
XINJI_MODEL_PUBLIC_BASE_URL=https://your-host/v1
XINJI_MODEL_PUBLIC_MODEL=deepseek-v4-flash
```

## 部署

```bash
cp cloudbaserc.example.json cloudbaserc.json   # 填入 AI_KEY
tcb fn deploy nxproxy --path /nxproxy --force -e <envId>
```

`cloudbaserc.json` 含密钥，已在 `.gitignore` 里排除，**不要提交**。

## 成本与风险（必须知情）

| 项 | 现状 |
|---|---|
| 谁能用 | 任何拿到地址的人（地址在源码里，等于公开） |
| 花的钱 | 你 CloudBase 套餐的**资源点** |
| 限流 | 每 IP 20 次 / 10 分钟；每实例每天 500 次 |
| 单请求上限 | 16 条消息、12000 字符、800 output tokens，强制关思考 |
| 计数器 | 在实例内存里，冷启动会重置 → 只能"防手滑"，不是防攻击 |

要真正控成本，下一步应该：把 key 换成一个专用账号的 key、在网关层加配额、
或者接 CloudBase 的用量告警。当前形态适合"给朋友试用的演示节点"。
