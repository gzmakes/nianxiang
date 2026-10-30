# 多端共享资源与接口契约

本轮已将首批共享资源接入 Web/H5（桌面共用同一页面）、iOS 和 Android 的运行源码：颜色、主导航文案、状态文案和新设备显示偏好默认值。已有用户偏好不会被新默认值覆盖。并非所有页面文案、布局和交互都已由一份配置控制。

- `design/tokens.json`：design.md 色板、尺寸与默认偏好。
- `product/copy.zh-CN.json`：首批关键中文文案，以 key 引用；可逐步扩充。
- `product/behavior.json`：一条持续对话、请求恢复、记忆版本核对、确认/撤回、跟进与文件范围。
- `api/openapi.json`：从真实 FastAPI 声明导出。核心成功响应已具类型；额外字段保持兼容，错误保留 detail 并提供 error_code。仍有非核心成功响应待补，不能称完整 SDK 已生成。
- `generated/`：生成资源，不手改；各端实际副本由同步脚本核对。
- `release.json`：本次交接版本与分层验收状态。

改资源后执行 `python3 scripts/sync_clients.py`；提交前执行 `python3 scripts/sync_clients.py --check` 和 `python3 scripts/check_consistency.py --require-response-models --require-runtime-adoption`。API 有变更时，在具备后端依赖的环境执行 `python scripts/export_api_contract.py` 并审查各端影响。

这套检查可以阻止生成资源和核心声明漂移，不能证明手机编译通过，也不会替代布局、文案语义、权限流程或可用性验收。远程 CI 尚未运行；接手团队应将这些命令放入同一仓库的合并检查。
