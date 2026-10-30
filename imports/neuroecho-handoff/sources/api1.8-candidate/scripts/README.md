# 多端共享资源与检查

修改颜色、首批导航文案或显示偏好默认值后，在工程根目录执行：

```sh
python3 scripts/sync_clients.py
```

这个命令生成 `shared/generated/`，复制 Web 的 generated-design.css / generated-shared.js，并调用当前包中存在的 iOS / Android `sync_shared.py`。只更新生成文件，不改原生布局或手写交互；独立交接包保持 `native/ios` / `native/android` 目录约定，缺少另一平台时明确 SKIP。

提交或 CI 使用：

```sh
python3 scripts/sync_clients.py --check
python3 scripts/check_consistency.py --require-response-models --require-runtime-adoption
```

检查不会联网、读取凭据、启动服务或调用原生 SDK。`--check` 比较每个存在平台的生成文件 exact bytes；严格门进一步核对真实 HTML 的本地样式/脚本导入及先后顺序、Web 默认值和导航绑定、Swift / Kotlin 的实际源代码引用，以及 Swift 生成文件是否加入 Xcode Sources。注释中的 marker 不算接入。

API 改动需在具备后端依赖的 Python 中更新并核对声明快照：

```sh
python scripts/export_api_contract.py
python scripts/export_api_contract.py --check
```

## 封版与打包

当前版本 `2026.10.30-round8-integrated`；契约 `1.2.0`，OpenAPI 为 73 paths / 80 operations。并行作者输入快照截止 2026-10-30 01:25（中国时间，UTC+8）；后续整合在隔离候选进行，原始 outputs 工程保留。平台验收状态见根 `shared/release.json` 与 `docs/技术交接/第8轮开发与验收.md`。

在同一份最终源码中按顺序执行（API 导出使用含后端依赖的 Python 环境）：

```sh
python3 scripts/sync_clients.py
python scripts/export_api_contract.py
python3 scripts/stamp_web_assets.py
python3 scripts/sync_clients.py --check
python scripts/export_api_contract.py --check
python3 scripts/stamp_web_assets.py --check
python3 scripts/check_consistency.py --require-response-models --require-runtime-adoption
```

`stamp_web_assets.py` 根据本地 JS/CSS 的内容 hash 更新 `web/index.html`、`web/m.html` 的资源 URL，防止同一版混用旧缓存代码。它必须在共享生成资源及所有 Web JS/CSS 最后一次修改后运行；之后若又改资产，重新生成并执行 `--check`。`--check` 只核对，不改 HTML。资源 hash 一致不能代替浏览器功能验证。

再运行对应后端/Node/本端检查，记录 root 最终 Node 与 GUI 结果（本轮Web/H5 411/411、桌面28/28，QA App载入/刷新及H5 WAV控件已验证；完整GUI/扬声器仍另验），从同一冻结源码生成完整/iOS/Android交接包和桌面包。不要把合并前日志或较早 Windows 候选作为最终包验收。当前后端543项+24子测试、最终定向42项、shared14项通过；iOS40+23为Foundation/宿主检查，Android71+34 HTTP+22语法为Core/隔离HTTP/解析检查，均不代表手机SDK构建。

Windows 跟进时区需要 `tzdata`：`requirements.txt` 使用 `sys_platform == "win32"` 条件依赖。离线打包时必须更新 Windows 锁定依赖/wheelhouse并携带该 wheel；检查依赖清单和干净源码清单。较早候选组装不替代最终重建；Mac 上构建 Windows 目录/zip 不代表 exe 在 Windows 已运行。macOS 最终 GUI、Windows 实机、iOS/Android SDK/设备分别保留验收门槛。

当前门槛覆盖已迁入的颜色、三项导航和显示偏好默认值；其余手写文案、字号/排版、平台特例、能力状态和业务流程仍需对应变更单与平台验收。JSON 生成成功不等于所有页面自动适配，也不等于 iOS / Android 编译、无障碍、真机或视觉验收通过。新增共享字段时，还需在实际组件中接入，并扩展相应静态或运行检查。

脚本回归仅需 Python 标准库：`python3 tests/test_shared_baseline.py -q`。它会在临时工程里主动修改 token / 默认值 / 文案、破坏响应 schema 或移除运行引用，验证检查确实失败，并验证统一同步能修复生成物漂移；不修改真实项目资料。
