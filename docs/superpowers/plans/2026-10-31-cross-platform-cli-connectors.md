# 跨平台 CLI 来源接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `feat/feishu-cli-integration` 上合入 Mac CLI 网页接入增量，并让 Git/GitHub/Notion/Gmail/System sources 在 Windows 与 macOS 使用统一服务端接口。

**Architecture:** Web 只调用来源目录、预览和授权接口；Python 服务通过 `cli_runtime` 解析跨平台 CLI，通过 `system_source` 选择 macOS `osascript` 或 Windows PowerShell 系统来源。状态模型明确区分可用、需安装、需登录、平台不支持和错误。

**Tech Stack:** Python 3.11+, FastAPI, pytest, Node test runner, Windows PowerShell, macOS osascript, gh/ntn/gws CLI。

**Spec:** `docs/superpowers/specs/2026-10-31-cross-platform-cli-connectors-design.md`

## Global Constraints

- 服务默认只监听 `127.0.0.1`。
- 不自动安装第三方 CLI、OAuth 客户端或 Outlook/To Do。
- 凭据留在各 CLI 的安全存储中；网页不接收原始凭据或原始 CLI 输出。
- 不把 Windows Outlook/To Do 伪装成 Apple 来源；返回具体提供方和状态。
- 读取范围沿用附件说明中的上限。

## Review Focus

- CLI 缺失时：目录和授权接口返回 `needs_install`，服务仍能启动。
- CLI 未登录时：返回 `needs_login`，不显示原始命令输出。
- Finder/Windows 启动时：PATH 仍能找到用户目录和常见安装路径。
- macOS 与 Windows 系统来源：平台不支持或权限失败均返回可恢复错误，不伪造数据。
- 原有飞书、旧 Gmail、Git 来源：跨平台改动不改变已有接口结构。

### Task 1: 合入附件增量与建立跨平台 CLI 运行时

**Files:**
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/docs/Mac网页来源接入.md`
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/scripts/start_mac_web.command`
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/server/cli_runtime.py`
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/server/connector_auth.py`
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/server/gmail_cli_source.py`
- Modify: attachment-listed server/source/web files as needed to apply the incremental patch.
- Test: attachment-listed connector tests plus existing CLI source tests.

**Interfaces:**
- Produces `cli_runtime.resolve`, `cli_runtime.environment`, `cli_runtime.probe` for all CLI adapters.
- Produces connector auth routes with stable status values.

- [ ] Copy only the attachment files into the isolated branch and inspect conflicts against `origin/main`.
- [ ] Add failing tests for missing CLI, custom executable override, and safe status output.
- [ ] Implement runtime resolution and environment construction for Windows/macOS.
- [ ] Add connector auth routes and CLI Gmail adapter using the runtime.
- [ ] Run targeted Python and Node connector tests.

### Task 2: Add unified Windows/macOS system source adapter

**Files:**
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/server/system_source.py`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/server/apple_source.py`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/server/main.py`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/server/real_sources.py`
- Test: `tests/test_system_source.py`, `tests/test_apple_source.py`

**Interfaces:**
- `system_source.read_reminders() -> dict` and `system_source.read_calendar() -> dict` return the existing source preview shape.
- Windows adapter uses PowerShell only when the relevant Outlook/To Do COM/API is available; it reports `needs_install` or `error` otherwise.

- [ ] Write platform-independent tests with mocked command runners.
- [ ] Move platform dispatch behind `system_source` while preserving the existing Apple response shape.
- [ ] Add Windows PowerShell scripts with bounded output and escaped text.
- [ ] Wire onboarding reads and real source reads to the dispatcher.
- [ ] Run all source and API contract tests.

### Task 3: Make catalog and web UI platform-aware

**Files:**
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/server/connectors.py`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/server/api_contract.py`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/web/app.js`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/web/index.html`
- Create: `tests/test_cross_platform_catalog.py`, `tests/test_connector_auth_ui.js`

**Interfaces:**
- Catalog entries expose `platform_status` and `availability_reason` without removing existing fields.
- Web renders installation/login/platform messages and keeps the same preview confirmation flow.

- [ ] Add tests asserting Windows and macOS catalog status mapping.
- [ ] Add status fields to catalog/API response models.
- [ ] Render status text and disable only unavailable connectors; preserve selectable sources.
- [ ] Run Node UI tests and API response checks.

### Task 4: Add Windows startup and operator documentation

**Files:**
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/scripts/start_windows_web.ps1`
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/scripts/start_windows_web.cmd`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/README.md`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/docs/Mac网页来源接入.md`

- [ ] Add Windows launcher that creates/uses a local venv and an external private data directory.
- [ ] Document CLI installation/login checks on both platforms and the exact source limits.
- [ ] Run launcher argument/help checks without starting a persistent service.

### Task 5: Full verification and branch review

- [ ] Run `python -m compileall -q server`.
- [ ] Run targeted pytest suites and Node connector tests.
- [ ] Start the Windows service with an external temp data directory and verify health, catalog, and home page.
- [ ] Run consistency/static checks available in the source tree.
- [ ] Review diff for credentials, source-tree databases, platform claims, and unrelated changes.
- [ ] Commit the branch with a focused message.
