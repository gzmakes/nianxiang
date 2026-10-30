# 念响 Web 拟人化交互升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将“小鲸鱼”人格卡接入现有 SOUL 机制，并在 Web 端安全支持更自然的通用交互展示和结构化多气泡回复。

**Architecture:** 保留现有 FastAPI、SQLite、模型调用和 `/api/chat` 合同。人格资源继续由 `server/prompts.py` 每轮读取项目根 `SOUL.md`；交互策略作为 Web 可复用常量，响应解析器在客户端完成 JSON/围栏/普通文本回退；现有 `app.js` 和移动页面只消费解析后的气泡字段，不引入新存储或接口。

**Tech Stack:** 原生 JavaScript、现有 FastAPI/Python 测试、Node `node:test`。

**Spec:** `C:/Users/bro/OneDrive - Microsoft 365/桌面/念响_Web端拟人化交互_Codex完整执行方案.md`

## Global Constraints

- 本次只实现 Web 端；不开发 Android、桌面、QQ 或其他客户端。
- 不新增服务器、数据库、云服务、账号系统、部署设施或依赖。
- 保留现有 API、BYOK、模型、记忆、页面和业务流程。
- 人格资源与通用交互策略分离；安全、授权、真实性规则优先。
- 结构化回复解析失败时安全显示普通文本，不泄露 JSON 协议或 emotion 标签。
- 技术解释、Markdown、代码块保持一个完整气泡。

## Review Focus

- 小鲸鱼人格资源缺失或超限时仍回退现有安全规则；由现有 `test_soul_loading.py` 覆盖。
- JSON 前后有围栏/说明、字段缺失、空数组、非法 JSON 时不能把协议泄露给用户；由 Web parser tests 覆盖。
- 代码块和 Markdown 表格不能被错误拆分；由 parser tests 覆盖。
- 多轮/刷新后同一 assistant 消息的气泡顺序稳定；由 app UI contract tests 覆盖。
- 连续输入已有 850ms 合并、生成中排队逻辑不能回归；由现有 chat flow tests 和 parser integration tests 覆盖。

### Task 1: 人格资源与纯逻辑回复模块

**Files:**
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/web/interaction-policy.js`
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/web/response-parser.js`
- Create: `imports/neuroecho-handoff/sources/r15-api1.7/tests/test_response_parser.js`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/SOUL.md`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/web/index.html`, `m.html`

**Interfaces:**
- `XinjiInteractionPolicy`: frozen policy text and `buildPromptHints(input)` helper with no DOM dependency.
- `XinjiResponseParser.parse(value) -> {messages: string[], emotion: string|null, format: string}`.
- `SOUL.md`: exact supplied `念响小鲸鱼_人格卡.md` content as the active persona resource.

- [ ] Add bounded parser tests for valid JSON, fenced JSON, plain text, invalid/empty/missing fields, Markdown and code blocks.
- [ ] Implement parser with conservative JSON extraction and single-text fallback.
- [ ] Add shared policy module containing natural conversation rules only, separate from persona and UI.
- [ ] Load parser and policy in both Web HTML entry points.
- [ ] Replace active SOUL resource with the supplied persona card.
- [ ] Run Node parser tests and existing soul tests.

### Task 2: Web rendering integration

**Files:**
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/web/app.js`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/web/m.js`
- Modify: `imports/neuroecho-handoff/sources/r15-api1.7/tests/test_chat_flow_ui.js` or add focused UI assertions.

**Interfaces:**
- Assistant message text is parsed once at render/response adoption; `message.bubbles` is derived locally and never sent to the server.
- Existing `expandTurns` remains responsible for user multi-input; assistant `bubbles` controls separate visual bubbles.

- [ ] Add a helper to decorate assistant messages with parser output without mutating user text or persistence payloads.
- [ ] Use parser output in desktop and mobile render paths; preserve message IDs, citations, action proposals, voice controls, stop/retry and refresh behavior.
- [ ] Keep technical/Markdown responses intact and avoid displaying internal emotion/format metadata.
- [ ] Run existing Web UI Node tests.

### Task 3: Verification and branch report

- [ ] Run `pytest -q` for the project tests.
- [ ] Run `node --test tests/*.js` from the R15 source root.
- [ ] Start local Web service and smoke check `/` and `/api/capabilities`.
- [ ] Review `git diff`, status, and active branch; report known limitation that persona selection remains current SOUL resource, since existing API has no persona selector.
