/* 念响 · PC Web MVP 前端 */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s = "") =>
    String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const feishuDisclosure = "读取时请求整篇文档，提取正文后保留最多 12000 字；下方可以滚动查看全部保留的正文。确认后保存在本机；生成理解时可能向当前模型服务发送摘要和提取内容。之后每次聊天，可能根据你的问题从已保存正文中检索每份来源最多 3 段；当前对话的所有来源合计最多 8 段、3200 字（含来源标注），连同问题及必要上下文发送给当前模型服务；无匹配时不发送检索片段，但摘要等其他上下文仍可能发送。可移除当前对话来源以停止使用。";

  function feishuPreviewMarkup(data) {
    const body = data?.preview;
    if (typeof body !== 'string' || !data.preview_id || !Number.isSafeInteger(data.length) ||
        !Number.isSafeInteger(data.extracted_length) || typeof data.truncated !== 'boolean' ||
        [...body].length !== data.length || data.extracted_length < data.length ||
        data.truncated !== (data.extracted_length > data.length)) {
      throw new Error('正文预览不完整，请更新本机服务后重新读取，再确认接入。');
    }
    const scope = data.truncated
      ? `已提取 ${data.extracted_length} 字，以下为将保留的前 ${data.length} 字；其余内容不会接入。`
      : `以下为将保留的全部 ${data.length} 字。`;
    return `<p class="note">${esc(scope)}</p><div class="feishu-full-preview" role="region" aria-label="将接入的飞书正文，可滚动查看" tabindex="0">${esc(body)}</div>`;
  }

  function readableFeishuUrl(value) {
    try { const u = new URL(value); return u.protocol === "https:" && /^\/(?:docx|docs|wiki)\/[^/]+/.test(u.pathname); }
    catch (_) { return false; }
  }

  const state = {
    session: null,
    messages: [],
    memories: [],
    bookmark: null,
    nextStep: null,
    context: null,
    realSource: null,
    bmSource: {},
    memes: [],
    tab: "understanding",
  };

  const els = {
    onboarding: $("#onboarding"),
    app: $("#app"),
    messages: $("#messages"),
    input: $("#input"),
    composer: $("#composer"),
    understandingFacts: $("#understanding-facts"),
    understandingInferences: $("#understanding-inferences"),
    understandingQuestions: $("#understanding-questions"),
    memoryList: $("#memory-list"),
    bookmarkCard: $("#bookmark-card"),
    auditList: $("#audit-list"),
    stateLabel: $("#state-label"),
    stateHint: $("#state-hint"),
    orb: $("#orb"),
    sourceLabel: $("#source-label"),
    sessionMeta: $("#session-meta"),
    modal: $("#modal"),
    bmNote: $("#bm-note"),
    bmChoice: $("#bm-choice"),
    bmNext: $("#bm-next"),
    toast: $("#toast"),
  };

  const stateCopy = {
    listening: ["安静陪着", "同一条对话，接着说就好"],
    thinking: ["正在整理回复", "需要一点时间"],
    responding: ["回复已到", "你可以继续说"],
    quiet: ["安静陪着你", "需要的时候再叫我"],
    failed: ["未完成", "先核对下方提示"],
  };

  let personaOptions = [];
  let personaRequest = 0;
  function personaName(id) { return personaOptions.find(item => item.id === id)?.name || (id === "whale" ? "小鲸鱼" : "念响"); }
  function updatePersonaLabels() {
    const name = personaName(state.session?.persona_id || "nianxiang");
    const title = $("#conversation-persona-name");
    if (title) title.textContent = name;
    document.title = `${name} · 具身个人伙伴`;
  }
  async function loadPersonaPicker() {
    const mount = $("#persona-picker");
    if (!mount || !state.session) return;
    const request = ++personaRequest, sid = state.session.id;
    try {
      const data = await api("/api/personas");
      if (request !== personaRequest || state.session?.id !== sid) return;
      personaOptions = (data.personas || []).filter(item => ["nianxiang", "whale"].includes(item.id));
      const selected = state.session.persona_id || data.default_persona || "nianxiang";
      mount.innerHTML = `<div class="k">当前伙伴</div><p class="note">可以随时切换，聊天、记忆和语气偏好都会保留。</p><div class="persona-options" role="radiogroup" aria-label="选择聊天伙伴">${personaOptions.map(item => `<button type="button" class="persona-option ${item.id === selected ? "is-selected" : ""}" data-persona-id="${esc(item.id)}" role="radio" aria-checked="${item.id === selected}"><span><b>${esc(item.name)}</b><small>${esc(item.description || "")}</small><em>${(item.tags || []).map(tag => esc(tag)).join(" · ")}</em></span><span class="persona-check" aria-hidden="true">${item.id === selected ? "✓" : ""}</span></button>`).join("")}</div>`;
      mount.querySelectorAll("[data-persona-id]").forEach(button => button.onclick = async () => {
        const next = button.dataset.personaId;
        if (!next || next === (state.session?.persona_id || "nianxiang") || button.disabled) return;
        button.disabled = true;
        try {
          const result = await api(`/api/session/${encodeURIComponent(sid)}/persona`, {method: "PUT", body: JSON.stringify({persona_id: next})});
          if (state.session?.id !== sid) return;
          state.session = result.session || result;
          if (typeof updatePersonaLabels === "function") updatePersonaLabels();
          if (typeof loadPersonaPicker === "function") loadPersonaPicker();
          renderMessages();
          toast(`已切换为${personaName(next)}`);
        } catch (error) { button.disabled = false; toast(error.message || "切换伙伴失败"); }
      });
      if (typeof updatePersonaLabels === "function") updatePersonaLabels();
    } catch (error) { if (request === personaRequest && state.session?.id === sid) mount.innerHTML = `<p class="note">暂时无法读取伙伴设置：${esc(error.message)}</p>`; }
  }

  let contentMutationEpoch = 0, contentMutationCount = 0;
  async function api(path, opts = {}) {
    const mutating = !['GET', 'HEAD'].includes(String(opts.method || 'GET').toUpperCase());
    if (mutating) { contentMutationEpoch++; contentMutationCount++; }
    try {
      const res = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...opts});
      if (!res.ok) {
        let payload = {};
        try { payload = await res.json(); } catch (_) {}
        const error = new Error(typeof payload.detail === 'string' ? payload.detail : `请求失败（${res.status}）`);
        error.status = res.status; error.code = payload.error_code; error.currentVersion = payload.current_version;
        throw error;
      }
      return await res.json();
    } finally {
      if (mutating) { contentMutationEpoch++; contentMutationCount--; }
    }
  }

  function toast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => els.toast.classList.remove("show"), 2600);
  }

  document.addEventListener("xinji-space-sync-error", (event) => {
    toast(event.detail?.error?.message || "当前人格和陪伴方式未能同步，请检查服务连接后重试。");
  });

  function setOrb(stateName) {
    els.orb.dataset.state = stateName;
    document.documentElement.dataset.presenceState = stateName;
    window.xinjiDesktop?.updateState?.({state: ["quiet","listening","thinking","responding"].includes(stateName) ? stateName : "quiet"});
    const [label, hint] = stateCopy[stateName] || stateCopy.listening;
    els.stateLabel.textContent = label;
    els.stateHint.textContent = hint;
  }

  const followups = window.XinjiFollowups.create({api, getSessionId: () => state.session?.id});
  const mood = window.XinjiMood?.create({api, surface:"web", getSessionId: () => state.session?.id, onContext:putMoodIntoChat});
  function putMoodIntoChat(text) {
    if (typeof text !== "string" || !text || !state.session) return;
    if (!els.input.value.includes(text)) els.input.value = els.input.value.trim() ? els.input.value + "\n\n" + text : text;
    window.XinjiComposerDraft?.save(); keepChatDraft(); setDesignPanel(false); els.input.focus(); toast("已放到输入框，由你决定是否发送。");
  }
  state.followupReminder = window.XinjiFollowups.startReminder({api, getSessionId: () => state.session?.id});
  state.companionBoundary = window.XinjiCompanionBoundary?.create({api, getSessionId: () => state.session?.id, host:document.querySelector("[data-companion-boundary]")});
  void window.XinjiVoice.configure({api});

  // Explicit, temporary device opt-in. Readings stay in the page only.
  let mindlinkToken = null;
  let mindlinkTimer = null;
  let mindlinkExpiryTimer = null;
  let mindlinkController = null;
  let mindlinkStarting = false;
  let mindlinkGeneration = 0;
  const MINDLINK_MAX_AGE_MS = 2500;
  const MINDLINK_REQUEST_TIMEOUT_MS = 2000;
  const mindlinkUnavailable = "信号暂不可用，请检查设备连接和佩戴。";

  function clearMindlinkReading(message) {
    clearTimeout(mindlinkExpiryTimer);
    mindlinkExpiryTimer = null;
    $("#mindlink-status").textContent = message;
  }

  async function releaseMindlinkToken(token) {
    if (!token) return;
    try {
      await fetch("/api/mindlink/stop", {method: "POST", keepalive: true,
        headers: {"Content-Type": "application/json", "X-MindLink-Token": token}, body: "{}"});
    } catch (_) {}
  }

  async function stopMindlink() {
    const token = mindlinkToken;
    mindlinkToken = null;
    mindlinkGeneration++;
    clearTimeout(mindlinkTimer);
    mindlinkController?.abort();
    mindlinkController = null;
    clearMindlinkReading("已停止读取");
    $("#mindlink-toggle").textContent = "同意并开启读取";
    await releaseMindlinkToken(token);
  }

  async function pollMindlink(generation) {
    if (!mindlinkToken || generation !== mindlinkGeneration || document.hidden) return;
    const token = mindlinkToken;
    const started = performance.now();
    const controller = new AbortController();
    mindlinkController = controller;
    const timeout = setTimeout(() => controller.abort(), MINDLINK_REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch("/api/mindlink/state", {method: "POST", signal: controller.signal,
        headers: {"Content-Type": "application/json", "X-MindLink-Token": token}, body: "{}"});
      if (!mindlinkToken || generation !== mindlinkGeneration || document.hidden) return;
      if (response.status === 403) {
        void stopMindlink();
        $("#mindlink-status").textContent = "授权已结束，请重新开启。";
        return;
      }
      if (!response.ok) throw new Error("MindLink request failed");
      const reading = await response.json();
      if (!mindlinkToken || generation !== mindlinkGeneration || document.hidden) return;
      if (controller.signal.aborted) throw new Error("MindLink request timed out");
      const elapsed = Math.max(0, performance.now() - started);
      const remaining = MINDLINK_MAX_AGE_MS - reading.age_ms - elapsed;
      if (reading.available === true && Number.isFinite(reading.score) && reading.score >= 1 && reading.score <= 100 &&
          Number.isFinite(reading.age_ms) && reading.age_ms >= 0 && remaining > 0) {
        clearMindlinkReading(`设备专注反馈：${Math.round(reading.score)}（设备估计值）`);
        mindlinkExpiryTimer = setTimeout(() => clearMindlinkReading(mindlinkUnavailable), remaining);
      } else {
        clearMindlinkReading(mindlinkUnavailable);
      }
    } catch (_) {
      if (!mindlinkToken || generation !== mindlinkGeneration || document.hidden) return;
      clearMindlinkReading(mindlinkUnavailable);
    } finally {
      clearTimeout(timeout);
      if (mindlinkController === controller) mindlinkController = null;
    }
    if (mindlinkToken && generation === mindlinkGeneration && !document.hidden) {
      mindlinkTimer = setTimeout(() => pollMindlink(generation), 1200);
    }
  }

  function mindlinkVisibilityChanged() {
    if (!mindlinkToken && !mindlinkStarting) return;
    if (document.hidden) {
      mindlinkGeneration++;
      clearTimeout(mindlinkTimer);
      mindlinkController?.abort();
      mindlinkController = null;
      clearMindlinkReading(mindlinkToken ? "页面已隐藏，已暂停显示设备读数。" : "页面已切换，开启已取消；请返回后重新开启。");
    } else if (mindlinkToken) {
      clearMindlinkReading("正在检查设备连接…");
      pollMindlink(mindlinkGeneration);
    }
  }

  async function toggleMindlink() {
    if (mindlinkToken) return stopMindlink();
    const button = $("#mindlink-toggle");
    const requestedGeneration = ++mindlinkGeneration;
    mindlinkStarting = true;
    const controller = new AbortController();
    mindlinkController = controller;
    const timeout = setTimeout(() => controller.abort(), MINDLINK_REQUEST_TIMEOUT_MS);
    button.disabled = true;
    try {
      const result = await api("/api/mindlink/start", {method: "POST", signal: controller.signal, body: JSON.stringify({consent: true})});
      if (requestedGeneration !== mindlinkGeneration || document.hidden || controller.signal.aborted) {
        await releaseMindlinkToken(result.token);
        return;
      }
      if (typeof result.token !== "string" || !result.token) throw new Error("授权响应无效");
      mindlinkToken = result.token;
      button.textContent = "停止读取";
      $("#mindlink-status").textContent = "正在检查设备连接…";
      pollMindlink(requestedGeneration);
    } catch (e) {
      if (requestedGeneration === mindlinkGeneration) $("#mindlink-status").textContent = "无法开启：" + e.message;
    } finally {
      clearTimeout(timeout);
      if (mindlinkController === controller) mindlinkController = null;
      mindlinkStarting = false;
      button.disabled = false;
    }
  }

  // ---------------- onboarding wizard ----------------
  const wizard = { connector: null, read: null };

  const connectionIntro = window.XinjiConnectionIntro.create({api, host: $("#connection-intro"),
    getSessionId: () => state.session?.id,
    canApply: () => !activeTurn && !state.delivery?.pending() && !queuedTurns.length && !turnQueue.length && !contentMutationCount && !state.attachingSource && !state.revokingSource && !state.confirmingSource,
    revision: () => `${state.session?.id}:${contentMutationEpoch}:${sourceUiEpoch}:${state.messages.length}`,
    apply: data => {
      state.session = data.session; state.messages = data.messages; state.memories = data.memories;
      state.context = data.context || null; state.bookmark = data.bookmark || null;
      renderMessages(); renderConnectedSources(); window.XinjiConnectionIntro.syncBadges(document, state.context);
    }});
  function finishConnection(data) {
    closeSourceDialog(); window.XinjiConnectionIntro.syncBadges(document, state.context);
    if (window.innerWidth < 1200 && !window.xinjiDesktop) setDesignPanel(false);
    connectionIntro.start(data?.intro); els.input?.focus();
  }
  async function beginConnectionIntro(sourceId) {
    const sid = state.session?.id;
    if (!sid) return;
    const data = await api('/api/connections/intro', {method:'POST', body:JSON.stringify({session_id:sid,source_id:sourceId})});
    if (state.session?.id !== sid) return;
    closeSourceDialog(); connectionIntro.start(data.intro || data); els.input?.focus();
  }
  function showConnectedSource(id, meta) {
    $("#wz-read").classList.add('is-hidden');
    $("#read-items").innerHTML = ''; $("#read-scope").innerHTML = '';
    $("#read-head").innerHTML = `<div class="connection-card"><div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">${esc(meta?.icon || '✓')}</span><h3>${esc(meta?.name || '已连接')}</h3></div><p class="connection-value">✓ 已连接，可以接着聊了。</p><p class="connection-scope">需要时会参考已接入的内容。你可以在资料管理里移除。</p><button type="button" class="btn primary" id="connection-return">回到聊天</button><button type="button" class="text-btn" id="connection-manage">管理资料</button></div>`;
    $("#connection-return").onclick = closeSourceDialog;
    $("#connection-manage").onclick = () => { closeSourceDialog(); switchTab('data'); };
    showWz(3);
  }


  // A closed or replaced credential form must never accept a late response.
  const credentialPendingKey = "xinji_source_creation_pending";
  // Record before sending: an interrupted request may already have created a session.
  function credentialPendingIds() {
    try { const ids = JSON.parse(localStorage.getItem(credentialPendingKey) || "[]"); return Array.isArray(ids) ? ids.filter(id => typeof id === "string") : []; }
    catch (_) { return []; }
  }
  function renderCredentialPendingNotice() {
    $("#source-uncertain-notice")?.classList.toggle("is-hidden", credentialPendingIds().length === 0);
  }
  function markCredentialStart() {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const ids = credentialPendingIds(); ids.push(id);
    try { localStorage.setItem(credentialPendingKey, JSON.stringify(ids)); } catch (_) {}
    return id;
  }
  function finishCredentialStart(id) {
    const remaining = credentialPendingIds().filter(value => value !== id);
    try { if (remaining.length) localStorage.setItem(credentialPendingKey, JSON.stringify(remaining)); else localStorage.removeItem(credentialPendingKey); } catch (_) {}
    renderCredentialPendingNotice();
  }
  let credentialGeneration = 0;
  let credentialController = null;
  function clearCredentialForms() {
    credentialGeneration++;
    credentialController?.abort();
    credentialController = null;
    renderCredentialPendingNotice();
    for (const selector of ["#wz-gmail-password", "#wz-notion-token"]) {
      const input = $(selector);
      if (input) input.value = "";
    }
    for (const selector of ["#wz-gmail-result", "#wz-notion-result"]) {
      const result = $(selector);
      if (result) { result.innerHTML = ""; result.classList.add("is-hidden"); }
    }
  }
  function beginCredentialRequest() {
    credentialController?.abort();
    credentialController = new AbortController();
    return {generation: ++credentialGeneration, controller: credentialController};
  }
  function credentialRequestCurrent(request) {
    return request.generation === credentialGeneration && !request.controller.signal.aborted;
  }

  function showWz(n) {
    els.onboarding.classList.toggle("connection-compact", n === 3);
    if (n !== 3) clearCredentialForms();
    [1, 2, 3, 4].forEach((i) => $(`#wz-${i}`)?.classList.toggle("is-hidden", i !== n));
    $$(".steps span").forEach((s) => s.classList.toggle("on", Number(s.dataset.step) === n));
  }

  async function loadCatalog() { return loadRealSources(); }

  async function readFeishuAccountState() {
    const sid = state.session?.id;
    if (!sid) return;
    try {
      const data = await api(`/api/lark/account?session_id=${encodeURIComponent(sid)}`);
      if (state.session?.id === sid) state.feishuAccount = data;
    } catch (_) { if (state.session?.id === sid) state.feishuAccount = null; }
  }

  async function loadRealSources(force = false) {
    const list = $("#reco-list");
    list.innerHTML = `<p class="muted">正在看看有哪些可用的来源…</p>`;
    try {
      const [d] = await Promise.all([api(`/api/onboarding/sources${force ? "?force=1" : ""}`), readFeishuAccountState()]);
      renderRealSources(d.sources || []);
    } catch (e) {
      list.innerHTML = `<p class="note">读取失败：${esc(e.message)}</p>`;
    }
  }

  const STATUS_LABEL = { ready: "可用", needs_click: "需系统权限", needs_config: "需配置", needs_auth: "需授权", needs_install: "需安装", unavailable: "暂不可用", empty: "没有可读内容" };

  function renderRealSources(sources) {
    const list = $("#reco-list");
    if (!sources.length) { list.innerHTML = `<p class="note">本机没有可连接的真实来源。</p>`; return; }
    list.innerHTML = sources.map((s) => `<div class="connector-card real-source" data-real-card="${s.id}">
      <div class="connector-icon">${esc(s.icon)}</div>
      <div class="connector-body">
        <b>${esc(s.name)}</b> <span class="muted">· ${esc(s.kind)}</span>
        <span class="tag synthetic" style="margin-left:6px" ${s.id === "feishu" ? "data-feishu-account-status" : `data-connection-source="${esc(s.id)}" data-connection-idle="${esc(STATUS_LABEL[s.status] || s.status)}"`}>${esc(s.id === "feishu" ? window.XinjiFeishuAccountPicker.statusLabel(state.feishuAccount) : window.XinjiConnectionIntro.connected(state.context,s.id) ? "✓ 已连接" : STATUS_LABEL[s.status] || s.status)}</span>
        <p>${esc(s.id === "apple_calendar" ? "过去 7 天的日程" : s.id === "apple_reminders" ? "最近 7 天有更新的提醒" : s.blurb)} · ${esc(s.id === "feishu" ? "连接后按问题自动查找有权访问的文档" : s.hint || "")}</p>
      </div>
      <button class="btn ghost small" data-real="${s.id}" ${s.id === "feishu" ? "data-feishu-account-control" : `data-connection-control="${esc(s.id)}" data-connection-idle="连接"`} >${s.id === "feishu" ? state.feishuAccount?.enabled ? "管理连接" : "连接" : s.id === "git" ? "选择目录" : s.status === "needs_auth" ? "去授权" : s.status === "needs_config" ? "配置" : s.status === "needs_install" || s.status === "unavailable" ? "查看" : "连接"}</button>
    </div>`).join("");
    list.querySelectorAll("[data-real]").forEach((b) => {
      b.onclick = () => openRealSource(b.dataset.real, sources.find((x) => x.id === b.dataset.real));
    });
  }

  async function openRealSource(id, meta) {
    clearCredentialForms();
    state.realSource = null;
    wizard.pendingSource = null;
    $("#wz-read").classList.remove("is-hidden");
    $("#wz-read").textContent = "开始读取";
    $("#wz-3 > .section-label").textContent = "将读取（仅这些）";
    $("#read-items").innerHTML = "";
    $("#read-scope").innerHTML = "";
    $("#read-head").innerHTML = `<div class="connector-card"><div class="connector-icon">${esc(meta?.icon || "•")}</div>
      <div class="connector-body"><b>${esc(meta?.name || id)}</b><span class="muted"> · 真实只读</span>
      <p>${esc(meta?.hint || "")}</p></div></div>`;

    if (id !== "feishu" && window.XinjiConnectionIntro.connected(state.context, id)) { showConnectedSource(id, meta); return; }
    if (id === "local_files") { openLocalFiles(); return; }
    if (id === "waytoagi" || id === "jike") { openPublicSource(id); return; }
    if (id === "git") { renderGitPicker(); return; }
    if (id === "feishu") { renderFeishuAccount(); return; }
    if (id === "notion") { $("#wz-read").classList.add("is-hidden"); renderNotionReal(); showWz(3); return; }
    if (id === "gmail") { $("#wz-read").classList.add("is-hidden"); renderGmailReal(); showWz(3); return; }
    if (id === "github" && ["needs_auth", "needs_install"].includes(meta?.status)) {
      $("#wz-read").classList.add("is-hidden");
      $("#read-head").insertAdjacentHTML("beforeend", `<p class="note">${esc(meta.hint || "请先在终端完成 GitHub CLI 登录。")}</p><button class="btn ghost small" id="wz-github-recheck">我已处理，重新检查</button>`);
      globalThis.XinjiConnectorAuth?.mount($("#read-head"), "github");
      $("#wz-github-recheck").onclick = async () => {
        const button = $("#wz-github-recheck");
        const request = beginCredentialRequest();
        button.disabled = true;
        try {
          const d = await api("/api/onboarding/sources?force=1", { signal: request.controller.signal });
          if (!button.isConnected || !credentialRequestCurrent(request)) return;
          const current = d.sources.find((s) => s.id === "github");
          if (!current) throw Error("GitHub 来源状态暂不可用");
          openRealSource("github", current);
        } catch (e) { if (button.isConnected && credentialRequestCurrent(request)) { button.disabled = false; toast(e.message); } }
      };
      showWz(3);
      return;
    }

    wizard.pendingSource = id;
    const scope = id === 'apple_calendar' ? '只读过去 7 天的日程，相关片段会发送给当前模型。'
      : id === 'apple_reminders' ? '只读最近 7 天相关提醒；可用时间范围以实际读取结果为准，相关片段会发送给当前模型。'
      : '只读当前来源支持的内容，相关片段会发送给当前模型。';
    $("#read-head").innerHTML = `<div class="connection-card"><div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">${esc(meta?.icon || '▦')}</span><h3>连接${esc(meta?.name || id)}</h3></div><p class="connection-value">陪你看看最近发生的事，找到此刻值得聊的一件。</p><p class="connection-scope">${esc(scope)}</p></div>`;
    $("#read-items").innerHTML = '';
    $("#wz-read").textContent = "授权";
    $("#wz-read").disabled = false;
    showWz(3);
  }

  function renderGitPicker() {
    clearCredentialForms();
    const initialSession = state.session?.id || null;
    state.realSource = null;
    wizard.pendingSource = null;
    $("#wz-read").classList.add("is-hidden");
    $("#read-items").innerHTML = "";
    $("#read-scope").innerHTML = "";
    $("#read-head").innerHTML = `<div class="real-lark connection-card"><div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">git</span><h3>连接代码库</h3></div>
      <p class="note">填写运行念响的电脑上的代码库完整目录。只读所选代码库最近最多 8 条提交；相关内容会发送给当前模型。</p>
      <p class="note">授权后直接回到聊天。</p>
      <label>代码库目录<input id="wz-git-path" type="text" autocomplete="off" spellcheck="false" placeholder="例如 C:\\Users\\你的用户名\\Projects\\my-project 或 ~/Projects/my-project" /></label>
      <button class="btn primary small" id="wz-git-preview">授权</button><p class="note" id="wz-git-hint" role="status">也支持 ~/Projects/my-project；填写目录路径即可，不要输入终端命令。</p></div>`;
    const input = $("#wz-git-path"), button = $("#wz-git-preview"), hint = $("#wz-git-hint");
    input.oninput = () => { clearCredentialForms(); $("#read-items").innerHTML = ""; hint.textContent = "目录已更改，请重新读取。"; button.disabled = false; };
    button.onclick = async () => {
      const path = input.value.trim();
      if (!path) { hint.textContent = "请先填写代码库的完整目录。"; return; }
      if (button.disabled) return;
      const request = beginCredentialRequest();
      button.disabled = true;
      $("#read-items").innerHTML = "";
      hint.textContent = "正在读取所选代码库…";
      try {
        const result = await api("/api/onboarding/real/read", {method: "POST", signal: request.controller.signal, body: JSON.stringify({source_id: "git", path, start_intro:true})});
        if (!credentialRequestCurrent(request) || input.value.trim() !== path || (state.session?.id || null) !== initialSession) return;
        if (!result.ok || !result.preview_id || !Array.isArray(result.items)) {
          hint.textContent = [result.error || "读取失败", result.hint].filter(Boolean).join(" · "); return;
        }
        $("#read-items").classList.add("connection-auto-snapshot");
        $("#read-items").innerHTML = `<p class="note">实际代码库：${esc(result.selected_path || path)} · ${result.items.length} 条提交</p>` + result.items.map(item =>
          `<div class="read-item"><b>${esc(item.title)}</b><span>${esc(item.meta)} · ${esc(item.summary)}</span></div>`).join("") +
          `<button class="btn primary small" id="wz-git-use">核对这些提交并继续</button>`;
        hint.textContent = "请核对快照，也可以修改目录后重新读取。预览 10 分钟内有效。";
        $("#wz-git-use").onclick = () => {
          if (!credentialRequestCurrent(request) || input.value.trim() !== path || (state.session?.id || null) !== initialSession) return;
          state.realSource = {id: "git", read: result, sessionId: initialSession};
          wizard.read = result;
          wizard.connector = result.connector;
          return startRealSource();
        };
        await $("#wz-git-use").onclick();
      } catch (error) { if (credentialRequestCurrent(request)) hint.textContent = `读取失败：${error.message}；可修改目录后重试。`; }
      finally { if (credentialRequestCurrent(request)) button.disabled = false; }
    };
    showWz(3);
  }

  function openPublicSource(id) {
    $("#wz-read").classList.add("is-hidden");
    const sid = state.session?.id || null;
    const request = beginCredentialRequest();
    window.XinjiPublicLinkPicker.mount($("#read-head"), {
      sourceId: id, api, autoAttach: true,
      isCurrent: () => credentialRequestCurrent(request) && (state.session?.id || null) === sid,
      onConfirm: async (read) => {
        if (!credentialRequestCurrent(request) || (state.session?.id || null) !== sid || state.attachingSource || state.revokingSource || state.confirmingSource || activeTurn || queuedTurns.length || turnQueue.length) throw Error("对话正在更新，请稍后重新读取。");
        state.attachingSource = true;
        try {
          const data = await api('/api/onboarding/real/start', {method:'POST',body:JSON.stringify({source_id:id, preview_id:read.preview_id, session_id:sid, start_intro:true})});
          if (!data?.session || (sid && data.session.id !== sid)) throw Error('接入结果未确认');
          if (credentialRequestCurrent(request) && (state.session?.id || null) === sid) { enterSession(data, {skipIntro:true}); toast('公开正文已接入当前对话'); }
        } finally { state.attachingSource = false; }
      }
    });
    showWz(3);
  }

  function openLocalFiles() {
    clearCredentialForms();
    $("#wz-read").classList.add("is-hidden");
    $("#read-items").innerHTML = "";
    $("#read-scope").innerHTML = "";
    const head = $("#read-head");
    const initialSession = state.session?.id || null;
    const request = beginCredentialRequest();
    window.XinjiFilePicker.mount(head, {sessionId: initialSession, autoAttach: true, isCurrent: () => credentialRequestCurrent(request), onConfirm: async (files, sid) => {
      if (!credentialRequestCurrent(request) || (state.session?.id || null) !== sid || activeTurn || queuedTurns.length || turnQueue.length) {
        const e = new Error("对话状态已变化或消息仍在发送，请稍后重新核对所选资料。"); e.status = 409; throw e;
      }
      state.attachingSource = true;
      try {
        const d = await api("/api/local-files/confirm", {method: "POST", body: JSON.stringify({session_id: sid, files, start_intro:true})});
        if (!d?.session || (sid && d.session.id !== sid)) throw Error("接入结果未确认");
        if (!credentialRequestCurrent(request) || (state.session?.id || null) !== (sid || null)) { connectionIntro.start(d.intro); return; }
        enterSession(d, {skipIntro: true}); toast("已接入当前对话");
      } finally { state.attachingSource = false; }
    }});
    showWz(3);
  }

  async function readConfirmedSource() {
    const id = wizard.pendingSource;
    const button = $("#wz-read");
    if (!id || button.disabled) return;
    const sessionId = state.session?.id || null;
    const request = beginCredentialRequest();
    let uncertain = false, pendingKey = null;
    button.disabled = true; button.textContent = "连接中…";
    $("#read-scope").textContent = "正在读取，若出现系统权限窗口，请完成后稍等。";
    try {
      const read = await api('/api/onboarding/real/read', {method:'POST', signal:request.controller.signal, body:JSON.stringify({source_id:id,read_window:'recent7',start_intro:true})});
      if (!credentialRequestCurrent(request)) return;
      if (!read.ok || !read.preview_id) throw Error([read.error || '读取失败', read.hint].filter(Boolean).join(' · '));
      if ((state.session?.id || null) !== sessionId || state.attachingSource || state.revokingSource || state.confirmingSource || activeTurn || queuedTurns.length || turnQueue.length) throw Error('对话正在更新，请稍后重新授权。');
      state.attachingSource = true;
      pendingKey = markCredentialStart();
      uncertain = true;
      const data = await api('/api/onboarding/real/start', {method:'POST',body:JSON.stringify({source_id:id,preview_id:read.preview_id,session_id:sessionId,start_intro:true})});
      if (!data?.session || (sessionId && data.session.id !== sessionId)) throw Error('接入结果尚未确认');
      uncertain = false; finishCredentialStart(pendingKey);
      if (!credentialRequestCurrent(request) || (state.session?.id || null) !== sessionId) return;
      wizard.pendingSource = null;
      enterSession(data, {skipIntro:true});
    } catch (error) {
      if (error.status >= 400 && error.status < 500) { uncertain = false; if (pendingKey) finishCredentialStart(pendingKey); }
      if (credentialRequestCurrent(request)) $("#read-scope").textContent = uncertain ? '连接结果尚未确认，请返回聊天后核对连接状态。' : error.message;
    } finally {
      state.attachingSource = false;
      if (credentialRequestCurrent(request)) { button.disabled = uncertain; button.textContent = uncertain ? '请先核对连接状态' : '授权'; }
    }
  }

  async function startRealSource(editFirst = false) {
    if (!state.realSource) { toast("请先选择并核对一份真实来源。"); return; }
    const selected = state.realSource;
    const id = selected.id;
    const sid = selected.sessionId;
    if ((state.session?.id || null) !== sid || state.attachingSource || state.revokingSource || state.confirmingSource || activeTurn || queuedTurns.length || turnQueue.length) { toast("对话状态已变化或消息仍在发送，请稍后重新核对。"); return; }
    state.attachingSource = true;
    try {
      const d = await api("/api/onboarding/real/start", { method: "POST", body: JSON.stringify({ source_id: id, start_intro:true, preview_id: state.realSource.read.preview_id, ...(sid ? {session_id:sid} : {}) }) });
      if (!d || !d.session) { toast(d?.detail || "接入失败"); return; }
      if (sid && d.session.id !== sid) throw Error("接入返回的记录不匹配，请重新核对；当前对话没有切换。");
      if (state.realSource !== selected || (state.session?.id || null) !== (sid || null)) { connectionIntro.start(d.intro); return; }
      enterSession(d, { skipIntro: true });
      if (editFirst) setTimeout(() => switchTab("understanding"), 500);
    } catch (e) { toast(e.message); }
    finally { state.attachingSource = false; }
  }

  async function chooseConnector(connector) {
    const data = await api("/api/onboarding/sources");
    const source = (data.sources || []).find(item => item.id === connector.id);
    if (!source) { toast("此来源当前不可用，没有读取资料。"); return; }
    prepareSourceDialog();
    await openRealSource(source.id, source);
  }

  async function confirmFeishuPreview(url, previewId, hint, button) {
    if (button.disabled) return;
    if (activeTurn || queuedTurns.length || turnQueue.length) {
      hint.textContent = "对话消息还在发送，请等回复完成后再接入文档。";
      return;
    }
    button.disabled = true;
    state.attachingSource = true;
    hint.textContent = state.session ? "正在接入当前对话…" : "正在创建对话…";
    const sid = state.session?.id;
    try {
      const endpoint = sid ? "/api/lark/attach" : "/api/lark/start";
      const body = sid ? {session_id: sid, url, preview_id: previewId, start_intro:true} : {url, preview_id: previewId, start_intro:true};
      const data = await api(endpoint, {method: "POST", body: JSON.stringify(body)});
      if (!data?.session || (sid && data.session.id !== sid)) throw new Error("响应无效");
      if ((state.session?.id || null) !== (sid || null)) { toast("资料已接入原对话，请在历史中查看。"); return; }
      enterSession(data, {skipIntro: true});
      toast("已接入当前对话");
    } catch (e) {
      if (e.status === 409) {
        hint.textContent = e.message;
        button.disabled = false;
      } else if (e.status === 400) {
        hint.textContent = "读取预览已失效，请重新读取并确认文档。";
      } else {
        hint.textContent = "接入结果未确认。请返回对话并刷新，确认是否已接入；如未接入请重新预览。";
      }
    } finally {
      state.attachingSource = false;
    }
  }

  function renderRealLark() {
    let previewVersion = 0;
    const head = $("#read-head");
    head.querySelector(".real-lark")?.remove();
    head.insertAdjacentHTML("beforeend", `
      <div class="real-lark">
        <div class="mem-group-label" style="margin-top:12px"><span>或者：真实飞书文档（只读）</span><span class="muted">lark-cli</span></div>
        <input id="wz-lark-url" placeholder="粘贴一篇飞书文档链接（https://…/docx/…）" />
        <div class="lark-actions">
          <button class="btn ghost small" id="wz-lark-preview">读取真实文档</button>
          <span class="note" id="wz-lark-hint">只读取你指定的这一篇；提取正文后保留最多 12000 字。需先授权 lark-cli。</span>
        </div>
        <div id="wz-lark-result" class="lark-preview is-hidden"></div>
      </div>`);
    const input = $("#wz-lark-url");
    $("#wz-lark-preview").onclick = async () => {
      const version = ++previewVersion;
      const url = $("#wz-lark-url").value.trim();
      const hint = $("#wz-lark-hint");
      $("#wz-lark-result").classList.add("is-hidden");
      if (!url) { hint.textContent = "先粘贴文档链接"; return; }
      hint.textContent = "读取中…";
      try {
        const d = await api("/api/lark/preview", { method: "POST", body: JSON.stringify({ url }) });
        if (version !== previewVersion || $("#wz-lark-url") !== input || input.value.trim() !== url) return;
        if (!d.ok) { hint.textContent = `${d.error || "读取失败"}${d.hint ? " · " + d.hint : ""}`; return; }
        const box = $("#wz-lark-result");
        const markup = feishuPreviewMarkup(d);
        box.classList.remove("is-hidden");
        box.innerHTML = `<h4>${esc(d.title)}</h4>${markup}
          <div class="meta"><span>提取后保留 ${d.length} 字 · identity=${esc(d.identity)}</span><span>只读 · 单篇</span></div>
          <p class="note">${feishuDisclosure}</p><button class="btn primary small" id="wz-lark-start" style="margin-top:10px">${state.session ? "确认接入当前对话" : "确认并开始"}</button>`;
        $("#wz-lark-start").onclick = () => {
          if ($("#wz-lark-url") !== input || input.value.trim() !== url) { hint.textContent = "链接已更改，请重新读取并确认。"; return; }
          return confirmFeishuPreview(url, d.preview_id, hint, $("#wz-lark-start"));
        };
        hint.textContent = "确认后开始；之后可随时撤回来源。";
      } catch (e) { if (version === previewVersion) hint.textContent = e.message; }
    };
  }

  function renderGmailReal() {
    clearCredentialForms();
    const initialSession = state.session?.id || null;
    const head = $("#read-head");
    head.innerHTML = `<div class="real-gmail real-lark connection-card">
      <div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">M</span><h3>连接 Gmail</h3></div>
      <p class="connection-value">看看最近的未读消息，一起理清在意的事。</p>
      <p class="connection-scope">只读最近 5 封未读邮件的主题、发件人和日期，必要内容会发送给当前模型。应用专用密码仅本次使用。</p>
      <label>连接方式<select id="wz-gmail-method"><option value="cli">Google 官方登录</option><option value="imap">应用专用密码（备用）</option></select></label>
      <input id="wz-gmail-address" placeholder="Gmail 地址" autocomplete="off" />
      <input id="wz-gmail-password" type="password" autocomplete="off" placeholder="应用专用密码" />
      <button class="btn primary small" id="wz-gmail-preview">授权</button>
      <p class="connection-status" id="wz-gmail-hint" role="status"></p>
      <div id="wz-gmail-result" class="lark-preview is-hidden" hidden></div></div>`;
    globalThis.XinjiConnectorAuth?.mount(head.querySelector(".real-gmail"), "gmail");
    $("#wz-gmail-method").onchange = () => {
      const cli = $("#wz-gmail-method").value === "cli";
      $("#wz-gmail-address").disabled = cli;
      $("#wz-gmail-password").disabled = cli;
      $("#wz-gmail-password").value = "";
      $("#wz-gmail-result").classList.add("is-hidden");
      $("#wz-gmail-result").innerHTML = "";
      $("#wz-gmail-hint").textContent = cli ? "先连接 Google 账号，再读取最近最多 5 封未读邮件头。" : "填写地址和应用专用密码；仅本次请求使用。";
    };
    $("#wz-gmail-method").onchange();
    $("#wz-gmail-preview").onclick = async () => {
      const authorizeButton = $("#wz-gmail-preview");
      if (authorizeButton.disabled) return;
      const method = $("#wz-gmail-method").value;
      const address = $("#wz-gmail-address").value.trim();
      const password = $("#wz-gmail-password").value.trim();
      const hint = $("#wz-gmail-hint");
      if (method !== "cli" && (!address || !password)) { hint.textContent = "地址和应用专用密码都要填"; return; }
      authorizeButton.disabled = true;
      $("#wz-gmail-result").classList.add("is-hidden");
      $("#wz-gmail-result").innerHTML = "";
      hint.textContent = "读取中…";
      const request = beginCredentialRequest();
      $("#wz-gmail-password").value = "";
      try {
        const d = await api("/api/gmail/preview", { method: "POST", signal: request.controller.signal, body: JSON.stringify({ address, password, method }) });
        if (!credentialRequestCurrent(request)) return;
        if (!d.ok) { hint.textContent = `${d.error || "读取失败"}${d.hint ? " · " + d.hint : ""}`; return; }
        const box = $("#wz-gmail-result");
        box.classList.remove("is-hidden");
        box.innerHTML = `<h4>${d.items.length} 封未读邮件头</h4>` + d.items.map((item, i) =>
          `<p><b>${esc(item.title)}</b><br>${esc(item.meta)} · ${esc(item.summary)}${i < 8 ? " · 生成理解时可能发送给模型" : ""}</p>`).join("") +
          `<p>生成理解时可能一并发送的提取事实：</p>` + (d.understanding?.facts || []).slice(0, 4).map(f => `<p>${esc(f)}</p>`).join("") + `
          <p>确认后接入这段对话，保留刚才的消息。聊天时若已配置模型服务，可能发送必要的邮件主题、发件人、日期及列出的提取事实，用于回应。不会下载邮件正文。预览 10 分钟内有效，仅能使用一次；可返回取消。</p>
          <button class="btn primary small" id="wz-gmail-start" style="margin-top:10px">${initialSession ? "接入当前对话" : "用这些未读开始对话"}</button>`;
        $("#wz-gmail-start").onclick = async () => {
          const button = $("#wz-gmail-start");
          if ((state.session?.id || null) !== initialSession || activeTurn || queuedTurns.length || turnQueue.length) { hint.textContent = "对话状态已变化或消息仍在发送，请稍后重新核对预览。"; return; }
          state.attachingSource = true;
          button.disabled = true;
          const startId = markCredentialStart();
          try {
            const s = await api("/api/gmail/start", { method: "POST", signal: request.controller.signal, body: JSON.stringify({ preview_id: d.preview_id, start_intro:true, ...(initialSession ? {session_id:initialSession} : {}) }) });
            if (!credentialRequestCurrent(request)) return;
            if (!s || !s.session) throw new Error("创建结果未确认");
            finishCredentialStart(startId);
            enterSession(s, { skipIntro: true });
          } catch (e) {
            if (!credentialRequestCurrent(request)) return;
            if ([400,404,409].includes(e.status)) {
              finishCredentialStart(startId);
              hint.textContent = e.status === 400 ? "读取预览已失效，请重新读取并确认来源。" : e.message;
            } else {
              renderCredentialPendingNotice();
              hint.textContent = "来源接入结果未确认，请返回当前对话或历史核对。";
            }
          } finally { state.attachingSource = false; }
        };
        await $("#wz-gmail-start").onclick();
      } catch (e) { if (credentialRequestCurrent(request)) hint.textContent = e.message; }
      finally { if (credentialRequestCurrent(request)) authorizeButton.disabled = false; }
    };
  }

  function renderFeishuAccount() {
    clearCredentialForms();
    const epoch = credentialGeneration;
    let sessionId = state.session?.id || null;
    const current = () => epoch === credentialGeneration && !els.onboarding.classList.contains("is-hidden") &&
      (!sessionId || state.session?.id === sessionId);
    showWz(3);
    $("#wz-read").classList.add("is-hidden");
    $("#wz-3 > .section-label").textContent = "飞书 · 按问题查阅";
    $("#read-items").innerHTML = ""; $("#read-scope").innerHTML = "";
    const head = $("#read-head");
    window.XinjiFeishuAccountPicker.mount(head, {api, getSessionId: () => state.session?.id, isCurrent: current,
      ensureSession: async () => {
        const data = await api("/api/conversation");
        if (!current()) return null;
        if (!data?.session?.id) throw Error("暂时无法读取当前对话");
        if (state.session && state.session.id !== data.session.id) throw Error("对话状态已变化，请重新打开连接");
        if (!state.session) {
          state.session = data.session; state.messages = data.messages || []; state.memories = data.memories || [];
          state.context = data.context || null; state.bookmark = data.bookmark || null;
          localStorage.setItem("xinji_session", data.session.id);
        }
        sessionId = state.session.id;
        return sessionId;
      },
      onAuthorize: () => startLarkAuth("account"),
      onConnected: data => finishConnection(data),
      onReturn: () => { closeSourceDialog(); els.input?.focus(); },
      onSingleDocument: () => {
        clearCredentialForms(); head.innerHTML = ""; $("#wz-3 > .section-label").textContent = "单篇文档快照";
        renderFeishuPicker();
      },
      onManageSources: () => { closeSourceDialog(); switchTab("data"); },
      onStateChange: data => { state.feishuAccount = data; window.XinjiFeishuAccountPicker.syncBadges(document, data); },
    });
  }

  function renderFeishuPicker() {
    let previewVersion = 0;
    const head = $("#read-head");
    head.querySelector(".real-feishu")?.remove();
    head.insertAdjacentHTML("beforeend", `
      <div class="real-feishu real-lark">
        <div class="mem-group-label" style="margin-top:12px"><span>选择一篇飞书文档</span><span class="muted">只接入单篇快照；读取时会核对飞书权限</span></div>
        <button type="button" class="btn ghost small" id="wz-feishu-reconnect">重新连接飞书</button>
        <div class="feishu-search-row">
          <input id="wz-feishu-q" placeholder="搜索飞书文档，例如：项目 / 周会 / PRD" />
          <button class="btn ghost small" id="wz-feishu-search">搜索</button>
        </div>
        <details><summary>搜索不可用？指定一篇文档</summary><div class="feishu-search-row"><input id="wz-feishu-url" placeholder="飞书文档链接" /><button class="btn ghost small" id="wz-feishu-url-read">读取</button></div></details>
        <button class="btn ghost small is-hidden" id="wz-feishu-search-auth">授权搜索云空间</button>
        <div id="wz-feishu-results" class="feishu-results"></div>
        <p class="note" id="wz-feishu-hint">选中文档后预览；开始对话时，如已配置模型服务，会发送文档摘要及提取内容生成理解。</p>
      </div>`);
    const pickerInput = $("#wz-feishu-q");
    $("#wz-feishu-reconnect").onclick = () => startLarkAuth("document", {force: true});
    const previewSelected = async (url) => {
      const version = ++previewVersion;
      const hint = $("#wz-feishu-hint");
      $("#wz-feishu-results").innerHTML = "";
      if (!url) { hint.textContent = "先选择一篇文档"; return; }
      if (!readableFeishuUrl(url)) { hint.textContent = "该类型暂不支持读取；请提供飞书文档或知识库链接。"; return; }
      try {
        hint.textContent = "正在读取所选文档…";
        const p = await api("/api/lark/preview", { method: "POST", body: JSON.stringify({ url }) });
        if (version !== previewVersion || $("#wz-feishu-q") !== pickerInput) return;
        if (!p.ok) { hint.textContent = p.error + (p.hint ? " · " + p.hint : ""); return; }
        $("#wz-feishu-results").innerHTML = `<div class="lark-preview"><h4>${esc(p.title)}</h4>${feishuPreviewMarkup(p)}
          <div class="meta"><span>提取后保留 ${p.length} 字</span><span>只读 · 单篇</span></div>
          <p class="note">${feishuDisclosure}</p>
          <button class="btn primary small" id="wz-feishu-start">${state.session ? "确认接入当前对话" : "确认并开始"}</button></div>`;
        $("#wz-feishu-start").onclick = () => confirmFeishuPreview(url, p.preview_id, hint, $("#wz-feishu-start"));
        hint.textContent = "请确认文档后继续。";
      } catch (e) { if (version === previewVersion) hint.textContent = e.message; }
    };
    const run = async () => {
      const version = ++previewVersion;
      const q = $("#wz-feishu-q").value.trim();
      const hint = $("#wz-feishu-hint");
      $("#wz-feishu-results").innerHTML = "";
      if (!q) { hint.textContent = "输入关键词后搜索"; return; }
      hint.textContent = "搜索中…";
      const d = await api("/api/lark/docs", {method:"POST", body:JSON.stringify({q})});
      if (version !== previewVersion || $("#wz-feishu-q") !== pickerInput) return;
      if (!d.ok) {
        hint.textContent = d.error + (d.hint ? " · " + d.hint : "");
        $("#wz-feishu-search-auth").classList.toggle("is-hidden", d.permission_issue !== "user_grant");
        return;
      }
      $("#wz-feishu-search-auth").classList.add("is-hidden");
      if (!d.items.length) { hint.textContent = "没有找到可访问的文档"; return; }
      hint.textContent = "仅支持文档或知识库链接；妙搭应用等其他类型暂不能读取。选中文档后先预览。";
      $("#wz-feishu-results").innerHTML = d.items.map((it, i) =>
        `<button class="feishu-doc" data-doc="${i}" ${readableFeishuUrl(it.url) ? "" : "disabled"}><b>${esc(it.title)}</b><span>${esc(it.type)}${readableFeishuUrl(it.url) ? "" : " · 该类型暂不支持读取"}</span></button>`).join("");
      $("#wz-feishu-results").querySelectorAll("[data-doc]").forEach((b) => {
        b.onclick = () => previewSelected(d.items[Number(b.dataset.doc)].url);
      });
    };
    const searchSafely = () => run().catch((e) => { $("#wz-feishu-hint").textContent = `搜索失败：${e.message}`; });
    $("#wz-feishu-search").onclick = searchSafely;
    $("#wz-feishu-search-auth").onclick = () => startLarkAuth("search");
    $("#wz-feishu-url-read").onclick = () => previewSelected($("#wz-feishu-url").value.trim());
    $("#wz-feishu-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); searchSafely(); } });
  }

  function renderNotionReal() {
    clearCredentialForms();
    const initialSession = state.session?.id || null;
    const head = $("#read-head");
    head.innerHTML = `<div class="real-notion real-lark connection-card">
      <div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">N</span><h3>连接 Notion</h3></div>
      <p class="connection-value">带上一页想法，从你正在做的事聊起。</p>
      <p class="connection-scope">只读所选页面前 50 个文本块或数据库前 20 条，相关内容会发送给当前模型。Token 仅本次使用。</p>
      <label>连接方式<select id="wz-notion-method"><option value="token">集成 Token</option><option value="cli">本机已登录的 Notion CLI</option></select></label>
      <input id="wz-notion-token" type="password" autocomplete="off" placeholder="Notion integration token" />
      <input id="wz-notion-url" placeholder="Notion 页面或数据库链接" />
      <button class="btn primary small" id="wz-notion-preview">授权</button><p class="connection-status" id="wz-notion-hint" role="status">请先在 Notion 中将页面连接给集成。</p>
      <details><summary>连接帮助</summary><a href="https://developers.notion.com/cli/get-started/authentication" target="_blank" rel="noopener noreferrer">Notion 官方 CLI 连接说明</a></details>
      <div id="wz-notion-result" class="lark-preview is-hidden" hidden></div></div>`;
    $("#wz-notion-method").onchange = () => { clearCredentialForms(); $("#wz-notion-hint").textContent = $("#wz-notion-method").value === "cli" ? "使用本机 ntn 已有登录；填写一个页面链接即可，只读前 50 个顶层文本块。" : "需在 Notion 中把目标页面连接给集成，填写 Token 和页面或数据库链接。"; $("#wz-notion-token").value = ""; $("#wz-notion-token").disabled = $("#wz-notion-method").value === "cli"; $("#wz-notion-result").innerHTML = ""; };
    globalThis.XinjiConnectorAuth?.mount(head.querySelector(".real-notion") || head, "notion");
    $("#wz-notion-method").onchange();
    $("#wz-notion-preview").onclick = async () => {
      const authorizeButton = $("#wz-notion-preview");
      if (authorizeButton.disabled) return;
      const method = $("#wz-notion-method").value || "token";
      const token = $("#wz-notion-token").value.trim();
      const url = $("#wz-notion-url").value.trim();
      const hint = $("#wz-notion-hint");
      if ((method !== "cli" && !token) || !url) { hint.textContent = method === "cli" ? "请填写一个 Notion 页面链接。" : "token 和页面/数据库链接都要填"; return; }
      authorizeButton.disabled = true;
      $("#wz-notion-result").classList.add("is-hidden");
      $("#wz-notion-result").innerHTML = "";
      hint.textContent = "读取中…";
      const request = beginCredentialRequest();
      $("#wz-notion-token").value = "";
      try {
        const d = await api("/api/notion/preview", { method: "POST", signal: request.controller.signal, body: JSON.stringify({ token, url, method }) });
        if (!credentialRequestCurrent(request)) return;
        if (!d.ok) { hint.textContent = `${d.error || "读取失败"}${d.hint ? " · " + d.hint : ""}`; return; }
        const box = $("#wz-notion-result");
        box.classList.remove("is-hidden");
        box.innerHTML = `<h4>${esc(d.title)}</h4><div class="meta"><span>${d.items.length} 条 · Notion</span><span>只读快照</span></div>` + d.items.map((item, i) =>
          `<p><b>${esc(item.title)}</b><br>${esc(item.meta)} · ${esc(item.summary)}${i < 8 ? " · 生成理解时可能发送给模型" : ""}</p>`).join("") +
          `<p>生成理解时可能一并发送的提取事实：</p>` + (d.understanding?.facts || []).slice(0, 4).map(f => `<p>${esc(f)}</p>`).join("") + `
          <p>确认后接入这段对话，保留刚才的消息。若已配置模型服务，将发送标记的标题、元信息、摘要及列出的提取事实，用于生成理解；之后对话可能发送保存的摘要和理解。预览 10 分钟内有效，仅能使用一次；可返回取消。</p>
          <button class="btn primary small" id="wz-notion-start" style="margin-top:10px">${initialSession ? "接入当前对话" : "用这页开始对话"}</button>`;
        $("#wz-notion-start").onclick = async () => {
          const button = $("#wz-notion-start");
          if ((state.session?.id || null) !== initialSession || activeTurn || queuedTurns.length || turnQueue.length) { hint.textContent = "对话状态已变化或消息仍在发送，请稍后重新核对预览。"; return; }
          state.attachingSource = true;
          button.disabled = true;
          const startId = markCredentialStart();
          try {
            const s = await api("/api/notion/start", { method: "POST", signal: request.controller.signal, body: JSON.stringify({ preview_id: d.preview_id, start_intro:true, ...(initialSession ? {session_id:initialSession} : {}) }) });
            if (!credentialRequestCurrent(request)) return;
            if (!s || !s.session) throw new Error("创建结果未确认");
            finishCredentialStart(startId);
            enterSession(s, { skipIntro: true });
          } catch (e) {
            if (!credentialRequestCurrent(request)) return;
            if ([400,404,409].includes(e.status)) {
              finishCredentialStart(startId);
              hint.textContent = e.status === 400 ? "读取预览已失效，请重新读取并确认来源。" : e.message;
            } else {
              renderCredentialPendingNotice();
              hint.textContent = "来源接入结果未确认，请返回当前对话或历史核对。";
            }
          } finally { state.attachingSource = false; }
        };
        await $("#wz-notion-start").onclick();
      } catch (e) { if (credentialRequestCurrent(request)) hint.textContent = e.message; }
      finally { if (credentialRequestCurrent(request)) authorizeButton.disabled = false; }
    };
  }

  function renderInsights() {
    const r = wizard.read;
    $("#wz-start").textContent = state.session ? "接入当前对话" : "开始对话";
    $("#insight-list").innerHTML = (['apple_calendar', 'apple_reminders'].includes(r.connector?.id) && !r.items?.length ? `<div class="insight-card"><b>读取成功，当前没有条目</b><p>${esc(r.connector?.id === "apple_reminders" ? "没有未完成的提醒事项。可以保存这次读取结果，之后再重新读取。" : "所选范围内没有日程。可以保存这次读取结果，之后再重新读取。")}</p></div>` : '') + r.insights.map((i) =>
      `<div class="insight-card"><div class="t">${esc(i.type.toUpperCase())}</div>
        <b>${esc(i.title)}</b><p>${esc(i.text)}</p></div>`).join("");
    const u = r.understanding;
    const row = (k, list) => list.map((x) => `<div class="intro-row"><b>${k}</b>${esc(x)}</div>`).join("");
    $("#wz-understanding").innerHTML = `
      <div class="wz-under">${row("事实", u.facts)}${row("推测", u.inferences)}${row("问题", u.questions)}</div>`;
    $("#wz-note-text").textContent = "这些是基于你所选来源的初步理解，请核对；若启用了模型，所选内容的摘要会发送给模型服务。";
    showWz(4);
  }

  async function startConnector() { toast("请先选择并核对一份真实来源。"); }

  // ---------------- onboarding ----------------
  let onboardingExitTimer = null;
  let sourceUiEpoch = 0;
  function enterSession(data, opts = {}) {
    clearCredentialForms();
    if (typeof pairedDevicesPanel !== "undefined") pairedDevicesPanel?.suspend();
    const sameSession = state.session?.id === data.session?.id;
    const previousTab = state.tab;
    const retainedMessages = opts.preserveDrafts && sameSession ? state.messages : null;
    sourceUiEpoch++;
    state.session = data.session;
    if (typeof updatePersonaLabels === "function") updatePersonaLabels();
    state.followupReminder?.refresh(); state.companionBoundary?.refresh();
    $("#chat-error")?.classList.add("is-hidden");
    state.messages = retainedMessages || data.messages;
    state.memories = data.memories;
    state.bookmark = data.bookmark || null;
    state.context = data.context || null;
    localStorage.setItem("xinji_session", state.session.id);

    clearTimeout(onboardingExitTimer);
    globalThis.XinjiSourceDialog?.close({remember: false});
    els.onboarding.classList.add("is-hidden");
    els.onboarding.classList.remove("leaving");
    els.app.classList.remove("is-hidden");

    els.sourceLabel.textContent = state.session.source_label || "新对话";
    els.sessionMeta.textContent = "";
    loadEngine();
    setOrb("listening");
    renderAll();
    if (typeof loadPersonaPicker === "function") loadPersonaPicker();
    loadAudit();
    loadNextStep();
    switchTab(sameSession && previousTab ? previousTab : "today");
    loadToday();
    renderInsightPanel();
    loadCarryover();
    bindIntro();
    window.XinjiConnectionIntro.syncBadges(document, state.context);
    connectionIntro.start(data.intro);
    if (new URLSearchParams(location.search).get("intro") === "1") showIntro();
  }

  async function startSession(mode, text = "") {
    if (!state.session) await restore();
    if (!state.session) return;
    if (mode !== "paste" || !text.trim()) return;
    if (text.length > 4000) { toast("这段资料超过本机单份 4000 字上限，请精简后再确认。"); return; }
    const sid = state.session.id;
    try {
      const data = await api("/api/local-files/confirm", {method: "POST", body: JSON.stringify({session_id: sid, files: [{name: "我补充的背景.txt", text}]})});
      if (state.session?.id === sid && data.session?.id === sid) enterSession(data, {preserveDrafts: true});
    } catch (error) { toast(error.message); }
  }

  let larkPreviewVersion = 0;
  async function previewLark() {
    const version = ++larkPreviewVersion;
    const url = $("#lark-url").value.trim();
    const hint = $("#lark-hint");
    const box = $("#lark-preview");
    hint.textContent = "";
    state.larkPreview = null;
    box.classList.add("is-hidden");
    $("#lark-start-btn").classList.add("is-hidden");
    if (!url) { hint.textContent = "先粘贴飞书文档链接"; return; }
    hint.textContent = "读取中…（只读，单篇）";
    try {
      const d = await api("/api/lark/preview", { method: "POST", body: JSON.stringify({ url }) });
      if (version !== larkPreviewVersion || $("#lark-url").value.trim() !== url) return;
      if (!d.ok) {
        hint.textContent = `${d.error || "读取失败"}${d.hint ? " · " + d.hint : ""}`;
        box.classList.add("is-hidden");
        $("#lark-start-btn").classList.add("is-hidden");
        return;
      }
      const markup = feishuPreviewMarkup(d);
      box.classList.remove("is-hidden");
      state.larkPreview = {url, previewId: d.preview_id};
      box.innerHTML = `<h4>${esc(d.title)}</h4>${markup}
        <div class="meta"><span>${d.length} 字 · identity=${esc(d.identity || "")}</span><span>只读 · 单篇</span></div>`;
      $("#lark-start-btn").classList.remove("is-hidden");
      hint.textContent = feishuDisclosure + " 撤回来源会清理派生记忆。";
    } catch (e) {
      if (version === larkPreviewVersion) hint.textContent = e.message;
    }
  }

  async function startLark() {
    const url = $("#lark-url").value.trim();
    if (!url) return;
    const hint = $("#lark-hint");
    const previewId = state.larkPreview?.url === url ? state.larkPreview.previewId : "";
    await confirmFeishuPreview(url, previewId, hint, $("#lark-start-btn"));
  }

  function connectedSources(context = state.context, session = state.session) {
    if (Array.isArray(context?.sources)) return context.sources;
    if ((!context || (!context.connector_id && !(context.items || []).length && !(context.insights || []).length))
        && (!session?.mode || session.mode === "empty" || !session.source_label)) return [];
    return [{id: null, connector_id: context?.connector_id || "legacy", label: session?.source_label || context?.connector_id || "原有资料来源",
      items: context?.items || [], insights: context?.insights || [], starters: context?.starters || [], stale: !!session?.source_context_stale}];
  }

  function sourceDisplayName(source) {
    const label = String(source.label || source.connector_id || "已接入来源");
    const title = String(source.title || (source.items || []).slice(0, 2).map(item => item.title || "").filter(Boolean).join("、"));
    return title && !label.includes(title) ? `${label} · ${title}` : label;
  }

  function memorySourceLabel(memory) {
    const source = memory.source_attachment_id && connectedSources().find(item => item.id === memory.source_attachment_id);
    if (!source) return memory.source || "来源待补";
    const name = sourceDisplayName(source);
    return memory.source && !name.includes(memory.source) ? `${memory.source} · ${name}` : name;
  }

  function sourceListMarkup(sources) {
    if (!sources.length) return state.feishuAccount?.enabled === true && state.feishuAccount.ready !== false
      ? '<p class="note">✓ 飞书已连接，聊天时会按需查阅。</p>'
      : '<p class="note">还没有接入资料。先聊聊，需要背景时再连接。</p>';
    return sources.map((source, index) => `<div class="connected-source">
      <div><b>${esc(sourceDisplayName(source))}</b><small>${source.stale ? "理解待核对 · 暂停用于回复" : "只读快照"} · ${(source.items || []).length} 条</small></div>
      <button class="text-btn source-remove" type="button" data-source-remove="${index}" ${!source.id && sources.length > 1 ? "disabled" : ""}>${!source.id && sources.length > 1 ? "刷新后移除" : "移除"}</button>
    </div>`).join("");
  }

  function bindSourceRemoval(container, sources, sid) {
    container.querySelectorAll("[data-source-remove]").forEach((button) => {
      button.onclick = () => {
        if (state.session?.id !== sid) return;
        const source = sources[Number(button.dataset.sourceRemove)];
        if (!source) return;
        if (source.id && !connectedSources().some(item => item.id === source.id)) { toast("来源列表已变化，请重新核对。"); renderConnectedSources(); return; }
        if (!source.id && connectedSources().length > 1) return;
        revokeSelectedSource(source.id || null);
      };
    });
  }

  function renderConnectedSources() {
    const sources = connectedSources(), sid = state.session?.id;
    const box = $("#connected-sources");
    if (box) { box.innerHTML = sourceListMarkup(sources); bindSourceRemoval(box, sources, sid); }
    if (els.sourceLabel) els.sourceLabel.textContent = sources.length > 1 ? `已接入 ${sources.length} 份来源` : (sources[0] ? sourceDisplayName(sources[0]) : "从对话开始");
    for (const id of ["#revoke-btn", "#data-revoke"]) {
      const button = $(id);
      if (button) { button.textContent = "移除全部已接入来源"; button.disabled = !sources.length; }
    }
  }

  function insightEntries() {
    return connectedSources().filter(source => !source.stale).flatMap(source => (source.insights || []).map(insight => ({...insight,
      sourceLabel: sourceDisplayName(source), connectorId: source.connector_id, sourceId: source.id})));
  }

  function renderInsightPanel() {
    const el = $("#insight-panel");
    if (!el) return;
    const insights = insightEntries();
    if (!insights.length) { el.classList.add("is-hidden"); el.innerHTML = ""; return; }
    el.classList.remove("is-hidden");
    el.innerHTML = `<div class="mem-group-label"><span>来自已接入来源的理解 · 可核对</span><span class="muted">${insights.length}</span></div>` +
      insights.map((i, idx) => `<div class="insight-chip">
        <div class="t">${esc(i.sourceLabel)} · ${esc((i.type || "").toUpperCase())}</div>
        <b>${esc(i.title)}</b><p>${esc(i.text)}</p>
        <div class="action-row">
          <button class="mini-btn" data-insight="${idx}" data-insight-source="${esc(i.sourceId || "")}">变成下一步</button>
          <button class="mini-btn" data-action="reminder" data-insight-idx="${idx}" data-insight-source="${esc(i.sourceId || "")}">提醒</button>
          <button class="mini-btn" data-action="calendar" data-insight-idx="${idx}" data-insight-source="${esc(i.sourceId || "")}">日历</button>
          <button class="mini-btn" data-action="message" data-insight-idx="${idx}" data-insight-source="${esc(i.sourceId || "")}">消息</button>
        </div>
      </div>`).join("");
  }

  function openInsightBookmark(i, expectedSourceId) {
    const ins = insightEntries()[i];
    if (!ins) return;
    if ((expectedSourceId !== undefined && String(ins.sourceId || "") !== expectedSourceId)
        || (ins.sourceId && !connectedSources().some(source => source.id === ins.sourceId))) {
      toast("这条理解的来源已变化，请重新核对。"); return;
    }
    state.bmSource = { source_memory_id: "", source_version: 0, source_attachment_id: ins.sourceId || "",
                       source_label: ins.sourceLabel || "洞察", source_quote: ins.text };
    state.bmSessionId = state.session?.id;
    els.bmNote.value = ins.title;
    els.bmChoice.value = `来自 ${ins.sourceLabel || "来源"} 的理解`;
    els.bmNext.value = ins.text;
    els.modal.classList.remove("is-hidden");
    els.bmNote.focus();
  }

  let pendingAction = null;

  function closeAction() {
    const action = pendingAction;
    pendingAction = null;
    $("#action-modal").classList.add("is-hidden");
    if (action?.phase === "committing") toast("确认请求已经发出，关闭窗口不代表取消保存；请到任务页核对。");
    else if (action?.phase === "creating") toast("已取消后续确认；若本机预览已创建，可以到任务页继续核对。");
  }

  function openAction(kind, idx, draft = null, expectedSourceId) {
    const ins = draft ? {title: draft.title || "", text: draft.text || ""} : insightEntries()[idx];
    if (!ins || !state.session || !["message", "reminder", "calendar"].includes(kind)) return;
    if (!draft && ((expectedSourceId !== undefined && String(ins.sourceId || "") !== expectedSourceId)
        || (ins.sourceId && !connectedSources().some(source => source.id === ins.sourceId)))) {
      toast("这条理解的来源已变化，请重新核对。"); return;
    }
    pendingAction = {kind, title: ins.title, detail: ins.text, sessionId: state.session.id, editable: true};
    const titleMap = {reminder: "新建提醒", calendar: "新建日历安排", message: "起草消息（不发送）"};
    $("#action-title").textContent = "我打算这样做 · " + titleMap[kind];
    $("#action-detail").textContent = "核对标题和内容后确认。默认只保存本机；消息草稿不会自动发送。";
    if ($("#action-name")) { $("#action-name").value = ins.title; $("#action-name").readOnly = false; }
    $("#action-real-row")?.classList.toggle("is-hidden", kind === "message");
    const realRow = $("#action-real-row");
    if (realRow && kind !== "message") realRow.lastChild.textContent = kind === "calendar"
      ? " 写入系统日历（需权限，写入第一个日历）"
      : " 写入系统提醒事项（需权限；当前系统接口只写标题，不设置到期时间）";
    $("#action-when-row")?.classList.toggle("is-hidden", kind === "message");
    if ($("#action-when")) {
      const date = new Date(); date.setDate(date.getDate() + 1); date.setHours(10, 0, 0, 0);
      const pad = value => String(value).padStart(2, "0");
      $("#action-when").value = kind === "calendar" ? `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T10:00` : "";
      $("#action-when").readOnly = false;
    }
    $("#action-message-row")?.classList.remove("is-hidden");
    if ($("#action-content-label")) $("#action-content-label").textContent = kind === "message" ? "草稿正文" : "内容（可选）";
    if ($("#action-message")) { $("#action-message").value = ins.text; $("#action-message").readOnly = false; }
    if ($("#action-real")) $("#action-real").checked = false;
    $("#action-confirm").disabled = false;
    $("#action-confirm").textContent = "确认保存";
    $("#action-result").classList.add("is-hidden");
    $("#action-modal").classList.remove("is-hidden");
    $("#action-name")?.focus();
  }

  function openSavedAction(action) {
    if (!state.session || action.status !== "previewed" || (action.session_id && action.session_id !== state.session.id)) return;
    openAction(action.kind, -1, {title: action.title, text: action.detail});
    if (!pendingAction) return;
    Object.assign(pendingAction, {existingId: action.id, title: action.title, detail: action.detail, when: action.when_text || "", editable: false});
    $("#action-detail").textContent = "这是已保存的待确认项。核对原内容后继续确认，不会新建第二个动作。" + (action.kind === "calendar" && !action.when_text ? "这条记录尚未设定时间，可以确认保存在本机；目前不能写入系统日历。" : "");
    for (const selector of ["#action-name", "#action-message", "#action-when"]) if ($(selector)) $(selector).readOnly = true;
    if ($("#action-when")) $("#action-when").value = action.when_text || "";
    $("#action-confirm").textContent = "确认这条记录";
  }

  async function checkActionStatus(action) {
    const sid = state.session?.id;
    if (!sid || (action.session_id && action.session_id !== sid)) return;
    switchTab("bookmark");
    await loadTaskActions();
    if (state.session?.id === sid) toast("已重新读取本机动作记录；没有再次写入系统。结果仍待确认时，请自行核对系统。");
  }

  async function confirmAction() {
    if (!pendingAction || !state.session) return;
    const action = pendingAction;
    const button = $("#action-confirm"), result = $("#action-result");
    if (button.disabled) return;
    if (action.sessionId !== state.session.id) {
      result.textContent = "对话状态已变化，请重新核对并打开草稿预览。";
      result.classList.remove("is-hidden"); return;
    }
    const title = action.editable ? ($("#action-name")?.value || "").trim() : action.title;
    const when = action.existingId ? (action.when || "") : ["calendar", "reminder"].includes(action.kind) ? ($("#action-when")?.value || "") : "";
    const real = !!($("#action-real")?.checked && ["reminder", "calendar"].includes(action.kind));
    if (!title || title.length > 200) { result.textContent = "请填写 1–200 字的标题。"; result.classList.remove("is-hidden"); return; }
    if (action.kind === "calendar" && !when && (real || !action.existingId)) {
      result.textContent = real ? "请先选择系统日历的时间。" : "请先选择日历安排的时间。";
      result.classList.remove("is-hidden"); return;
    }
    const detail = action.editable || action.kind === "message" ? ($("#action-message")?.value ?? action.detail) : action.detail;
    if ((action.kind === "message" && !detail.trim()) || detail.length > 2000) {
      result.textContent = detail.trim() ? "内容仍完整保留在编辑框。本机保存上限为 2000 字，请精简后再确认。" : "先填写想保存的草稿正文。";
      result.classList.remove("is-hidden"); return;
    }
    button.disabled = true;
    result.classList.add("is-hidden");
    let mayRetry = false;
    try {
      if (action.existingId) {
        const snapshot = await api(`/api/actions?session_id=${encodeURIComponent(action.sessionId)}`);
        if (pendingAction !== action || state.session?.id !== action.sessionId) return;
        const saved = (snapshot.actions || []).find(item => item.id === action.existingId);
        if (!saved || saved.status !== "previewed") {
          result.textContent = "这条记录已处理或结果待确认，请到任务页核对；没有再次写入系统。";
          result.classList.remove("is-hidden"); loadTaskActions(); return;
        }
      } else {
        action.phase = "creating";
        const created = await api("/api/action", {method: "POST", body: JSON.stringify({session_id: action.sessionId, kind: action.kind, title, detail, when})});
        if (!created?.id) throw Error("未确认创建结果");
        action.existingId = created.id; action.when = when; action.title = title; action.detail = detail; action.editable = false;
        if (pendingAction !== action || state.session?.id !== action.sessionId) {
          if (state.session?.id === action.sessionId) { loadTaskActions(); loadToday(); }
          return;
        }
        for (const selector of ["#action-name", "#action-message", "#action-when"]) if ($(selector)) $(selector).readOnly = true;
      }
      action.phase = "committing";
      const done = await api(`/api/action/${action.existingId}/commit`, {method: "POST", body: JSON.stringify({real})});
      if (pendingAction !== action || state.session?.id !== action.sessionId) return;
      if (done.status !== "committed") {
        result.textContent = action.kind === "message" ? "草稿保存结果未确认，请到任务页核对本机记录，暂勿重复保存。" : done.status === "unknown" || done.status === "executing"
          ? "未确认写入，请先到系统检查。任务页可以核对本机记录，不会自动重试。"
          : (done.error || "保存结果未确认，请到任务页核对，暂勿重复保存。");
        result.classList.remove("is-hidden"); loadTaskActions(); loadToday(); loadAudit(); return;
      }
      toast(done.real ? `已写入系统${action.kind === "calendar" ? "日历" : "提醒事项"}` : action.kind === "message" ? "消息草稿已保存（未发送）" : "仅保存在念响，未写入系统。");
      touchLastSeen();
      $("#action-modal").classList.add("is-hidden"); pendingAction = null;
      loadTaskActions(); loadToday(); loadAudit();
    } catch (error) {
      if (pendingAction !== action || state.session?.id !== action.sessionId) return;
      result.textContent = action.kind === "message" ? "草稿保存结果未确认，请到任务页核对本机记录，暂勿重复保存。" : "保存结果未确认，请到任务页核对本机记录，暂勿重复创建或再次写入。";
      result.classList.remove("is-hidden"); loadTaskActions(); loadToday();
    } finally { if (mayRetry && pendingAction === action && state.session?.id === action.sessionId) button.disabled = false; }
  }

  function actionStatusLabel(action) {
    if (action.status === "unknown" || action.status === "executing") return "未确认写入，请先检查系统";
    if (action.status === "failed") return "未写入系统";
    if (action.status === "previewed") return "待确认";
    return action.real ? "已写入系统" : "仅保存在念响";
  }

  let historyCache = [];
  let historySource = "";

  async function openHistory() {
    try {
      const d = await api("/api/sessions");
      historyCache = d.sessions || [];
      historySource = "";
      renderHistoryFilters();
      renderHistoryList($("#history-search").value.trim());
      $("#history-modal").classList.remove("is-hidden");
    } catch (e) { toast(e.message); }
  }

  function renderHistoryFilters() {
    const sources = [...new Set(historyCache.map((s) => (s.source_label || "示例").split(" · ")[0]))];
    $("#history-filters").innerHTML = ["全部", ...sources].map((src) => {
      const active = (src === "全部" && !historySource) || src === historySource;
      return `<button class="filter-chip ${active ? "active" : ""}" data-src="${src === "全部" ? "" : esc(src)}">${esc(src)}</button>`;
    }).join("");
    $("#history-filters").querySelectorAll("[data-src]").forEach((b) => {
      b.onclick = () => { historySource = b.dataset.src; renderHistoryFilters(); renderHistoryList($("#history-search").value.trim()); };
    });
  }

  function renderHistoryList(q = "") {
    const list = historyCache.filter((s) =>
      (!q || `${s.title} ${s.source_label}`.includes(q)) &&
      (!historySource || (s.source_label || "").startsWith(historySource)));
    $("#history-list").innerHTML = list.length
      ? list.map((s) => `<div class="history-item" data-history="${s.id}">
          <div class="history-main">
            <b>${esc(s.title || "新会话")}</b>
            <span>${esc(s.source_label || "新对话")} · ${esc((s.last_at || "").slice(0, 16).replace("T", " "))} · ${s.memories} 条记忆</span>
          </div>
          <span class="history-ops">
            <button class="text-btn history-del" data-rename="${s.id}" title="重命名">改名</button>
            <button class="text-btn history-del" data-del="${s.id}" title="删除这条会话">忘掉这条</button>
          </span>
        </div>`).join("")
      : `<p class="note">${q ? "没有匹配的会话" : "还没有会话。走完 onboarding 后会出现在这里。"}</p>`;
    $("#history-list").querySelectorAll("[data-history]").forEach((el) => {
      el.onclick = () => {
        localStorage.setItem("xinji_session", el.dataset.history);
        location.reload();
      };
    });
    $("#history-list").querySelectorAll("[data-rename]").forEach((el) => {
      el.onclick = async (ev) => {
        ev.stopPropagation();
        const cur = historyCache.find((s) => s.id === el.dataset.rename);
        const title = prompt("给这次会话起个名字：", cur?.title || "");
        if (!title || !title.trim()) return;
        try {
          await api(`/api/session/${el.dataset.rename}`, { method: "PATCH", body: JSON.stringify({ title: title.trim() }) });
          if (cur) cur.title = title.trim();
          renderHistoryList($("#history-search").value.trim());
          toast("已重命名");
        } catch (e) { toast(e.message); }
      };
    });
    $("#history-list").querySelectorAll("[data-del]").forEach((el) => {
      el.onclick = async (ev) => {
        ev.stopPropagation();
        if (!confirm("删除这条会话？消息、记忆、历史、书签、动作与审计都会移除。")) return;
        try {
          await api(`/api/session/${el.dataset.del}`, { method: "DELETE" });
          typeof mood !== "undefined" && mood?.clearSession(el.dataset.del);
          if (state.session && state.session.id === el.dataset.del) {
            localStorage.removeItem("xinji_session");
            location.reload();
            return;
          }
          historyCache = historyCache.filter((s) => s.id !== el.dataset.del);
          renderHistoryList(q);
          toast("已删除该会话");
        } catch (e) { toast(e.message); }
      };
    });
  }

  async function loadCarryover() {
    const box = $("#carryover-banner");
    if (!box || !state.session) return;
    const sid = state.session.id;
    if (localStorage.getItem("xinji_carry_dismiss_" + sid)) { box.classList.add("is-hidden"); return; }
    try {
      const d = await api(`/api/carryover?session_id=${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid) return;
      const items = d.memories || [], current = d.current_confirmed || [];
      if (!items.length) { box.classList.add("is-hidden"); return; }
      const content = $("#carryover-text");
      content.replaceChildren();
      const heading = document.createElement("div");
      heading.textContent = "挑选最近的记忆带入本次对话。说法可能过时或不一致，请先核对。";
      content.appendChild(heading);
      if (current.length) {
        const existing = document.createElement("details");
        existing.open = true;
        const summary = document.createElement("summary");
        summary.textContent = `本次已确认 ${current.length} 条`;
        existing.appendChild(summary);
        for (const m of current) {
          const row = document.createElement("div");
          row.textContent = m.text;
          existing.appendChild(row);
        }
        content.appendChild(existing);
      }
      const choices = [];
      for (const m of items) {
        const label = document.createElement("label");
        label.className = "carryover-choice";
        const check = document.createElement("input");
        check.type = "checkbox";
        const text = document.createElement("span");
        text.textContent = m.text + (m.source ? `（${m.source}）` : "") + (m.updated_at ? ` · ${m.updated_at.slice(0, 10)}` : "");
        label.appendChild(check); label.appendChild(text); content.appendChild(label);
        choices.push({check, memory: m});
      }
      box.classList.remove("is-hidden");
      $("#carryover-accept").onclick = async () => {
        const button = $("#carryover-accept");
        const selected = choices.filter(x => x.check.checked).map(x => x.memory);
        if (!selected.length) { toast("请先选择要带入的记忆"); return; }
        button.disabled = true;
        let imported = false;
        try {
          const r = await api("/api/carryover/import", { method: "POST", body: JSON.stringify({
            session_id: sid, ids: selected.map(m => m.id),
            expected_versions: Object.fromEntries(selected.map(m => [m.id, m.version])),
            expected_target: Object.fromEntries(current.map(m => [m.id, m.version]))
          }) });
          imported = true;
          const latest = await api(`/api/memory?session_id=${encodeURIComponent(sid)}`);
          if (state.session?.id !== sid) return;
          state.memories = latest.memories || [];
          box.classList.add("is-hidden");
          renderAll();
          toast(`已带入 ${r.imported || 0} 条`);
        } catch (e) {
          if (state.session?.id === sid) {
            toast(imported ? "已带入，但列表刷新失败；请刷新对话查看。" : `带入失败：${e.message}`);
            if (!imported && e.status === 409) await loadCarryover();
          }
        } finally { button.disabled = false; }
      };
      $("#carryover-dismiss").onclick = () => {
        localStorage.setItem("xinji_carry_dismiss_" + sid, "1");
        box.classList.add("is-hidden");
      };
    } catch (_) { if (state.session?.id === sid) box.classList.add("is-hidden"); }
  }

  function showResumeBanner() {
    if (!state.session) return;
    const banner = $("#resume-banner");
    if (!banner) return;
    if (!state.bookmark && !state.messages.some((message) => message.role === "user")) {
      banner.classList.add("is-hidden");
      return;
    }
    const key = "xinji_last_seen_" + state.session.id;
    const ts = localStorage.getItem(key);
    if (!ts) return;
    const t = new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const bm = state.bookmark;
    $("#resume-text").textContent = bm
      ? `上次停在这里 · 书签：${bm.note.slice(0, 24)}`
      : `上次停在这里 · ${t}，接着往下说`;
    const bmBtn = $("#resume-bookmark");
    if (bmBtn) {
      bmBtn.classList.toggle("is-hidden", !bm);
      bmBtn.onclick = () => { switchTab("bookmark"); banner.classList.add("is-hidden"); };
    }
    banner.classList.remove("is-hidden");
    $("#messages").scrollTop = $("#messages").scrollHeight;
  }

  function showIntro() {
    globalThis.XinjiVoice?.stop?.();
    const groups = [
      ["事实", state.memories.filter((m) => m.kind === "fact")],
      ["推测", state.memories.filter((m) => m.kind === "inference")],
      ["问题", state.memories.filter((m) => m.kind === "question")],
    ];
    const body = $("#intro-body");
    body.innerHTML = groups.map(([label, items]) => items.length
      ? `<div class="intro-group"><div class="mem-group-label"><span>${label}</span><span class="muted">${items.length}</span></div>${items.map((m) => `<div class="intro-item">${esc(m.text)}</div>`).join("")}</div>`
      : "").join("");
    $("#intro-modal").classList.remove("is-hidden");
  }

  function bindIntro() {
    $("#intro-start").onclick = () => {
      $("#intro-modal").classList.add("is-hidden");
      $("#input").focus();
    };
    $("#intro-edit").onclick = () => {
      $("#intro-modal").classList.add("is-hidden");
      switchTab("understanding");
      setTimeout(() => document.querySelector("#tab-understanding")?.scrollIntoView({ block: "start" }), 50);
    };
  }

  // ---------------- render ----------------
  function renderAll() {
    renderConnectedSources();
    renderMessages();
    renderUnderstanding();
    renderMemoryList();
    renderBookmark();
    renderStarterBar();
  }

  function touchLastSeen() {
    if (state.session) localStorage.setItem("xinji_last_seen_" + state.session.id, new Date().toISOString());
  }

  function renderMessageText(text) {
    return window.XinjiMeme.render(text, state.memes, esc);
  }

  function renderStarterBar() {
    const bar = $("#starter-bar");
    if (!bar) return;
    const starters = [...new Set(connectedSources().filter(source => !source.stale).flatMap(source => source.starters || []))].slice(0, 4);
    const isEmpty = state.messages.filter((m) => m.role === "user").length === 0;
    if (!starters.length || !isEmpty) { bar.classList.add("is-hidden"); bar.innerHTML = ""; return; }
    bar.classList.remove("is-hidden");
    bar.innerHTML = starters.map((s) => `<button class="starter" data-starter="${esc(s)}">${esc(s)}</button>`).join("");
    bar.querySelectorAll("[data-starter]").forEach((b) => {
      b.onclick = () => { bar.classList.add("is-hidden"); sendMessage(b.dataset.starter); };
    });
  }

  window.XinjiCompanionChoices.bind(document, els.input);

  const memoryProposal = window.createMemoryProposal({box: $("#memory-proposal"), toggle: $("#memory-proposal-enabled"), state, api, toast, refresh: renderAll});
  const chatScroll = window.createChatScroll($("#messages"), $("#chat-new-messages"));
  let renderedChatSession = null;
  let renderedMessageIds = new Set();
  state.delivery = window.XinjiChatDelivery.create({state, api, render: () => renderMessages(),
    stopButton: $("#stop-btn"), busy: () => !!activeTurn,
    onError: error => toast(error?.message || "消息发送状态暂时无法确认，请稍后核对")});
  function renderMessages(forceBottom = false) {
    function decorateAssistantMessage(message) {
      if (message?.role !== "assistant" || typeof message.text !== "string") return message;
      const parser = globalThis.XinjiResponseParser;
      if (!parser?.parse) return message;
      if (Array.isArray(message.bubbles) && message.bubbles.length) return message;
      const parsed = parser.parse(message.text);
      if (!parsed || !Array.isArray(parsed.messages) || !parsed.messages.length) return message;
      message.bubbles = parsed.messages;
      message._bubblesSource = message.text;
      return message;
    }
    memoryProposal.sync();
    const empty = state.messages.filter((m) => m.role === "user").length === 0;
    const lastAssistant = [...state.messages].reverse().find((m) => m.role === "assistant");
    const showEmpty = empty && state.session?.mode === "empty" && !state.messages.some(message => message.connection_intro);
    $("#chat-empty")?.classList.toggle("is-hidden", !showEmpty);
    const visibleMessages = showEmpty ? [] : state.messages;
    visibleMessages.forEach(decorateAssistantMessage);
    const sessionChanged = renderedChatSession !== state.session?.id;
    const newMessage = !sessionChanged && visibleMessages.some(message => !String(message.id).startsWith("local-") && !renderedMessageIds.has(message.id));
    chatScroll.render(() => { els.messages.innerHTML = visibleMessages
      .map((m, index) => {
        const role = m.role === "user" ? "user" : "assistant";
        const time = m.created_at ? new Date(m.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : "";
        const cites = window.XinjiFeishuAccountPicker?.renderCitations(m) || "";
        const sugg = (lastAssistant && m.id === lastAssistant.id && (m.suggestions || []).length)
          ? `<div class="suggests">${m.suggestions.map((s) => `<button class="suggest" data-suggest="${esc(s)}">${esc(s)}</button>`).join("")}</div>`
          : "";
        const draft = window.XinjiActionCards.chatDraft(visibleMessages, index);
        const draftButton = draft ? `<div class="suggests"><button class="suggest" data-chat-draft="${index}">查看并保存为消息草稿</button></div>` : "";
        const parts = role === "assistant" && Array.isArray(m.bubbles) && m.bubbles.length ? m.bubbles : [m.text];
        const voiceButton = role === "assistant" && !m.delivery_pending ? `<button type="button" class="message-topic" data-voice-message="${index}" aria-label="朗读这条回复" title="${esc(window.EchoShared?.copy?.['voice.disclosure'] || '由设备语音朗读，不会自动播放或创建语音文件。')}" aria-pressed="false">${esc(window.EchoShared?.copy?.['voice.read'] || '朗读')}</button><button type="button" class="message-topic" hidden data-voice-clip="${index}">生成语音</button><span data-voice-clip-slot="${index}"></span>` : "";
        const proposalButton = m.action_proposal && !m.delivery_pending ? `<div class="suggests"><button class="suggest" data-action-proposal="${index}">查看提醒预览</button></div>` : "";
        return `<div class="msg ${role}" data-message-id="${esc(m.id)}" data-persona-id="${esc(m.persona_id || '')}" data-interaction-mode="${esc(m.interaction_mode || '')}">
          <div class="meta"><span>${role === "user" ? "你" : "回响"}</span><span>${esc(time)}</span></div>
          ${parts.map(part => `<div class="bubble">${renderMessageText(part)}</div>`).join("")}
          ${cites ? `<div class="cites">${cites}</div>` : ""}
          ${sugg}${draftButton}${proposalButton}${voiceButton}<button type="button" class="message-topic" data-topic-message="${esc(m.id)}" ${String(m.id).startsWith("local-") ? 'disabled title="发送完成后可标记话题"' : ""} aria-label="为这条消息标记话题">标记话题</button>
        </div>`;
      })
      .join(""); }, { forceBottom: forceBottom || sessionChanged, newMessage });
    globalThis.XinjiWorkspace?.filterMessages(els.messages);
    renderedChatSession = state.session?.id;
    renderedMessageIds = new Set(visibleMessages.map(message => message.id));
    state.delivery?.schedule();
    const draftSession = state.session?.id;
    window.XinjiVoice.pruneClips(draftSession, visibleMessages);
    els.messages.querySelectorAll("[data-voice-message]").forEach(button => {
      const message = visibleMessages[Number(button.dataset.voiceMessage)];
      if (message) window.XinjiVoice.bindMessage(message.id, window.XinjiVoice.readText(message), button, draftSession);
      button.onclick = () => { if (message && state.session?.id === draftSession) window.XinjiVoice.playMessage(message.id, window.XinjiVoice.readText(message), button, draftSession); };
    });
    els.messages.querySelectorAll("[data-voice-clip]").forEach(button => {
      const index = Number(button.dataset.voiceClip), message = visibleMessages[index];
      const container = els.messages.querySelector(`[data-voice-clip-slot="${index}"]`);
      if (!message || !container) return;
      window.XinjiVoice.bindClipControl(button, window.XinjiVoice.clipEligible(message));
      if (window.XinjiVoice.attachClip(draftSession, message.id, message.text, container)) button.textContent = '语音已生成';
      button.onclick = () => window.XinjiVoice.makeClip({sessionId:draftSession, id:message.id, text:message.text, button, container,
        isCurrent:() => state.session?.id === draftSession && state.messages.some(m => m.id === message.id && m.text === message.text && !m.delivery_pending),
        onReady:() => renderMessages()});
    });
    els.messages.querySelectorAll("[data-action-proposal]").forEach(button => {
      button.onclick = async () => {
        if (state.session?.id !== draftSession) return;
        const message = visibleMessages[Number(button.dataset.actionProposal)];
        if (!message?.id || button.disabled) return;
        button.disabled = true;
        try {
          const latest = await api(`/api/session/${encodeURIComponent(draftSession)}`);
          if (state.session?.id !== draftSession) return;
          const fresh = (latest.messages || []).find(item => item.id === message.id && !item.delivery_pending);
          const result = followups.offer(fresh?.action_proposal);
          if (result === "ready") { switchTab("today"); $("#today-followups")?.scrollIntoView({block:"start"}); }
          else if (result === "draft") { switchTab("today"); toast("你已有未保存的跟进草稿，请先处理它，再打开这条建议。"); }
          else if (result === "pending") { switchTab("today"); toast("上一条跟进的保存结果待核对，请先处理它。"); }
          else toast("这条建议已变化，请重新发起提醒。");
        } catch (error) { if (state.session?.id === draftSession) toast(`暂时无法核对建议：${error.message}`); }
        finally { button.disabled = false; }
      };
    });
    els.messages.querySelectorAll("[data-chat-draft]").forEach((button) => {
      button.onclick = () => {
        if (state.session?.id !== draftSession) return;
        const draft = window.XinjiActionCards.chatDraft(visibleMessages, Number(button.dataset.chatDraft));
        if (draft) openAction("message", null, draft);
      };
    });
    els.messages.querySelectorAll("[data-suggest]").forEach((b) => {
      b.onclick = () => sendMessage(b.dataset.suggest);
    });
    $("#chat-empty")?.querySelectorAll("[data-prompt]").forEach((b) => {
      b.onclick = () => window.XinjiCompanionChoices.put(els.input, b.dataset.prompt);
    });
  }

  function memByKind(kind) {
    return state.memories.filter((m) => m.kind === kind && m.status !== "deleted");
  }

  function renderUnderstanding() {
    const groups = [
      [els.understandingFacts, memByKind("fact"), "事实"],
      [els.understandingInferences, memByKind("inference"), "推测"],
      [els.understandingQuestions, memByKind("question"), "问题"],
    ];
    groups.forEach(([el, items, label]) => {
      if (!el) return;
      el.innerHTML =
        `<div class="mem-group-label"><span>${label}</span><span class="muted">${items.length}</span></div>` +
        (items.length
          ? items.map((m) => understandingItem(m)).join("")
          : `<p class="note">还没有${label}。</p>`);
    });
  }

  function understandingItem(m) {
    return `<div class="mem-item" data-id="${m.id}">
      <div class="memory-origin ${m.kind === "inference" && m.status !== "confirmed" ? "is-inference" : ""}">${m.kind === "inference" && m.status !== "confirmed" ? "推测 · 待你确认" : m.source_attachment_id ? "来自你选定的资料" : /用户|原话|user|聊天/.test(m.source || "") ? "你的原话" : "来源见下方记录"}</div><div class="mem-text">${esc(m.text)}</div><p class="memory-use">确认后，可作为相关对话的背景。</p><details class="memory-details"><summary>来源与使用方式</summary><p>说于：原话的具体时间未记录。<br>记下于：${esc(m.created_at ? String(m.created_at).replace("T", " ") : "未记录")}<br>用在：相关对话的背景，${m.kind === "inference" && m.status !== "confirmed" ? "推测需要先由你确认。" : "可随时纠正或忘掉。"}</p></details>
      <div class="mem-meta">
        <span class="mem-version">v${m.version} · ${esc(memorySourceLabel(m))}</span>
        <span class="mem-actions">
          ${m.status === "candidate" ? `<button class="mini-btn confirm" data-act="confirm" data-id="${m.id}">确认</button>` : `<span class="mini-btn confirm" style="opacity:.6">已确认</span>`}
          <button class="mini-btn" data-act="edit" data-id="${m.id}">改一改</button>
          <button class="mini-btn" data-act="history" data-id="${m.id}">历史</button>
          <button class="mini-btn" data-act="delete" data-id="${m.id}">忘掉这条</button>
        </span>
      </div>
    </div>`;
  }

  function renderMemoryList() {
    if (!els.memoryList) return;
    els.memoryList.innerHTML = state.memories.length
      ? state.memories.map((m) => memoryItem(m)).join("")
      : `<p class="note">还没有记忆。对话里说「记住……」或手动添加。</p>`;
    for (const id of memoryDrafts.keys()) if (state.memories.some(memory => memory.id === id)) startMemoryEdit(id);
  }

  function memoryItem(m) {
    return `<div class="mem-item" data-id="${m.id}">
      <div class="mem-group-label" style="margin-bottom:6px">
        <span class="tag ${m.kind}">${{ fact: "事实", inference: "推测", question: "问题" }[m.kind]}</span>
        <span class="mem-version">v${m.version} · ${m.status === "confirmed" ? "已确认" : "待确认"}</span>
      </div>
      <div class="memory-origin ${m.kind === "inference" && m.status !== "confirmed" ? "is-inference" : ""}">${m.kind === "inference" && m.status !== "confirmed" ? "推测 · 待你确认" : m.source_attachment_id ? "来自你选定的资料" : /用户|原话|user|聊天/.test(m.source || "") ? "你的原话" : "来源见下方记录"}</div><div class="mem-text">${esc(m.text)}</div><p class="memory-use">确认后，可作为相关对话的背景。</p><details class="memory-details"><summary>来源与使用方式</summary><p>说于：原话的具体时间未记录。<br>记下于：${esc(m.created_at ? String(m.created_at).replace("T", " ") : "未记录")}<br>用在：相关对话的背景，${m.kind === "inference" && m.status !== "confirmed" ? "推测需要先由你确认。" : "可随时纠正或忘掉。"}</p></details>
      <div class="mem-meta">
        <span class="mem-version">${esc(memorySourceLabel(m))}</span>
        <span class="mem-actions">
          ${m.status === "candidate" ? `<button class="mini-btn confirm" data-act="confirm" data-id="${m.id}">确认</button>` : ""}
          <button class="mini-btn" data-act="edit" data-id="${m.id}">改一改</button>
          <button class="mini-btn" data-act="history" data-id="${m.id}">历史</button>
          <button class="mini-btn" data-act="delete" data-id="${m.id}">忘掉这条</button>
        </span>
      </div>
    </div>`;
  }

  function renderBookmark() {
    if (!els.bookmarkCard) return;
    const b = state.bookmark;
    if (!b) {
      els.bookmarkCard.className = "bookmark-card empty";
      els.bookmarkCard.innerHTML = `<p class="muted">还没有书签。聊到一个想停下的位置，点「标记此刻」。</p>`;
      return;
    }
    els.bookmarkCard.className = "bookmark-card";
    const committed = b.status === "committed";
    els.bookmarkCard.innerHTML = `
      <p class="bm-note">${esc(b.note)}</p>
      <div class="bm-row"><b>取舍</b><span>${esc(b.choice || "—")}</span></div>
      <div class="bm-row"><b>下一步</b><span>${esc(b.next_step || "—")}</span></div>
      ${b.source_label || b.source_quote ? `<div class="bm-row"><b>来源</b><span>${esc(b.source_label || "")}${b.source_version ? " · v" + b.source_version : ""}${b.source_quote ? " · " + esc(b.source_quote.slice(0, 40)) + "…" : ""}</span></div>` : ""}
      <div class="bm-receipt">
        <span>${committed ? "已保存 · " + esc(b.receipt || "") : "草稿 · 未保存"}</span>
        ${committed ? `<span>${esc((b.committed_at || "").slice(0, 16).replace("T", " "))}</span>` : `<button class="mini-btn confirm" id="commit-bm">确认保存</button>`}
      </div>`;
    const commitBtn = $("#commit-bm");
    if (commitBtn) commitBtn.onclick = commitBookmark;
  }

  const recommendedTasks = [
    ["☷", "整理今日重点", "把你今天要做的事情列清楚，排出最值得先完成的一件。"],
    ["⌧", "拆解一项计划", "把一个目标拆成几步，明确下一步现在就能开始做什么。"],
    ["✣", "梳理混乱想法", "把你脑中的信息分组整理，提炼出重点、疑问和待决定事项。"],
    ["≡", "回顾近期进展", "根据我们的对话整理已经完成、暂时卡住和接下来要继续的事情。"],
    ["◌", "清理待办清单", "合并重复事项，删掉不再重要的内容，把剩下的安排得更清楚。"]
  ];

  function putTaskPrompt(text) {
    if (!text || !els.input) return;
    els.input.value = els.input.value.trim() ? `${els.input.value.trim()}\n${text}` : text;
    els.input.focus();
    els.input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function renderTaskRecommendations() {
    const box = $("#task-recommendations");
    if (!box) return;
    box.innerHTML = recommendedTasks.map(([icon, title, prompt], index) => `<article class="task-recommendation" draggable="true" data-task-prompt="${esc(prompt)}"><span class="task-icon">${icon}</span><div class="task-copy"><b>${esc(title)}</b><p>${esc(prompt)}</p></div><button class="task-add" type="button" data-task-add="${index}" aria-label="添加${esc(title)}">＋</button></article>`).join("");
    box.querySelectorAll("[data-task-add]").forEach((button) => button.addEventListener("click", () => { const task = recommendedTasks[Number(button.dataset.taskAdd)]; putTaskPrompt(task?.[2]); }));
    box.querySelectorAll(".task-recommendation").forEach((card) => {
      card.addEventListener("dragstart", (event) => { event.dataTransfer.setData("text/plain", card.dataset.taskPrompt || ""); card.classList.add("is-dragging"); });
      card.addEventListener("dragend", () => card.classList.remove("is-dragging"));
    });
  }

  const taskViews = $$('[data-task-view]');
  taskViews.forEach((button) => button.addEventListener('click', () => {
    const view = button.dataset.taskView;
    taskViews.forEach((item) => item.classList.toggle('active', item === button));
    $$('[data-task-panel]').forEach((panel) => { panel.style.display = panel.dataset.taskPanel === view ? '' : 'none'; });
  }));
  $('#create-task-btn')?.addEventListener('click', () => {
    const title = window.prompt('任务名称');
    if (!title?.trim()) return;
    const detail = window.prompt('任务说明（可选）') || '这是你创建的任务，可以直接在对话中继续。';
    const list = $('#my-task-list');
    if (!list) return;
    list.querySelector('.my-task-empty')?.remove();
    const card = document.createElement('article');
    card.className = 'task-recommendation user-task';
    card.innerHTML = `<span class="task-icon">＋</span><div class="task-copy"><b>${esc(title.trim())}</b><p>${esc(detail)}</p></div><button class="task-add" type="button">＋</button>`;
    card.querySelector('.task-add').addEventListener('click', () => putTaskPrompt(detail));
    list.appendChild(card);
    document.querySelector('[data-task-view="mine"]')?.click();
  });

  renderTaskRecommendations();
  els.input?.addEventListener("dragover", (event) => { event.preventDefault(); $("#composer")?.classList.add("task-drop-active"); });
  els.input?.addEventListener("dragleave", () => $("#composer")?.classList.remove("task-drop-active"));
  els.input?.addEventListener("drop", (event) => { event.preventDefault(); $("#composer")?.classList.remove("task-drop-active"); putTaskPrompt(event.dataTransfer.getData("text/plain")); });

  async function loadPlugins() {
    try {
      const d = await api("/api/plugins");
      state.memes = (d.meme && d.meme.items) || [];
      if (state.session) renderMessages();
      $("#meme-btn")?.classList.toggle("is-hidden", !state.memes.length);
      const box = $("#plugin-status");
      if (box) {
        box.innerHTML = `<div class="k">插件</div>
          <p class="note">表情包：${d.meme?.installed ? `${state.memes.length} 张（含回响自带）` : "未安装"}</p>
          <p class="note">桌宠：${d.pet?.installed ? `dsh-pet ${esc(d.pet.version)} · ${esc(d.pet.hint || "")}` : "未安装"}</p>`;
      }
      const grid = $("#meme-grid");
      if (grid) {
        grid.innerHTML = state.memes.map((m, i) => `<button class="meme-item" data-meme="${i}"><img src="${esc(m.url)}" alt="${esc(m.label)}" loading="lazy"><span>${esc(m.label)}</span></button>`).join("");
        grid.querySelectorAll("[data-meme]").forEach((b) => {
          b.onclick = () => {
            $("#meme-modal").classList.add("is-hidden");
            const m = state.memes[Number(b.dataset.meme)];
            if (m) sendMessage(`[表情: ${m.id}]`);
          };
        });
      }
    } catch (_) {}
  }

  async function loadEngine() {
    try {
      const cfg = await api("/api/config");
      const badge = $("#engine-badge");
      if (!badge) return;
      if (cfg.model && cfg.model.configured) {
        badge.textContent = `模型 · ${cfg.model.model}`;
        badge.title = "已配置模型服务；失败时自动降级规则引擎";
      } else {
        badge.textContent = "规则引擎 · 未配置模型";
        badge.title = "设置 XINJI_MODEL_BASE_URL / API_KEY / NAME 后启用模型";
      }
    } catch (_) {}
  }

  async function loadNextStep() {
    if (!state.session) return;
    const sid = state.session.id, epoch = sourceUiEpoch;
    try {
      const next = await api(`/api/next-step?session_id=${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid || epoch !== sourceUiEpoch) return;
      state.nextStep = next;
      renderNextStep();
    } catch (_) {}
  }

  function renderNextStep() {
    const card = $("#next-step-card");
    if (!card) return;
    const d = state.nextStep;
    if (!d) { card.innerHTML = ""; return; }
    card.innerHTML = `
      <div class="next-step-label">下一步 · 候选 ${d.changed_by_version ? `· 基于 v${d.changed_by_version}` : ""}</div>
      <p class="next-step-text">${esc(d.step)}</p>
      <p class="next-step-why">${esc(d.rationale)}</p>
      <div class="next-step-actions">
        <button class="mini-btn confirm" id="next-to-bookmark">存成书签</button>
        <button class="mini-btn" id="next-refresh">刷新建议</button>
      </div>`;
    $("#next-to-bookmark").onclick = () => {
      openBookmarkModal(false);
      els.bmNext.value = d.step;
    };
    $("#next-refresh").onclick = loadNextStep;
  }

  async function loadAudit() {
    if (!state.session) return;
    try {
      const data = await api(`/api/audit?session_id=${encodeURIComponent(state.session.id)}`);
      els.auditList.innerHTML = (data.events || [])
        .map((e) => {
          const t = new Date(e.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
          return `<li><time>${esc(t)}</time><div><span class="audit-action">${esc(e.action)}</span><div class="audit-detail">${esc(e.detail || "")}${e.reason ? " · " + esc(e.reason) : ""}</div></div></li>`;
        })
        .join("") || `<li><span></time><span class="muted">暂无记录</span></li>`;
    } catch (_) {}
  }

  // ---------------- chat ----------------
  let turnQueue = [];
  let turnTimer = null;
  let queuedTurns = [];
  let activeTurn = null;
  let chatBlocked = false;
  let chatStorageBlocked = false;
  const uncertainTurns = new Map();
  const chatLedger = window.XinjiChatTransport.createLedger('web');
  const chatTransport = window.XinjiChatTransport.create(api, {ledger:chatLedger});
  const displayedTurns = new Map();
  let localTurnId = 0;
  let recognition = null;
  let listening = false;

  function setupVoice() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const btn = $("#mic-btn");
    if (!SR) { btn.classList.add("is-hidden"); return; }
    recognition = new SR();
    recognition.lang = "zh-CN";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.onresult = (e) => {
      let text = "";
      for (let i = e.resultIndex; i < e.results.length; i++) text += e.results[i][0].transcript;
      els.input.value = text.trim();
    };
    recognition.onstart = () => {
      listening = true; btn.classList.add("listening"); btn.textContent = "在听…";
    };
    recognition.onend = () => {
      listening = false; btn.classList.remove("listening"); btn.textContent = "语音";
      if (els.input.value.trim()) sendMessage(els.input.value);
    };
    recognition.onerror = (e) => {
      listening = false; btn.classList.remove("listening"); btn.textContent = "语音";
      if (e.error !== "aborted") toast(e.error === "not-allowed" ? "麦克风权限未开启" : "语音识别失败，可改用文字");
    };
    btn.onclick = () => {
      if (listening) { recognition.stop(); return; }
      try { recognition.start(); } catch (_) {}
    };
  }

  function pendingMessages(sessionId) {
    return [...queuedTurns.flatMap((turn) => turn.sessionId === sessionId ? turn.parts : []),
      ...turnQueue.filter((part) => part.sessionId === sessionId)];
  }

  function restoreChatLedger() {
    if (!state.session) return;
    try {
      const saved=chatLedger.restore(state.session.id, els.input.value);
      els.input.value=saved.draft;
      window.XinjiComposerDraft?.save();
      for (const record of saved.pending) {
        uncertainTurns.set(record.session_id, {sessionId:record.session_id, parts:record.parts, transport:record});
      }
      chatBlocked=uncertainTurns.size>0;
      if (saved.pending.length || saved.restored) {
        $('#chat-error').textContent=saved.pending.length
          ? '上次发送状态待核对；原请求已保存在本机。点击「核对发送状态」只读取结果，不会重新发送。'
          : '刚才尚未发出的内容已放回输入框，由你决定是否发送。';
        $('#chat-error').classList.remove('is-hidden');
        $('#chat-recover')?.classList.toggle('is-hidden', !saved.pending.length);
      }
    } catch (error) { chatStorageBlocked=true; toast(error.message); }
  }

  function keepChatDraft() {
    window.XinjiComposerDraft?.save();
    if (state.session) try { chatLedger.saveDraft(state.session.id, els.input.value); } catch (_) { /* Sending fails closed if storage is unavailable. */ }
  }

  function expandTurns(messages) {
    return messages.flatMap((message) => displayedTurns.get(message.id) || [message]);
  }

  function isStandaloneCommand(text) {
    const s = text.trim();
    return s.includes("记住") || ["继续", "继续吧", "安静", "安静一会儿", "停下", "不用了", "别说了"].includes(s)
      || ["继续上次", "回到上次", "上次的书签", "回到书签", "别安排", "不用提醒"].some((word) => s.includes(word));
  }

  function sendMessage(text) {
    const clean = text.trim();
    if (!clean || !state.session) return;
    if (chatStorageBlocked) { toast('本机发送记录未能保存。请先复制输入内容，检查存储后重新打开页面。'); return; }
    if (state.attachingSource) { toast("正在接入来源，请稍后发送。"); return; }
    if (uncertainTurns.has(state.session.id)) { $("#chat-recover").classList.remove("is-hidden"); toast("这次发送状态待核对，请点击「核对发送状态」。"); return; }
    window.XinjiCompanionBoundary?.invalidate();
    if (state.delivery?.pending()) void state.delivery?.stop();
    const part = { id: `local-${++localTurnId}`, role: "user", text: clean,
      created_at: new Date().toISOString(), sessionId: state.session.id };
    part.id='local-'+chatTransport.requestId();
    if(window.XinjiContactContract?.supported(state.companionBoundary?.capabilities())) part.time_zone=window.XinjiContactContract.timeZone();
    try { chatLedger.enqueue(part); }
    catch (error) { toast(error.message); return; }
    if (activeTurn?.sessionId === part.sessionId && activeTurn.transport) {
      chatTransport.cancel(activeTurn.transport);
      $("#thinking .think-note")?.replaceChildren(document.createTextNode("我在听，继续说…"));
    }
    turnQueue.push(part);
    state.messages.push(part);
    renderMessages(true);
    els.input.value = "";
    window.XinjiComposerDraft?.save();
    clearTimeout(turnTimer);
    turnTimer = setTimeout(() => {
      // Keep sessions separate if the user changes conversations during the debounce.
      for (const part of turnQueue) {
        const last = queuedTurns[queuedTurns.length - 1];
        const standalone = isStandaloneCommand(part.text);
        if (last && last.sessionId === part.sessionId && !last.started && !last.standalone && !standalone && last.timeZone === part.time_zone) last.parts.push(part);
        else queuedTurns.push({ sessionId: part.sessionId, parts: [part], standalone, timeZone:part.time_zone });
      }
      turnQueue = [];
      turnTimer = null;
      dispatchTurn();
    }, 850);
  }

  async function dispatchTurn() {
    if (activeTurn || !queuedTurns.length) return;
    const next = queuedTurns.findIndex(turn => !uncertainTurns.has(turn.sessionId));
    if (next < 0) return;
    const turn = queuedTurns.splice(next, 1)[0];
    turn.started = true;
    activeTurn = turn;
    const sameSession = () => state.session?.id === turn.sessionId;
    if (sameSession()) {
      setOrb("thinking");
      chatScroll.render(() => els.messages.insertAdjacentHTML("beforeend", `<div class="msg assistant" id="thinking"><div class="meta"><span>回响</span><span>…</span></div><div class="bubble"><span class="thinking"><i></i><i></i><i></i></span> <span class="think-note">在整理理解…</span></div></div>`));
      $("#stop-btn").classList.remove("is-hidden");
    }
    touchLastSeen();
    try {
      turn.transport ||= {session_id:turn.sessionId, text:turn.parts.map(p=>p.text).join("\n"), memory_proposals:memoryProposal.shouldRequest(turn.sessionId), ...(typeof turn.timeZone === "string" ? {time_zone:turn.timeZone} : {})};
      const data = await chatTransport.send(turn.transport, message => {
        if (sameSession()) { $("#chat-error").textContent = message; $("#chat-error").classList.remove("is-hidden"); }
      }, turn.parts);
      if (sameSession()) $("#chat-recover")?.classList.add("is-hidden");
      const userMessage = data.messages.find((m) => m.id === data.user_message_id);
      if (userMessage && turn.parts.length > 1) displayedTurns.set(userMessage.id, turn.parts);
      if (sameSession()) {
        state.messages = [...expandTurns(data.messages), ...pendingMessages(turn.sessionId)];
        state.memories = data.memories;
        setOrb(data.cancelled ? "listening" : data.state === "quiet" ? "quiet" : data.state === "failed" ? "failed" : "responding");
        if (data.error) toast(`未完成（${data.error}），可重试`);
        renderAll();
        if (!data.cancelled) memoryProposal.offer(turn.sessionId, data);
        loadAudit();
        loadNextStep();
      }
    } catch (e) {
      if (e.notSent && sameSession()) {
        const waiting = [...turn.parts, ...pendingMessages(turn.sessionId)];
        const ids = new Set(waiting.map((part) => part.id));
        queuedTurns = queuedTurns.filter((item) => item.sessionId !== turn.sessionId);
        turnQueue = turnQueue.filter((item) => item.sessionId !== turn.sessionId);
        state.messages = state.messages.filter((item) => !ids.has(item.id));
        els.input.value = [...waiting.map((part) => part.text), els.input.value.trim()].filter(Boolean).join("\n");
        try { chatLedger.returnDraft(turn.sessionId, els.input.value, turn.transport?.request_id); }
        catch (_) { chatStorageBlocked=true; }
        window.XinjiComposerDraft?.save();
        renderMessages();
        setOrb("failed");
        $("#chat-error").textContent = `${e.message}。本条未发送，内容已放回输入框。请先复制保存，再检查服务或本机存储。`;
        $("#chat-error").classList.remove("is-hidden");
        toast("本条未发送，内容已放回输入框。");
      } else {
        chatBlocked = true;
        uncertainTurns.set(turn.sessionId, turn);
        if (sameSession()) {
        $("#chat-error").textContent = "发送结果尚未确认，原请求和待发内容已保存在本机。核对后可继续。";
        $("#chat-error").classList.remove("is-hidden");
        $("#chat-recover")?.classList.remove("is-hidden");
        $("#thinking")?.remove();
        setOrb("failed");
        toast("发送结果尚未确认，请点击「核对发送状态」。");
        }
      }
    } finally {
      activeTurn = null;
      if (sameSession()) void state.companionBoundary?.refresh();
      if (sameSession()) {
        state.delivery?.schedule();
        els.input.focus();
      }
      dispatchTurn();
    }
  }

  function stopWaiting() {
    if (state.delivery?.pending()) { void state.delivery?.stop(); return; }
    if (!activeTurn?.transport) return;
    chatTransport.cancel(activeTurn.transport);
    $("#stop-btn").classList.add("is-hidden");
    setOrb("listening");
    toast("正在停止这次回复，已发送的话会保留。模型请求可能仍在完成。");
  }

  async function recoverChat() {
    const turn = uncertainTurns.get(state.session?.id);
    if (!turn || state.session?.id !== turn.sessionId) return;
    const button = $("#chat-recover"); button.disabled = true;
    try {
      const result = await chatTransport.recover(turn.transport);
      if (state.session?.id !== turn.sessionId) return;
      state.messages = [...expandTurns(result.messages), ...pendingMessages(turn.sessionId)];
      state.memories = result.memories;
      uncertainTurns.delete(turn.sessionId); chatBlocked = uncertainTurns.size > 0;
      button.classList.add("is-hidden"); $("#chat-error").classList.add("is-hidden");
      setOrb(result.cancelled ? "listening" : result.state === "quiet" ? "quiet" : result.state === "failed" ? "failed" : "responding");
      renderAll(); dispatchTurn();
    } catch (error) {
      if (error.uncertain && ["process_interrupted", "execution_uncertain"].includes(error.code)) {
        const snapshot = await api('/api/session/' + encodeURIComponent(turn.sessionId));
        if (state.session?.id !== turn.sessionId) return;
        state.messages = [...snapshot.messages, ...pendingMessages(turn.sessionId)];
        state.memories = snapshot.memories;
        const restored=[turn.transport.text, ...pendingMessages(turn.sessionId).map(p=>p.text), els.input.value].filter(Boolean).join("\n");
        chatLedger.returnDraft(turn.sessionId, restored, turn.transport.request_id);
        queuedTurns=queuedTurns.filter(item=>item.sessionId!==turn.sessionId);
        turnQueue=turnQueue.filter(item=>item.sessionId!==turn.sessionId);
        els.input.value=restored; window.XinjiComposerDraft?.save();
        uncertainTurns.delete(turn.sessionId); chatBlocked = uncertainTurns.size > 0;
        button.classList.add("is-hidden"); setOrb("listening"); renderAll();
        $("#chat-error").textContent = "上次回复结果未确认，已重新读取记录。原文放回输入框，请核对是否已保存再决定发送；没有自动重发。";
        $("#chat-error").classList.remove('is-hidden');
        dispatchTurn();
      } else { toast(error.message); }
    } finally { button.disabled = false; }
  }

  function showMemoryContextNotice() {
    const notice = $("#chat-error");
    notice.textContent = "记忆已更改：相关来源及未确认派生内容暂不用于回复，其他已接入来源会按各自状态保留。";
    notice.classList.remove("is-hidden");
    const insights = $("#insight-panel");
    if (insights) { insights.innerHTML = ""; insights.classList.add("is-hidden"); }
    refreshSourceContext();
  }

  async function refreshSourceContext() {
    if (!state.session) return;
    const sid = state.session.id, epoch = ++sourceUiEpoch;
    try {
      const data = await api(`/api/session/${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid || sourceUiEpoch !== epoch) return;
      state.context = data.context || null;
      state.session = {...state.session, source_context_stale: data.session.source_context_stale, source_label: data.session.source_label};
      renderConnectedSources();
      renderInsightPanel();
      renderStarterBar();
    } catch (_) {
      if (state.session?.id !== sid || sourceUiEpoch !== epoch) return;
      const notice = $("#chat-error");
      notice.textContent = "记忆更改已保存，但来源列表未能同步。请先复制未发送的草稿，再刷新核对来源与理解状态。";
      notice.classList.remove("is-hidden");
    }
  }

  // ---------------- memory actions ----------------
  const memoryDrafts = new Map();

  async function readLatestMemory(id) {
    const sid = state.session?.id;
    const data = await api(`/api/memory?session_id=${encodeURIComponent(sid)}`);
    if (state.session?.id !== sid) return null;
    const latest = (data.memories || []).find(memory => memory.id === id);
    if (latest) {
      const old = state.memories.find(memory => memory.id === id);
      if (old) Object.assign(old, latest);
    }
    return latest || null;
  }

  async function onMemoryAction(ev) {
    const btn = ev.target.closest("[data-act]");
    if (!btn || btn.disabled) return;
    const id = btn.dataset.id;
    const act = btn.dataset.act;
    const item = state.memories.find((m) => m.id === id);
    if (!item) return;
    const snapshot = {...item};
    btn.disabled = true;
    state.memorySaving = true;

    try {
      if (act === "confirm") {
        const out = await window.XinjiMemorySync.patch(api, snapshot, {status: "confirmed"});
        Object.assign(item, out);
        toast("已确认，版本 +1");
      } else if (act === "delete") {
        if (!await window.XinjiDialogs.confirm({title: "忘掉这条记忆", message: "将移除这条记忆，相关来源和未确认派生内容会暂停用于回复。已独立修改的副本仍需分别核对。", confirmLabel: "忘掉这条", danger: true})) return;
        if (!state.memories.some(memory => memory.id === id)) return;
        await window.XinjiMemorySync.remove(api, snapshot);
        memoryDrafts.delete(id);
        state.memories = state.memories.filter((m) => m.id !== id);
        toast("已删除；来源与未确认派生内容暂不参与模型回复。");
        showMemoryContextNotice();
      } else if (act === "edit") {
        startMemoryEdit(id, btn.closest(".mem-item"));
        return;
      } else if (act === "history") {
        toggleHistory(id, btn.closest(".mem-item"));
        return;
      }
      renderAll();
      loadAudit();
      loadNextStep();
    } catch (e) {
      if (window.XinjiMemorySync.isConflict(e)) {
        await readLatestMemory(id).catch(() => null);
        renderMemoryList();
        toast("这条记忆已在别处更新。已重新读取，请先核对内容，再决定是否确认或忘掉。");
        return;
      }
      toast(e.message);
    } finally { btn.disabled = false; state.memorySaving = false; }
  }

  function startMemoryEdit(id, card = null) {
    const item = state.memories.find((m) => m.id === id);
    const node = card || els.memoryList.querySelector(`.mem-item[data-id="${id}"]`);
    if (!item || !node) return;
    const draft = memoryDrafts.get(id) || {text: item.text, version: item.version};
    memoryDrafts.set(id, draft);
    const textNode = node.querySelector(".mem-text");
    textNode.innerHTML = `<textarea class="mem-edit" aria-label="纠正记忆">${esc(draft.text)}</textarea>
      <p class="memory-conflict note" role="status"></p>
      <div style="display:flex;gap:8px;margin-top:8px">
        <button class="mini-btn confirm" data-save="${id}">保存纠正</button>
        <button class="mini-btn is-hidden" data-review="${id}">核对后采用此版本</button>
        <button class="mini-btn" data-cancel="${id}">取消</button>
      </div>`;
    const ta = node.querySelector("textarea");
    ta.oninput = () => { draft.text = ta.value; };
    const save = node.querySelector("[data-save]"), review = node.querySelector("[data-review]"), notice = node.querySelector(".memory-conflict");
    function showConflict() {
      if (!draft.conflict) return;
      notice.textContent = draft.latest ? `已在别处更新为 v${draft.latest.version}：${draft.latest.text}。你的修改仍在输入框中。核对后可采用此版本，再保存修改。` : "这条记忆已变更或移除。你的修改仍在输入框中，请复制保留后重新读取。";
      save.disabled = true;
      review.classList.toggle("is-hidden", !draft.latest);
    }
    showConflict();
    review.onclick = () => {
      if (!draft.latest) return;
      draft.version = draft.latest.version;
      draft.conflict = false;
      save.disabled = false;
      review.classList.add("is-hidden");
      notice.textContent = `已采用 v${draft.version} 作为核对版本。草稿未提交，请再检查并点击保存。`;
    };
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    save.onclick = async () => {
      if (draft.conflict || save.disabled) return;
      save.disabled = true;
      try {
        draft.text = ta.value;
        const out = await window.XinjiMemorySync.patch(api, {id, version: draft.version}, {text: draft.text});
        Object.assign(item, out);
        memoryDrafts.delete(id);
        toast("已纠正；来源与未确认派生内容暂不参与模型回复。");
        showMemoryContextNotice();
        renderAll();
        loadAudit();
        loadNextStep();
      } catch (e) {
        if (window.XinjiMemorySync.isConflict(e)) {
          draft.conflict = true;
          draft.latest = await readLatestMemory(id).catch(() => null);
          showConflict();
        } else { notice.textContent = e.message + " 修改仍保留在输入框中。"; }
      } finally { if (!draft.conflict) save.disabled = false; }
    };
    node.querySelector("[data-cancel]").onclick = () => { memoryDrafts.delete(id); renderAll(); };
  }

  async function toggleHistory(id, card = null) {
    const node = card || els.memoryList.querySelector(`.mem-item[data-id="${id}"]`);
    if (!node) return;
    const existing = node.querySelector(".mem-history");
    if (existing) { existing.remove(); return; }
    try {
      const d = await api(`/api/memory/${id}/history`);
      const rows = (d.revisions || []).map((r) => `<div class="mem-rev">
        <span class="mem-version">v${r.version}</span>
        <span>${esc(r.text)}</span>
        <span class="mem-version">${esc((r.created_at || "").slice(11, 19))}</span>
      </div>`).join("");
      node.insertAdjacentHTML("beforeend",
        `<div class="mem-history"><div class="mem-group-label"><span>版本历史</span><span class="muted">${(d.revisions || []).length}</span></div>${rows || '<p class="note">暂无历史</p>'}</div>`);
    } catch (e) { toast(e.message); }
  }

  // ---------------- bookmark ----------------
  function openBookmarkModal(fromNext = false) {
    const lastAssistant = [...state.messages].reverse().find((m) => m.role === "assistant");
    const cite = lastAssistant?.citations?.find(cite => window.XinjiFeishuAccountPicker?.isMemoryCitation(cite));
    state.bmSessionId = state.session?.id;
    state.bmSource = cite
      ? { source_memory_id: cite.id, source_version: cite.version, source_label: state.session?.source_label || "依据", source_quote: cite.text || "" }
      : { source_memory_id: "", source_version: 0, source_label: state.session?.source_label || "", source_quote: "" };
    els.bmNote.value = lastAssistant ? lastAssistant.text.slice(0, 120) : "";
    els.bmChoice.value = "";
    if (!fromNext) els.bmNext.value = "";
    if (state.nextStep && fromNext) els.bmNext.value = state.nextStep.step;
    els.modal.classList.remove("is-hidden");
    els.bmNote.focus();
  }

  async function saveBookmark() {
    if (!state.session) return;
    if (state.bmSessionId && state.bmSessionId !== state.session.id) { toast("对话状态已变化，请重新核对并打开书签。"); return; }
    const sid = state.session.id;
    if (state.bmSource?.source_attachment_id && !connectedSources().some(source => source.id === state.bmSource.source_attachment_id)) {
      toast("书签对应的来源已移除，请核对后重新标记。"); return;
    }
    if (!els.bmNote.value.trim()) { toast("先写一句：停在了哪里"); return; }
    try {
      const b = await api("/api/bookmark", {
        method: "POST",
        body: JSON.stringify({
          session_id: sid,
          note: els.bmNote.value.trim(),
          choice: els.bmChoice.value.trim(),
          next_step: els.bmNext.value.trim(),
          ...state.bmSource,
        }),
      });
      if (state.session?.id !== sid) return;
      state.bookmark = b;
      els.modal.classList.add("is-hidden");
      renderBookmark();
      switchTab("bookmark");
      toast("已存为草稿，确认后才是真书签");
      loadAudit();
    } catch (e) { toast(e.message); }
  }

  async function commitBookmark() {
    if (!state.bookmark) return;
    try {
      const b = await api(`/api/bookmark/${state.bookmark.id}/commit`, { method: "POST" });
      state.bookmark = b;
      renderBookmark();
      toast("已保存 · 回执已生成");
      touchLastSeen();
      loadAudit();
    } catch (e) { toast(e.message); }
  }

  // ---------------- misc ----------------
  let pairedDevicesPanel = null;
  function switchTab(name) {
    pairedDevicesPanel?.suspend();
    state.tab = name;
    if (typeof setDesignPanel === "function") setDesignPanel(true);
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $$(".tab-panel").forEach((p) => p.classList.add("is-hidden"));
    $(`#tab-${name}`)?.classList.remove("is-hidden");
    if (name === "design") {
      pairedDevicesPanel?.dispose();
      pairedDevicesPanel = window.XinjiPairedDevices?.mount($("#paired-devices"), {api, getSessionId:() => state.session?.id, visible:() => state.tab === "design"});
    }
    if (name === "today") loadToday();
    if (name === "bookmark") loadTaskActions();
    if (name === "apps") return loadAppsCatalog();
    if (name === "audit") loadAudit();
    if (name === "metrics") loadMetrics();
    if (name === "data") loadData();
    if (name === "persona" && typeof loadPersonaPicker === "function") loadPersonaPicker();
  }

  let todaySources = [];

  function putTodayDraft(text, sid) {
    if (!text || state.session?.id !== sid) return;
    const previous = els.input.value.trim();
    els.input.value = previous ? `${previous}\n${text}` : text;
    els.input.focus();
  }

  function bookmarkTodayStep(step, sid) {
    if (!step || state.session?.id !== sid) return;
    openBookmarkModal(false);
    els.bmNext.value = step;
    if (!els.bmNote.value.trim()) els.bmNote.value = "想留下的下一步";
  }

  async function loadToday(snapshot = null) {
    if (!state.session) return;
    const body = $("#today-body");
    if (!body) return;
    const sid = state.session.id, epoch = sourceUiEpoch;
    try {
      const [sess, acts, next] = snapshot?.conversation && snapshot?.next
        ? [snapshot.conversation, snapshot.actions, snapshot.next]
        : await Promise.all([
          api(`/api/session/${encodeURIComponent(sid)}`), api(`/api/actions?session_id=${encodeURIComponent(sid)}`), api(`/api/next-step?session_id=${encodeURIComponent(sid)}`),
        ]);
      if (state.session?.id !== sid || epoch !== sourceUiEpoch) return;
      const attached = connectedSources(sess.context, sess.session), bm = sess.bookmark;
      const actions = acts.actions || [], memories = sess.memories || [];
      const latest = memories.filter(item => item.status === "confirmed").slice(-1)[0];
      const hasBackground = memories.some(item => item.status !== "deleted") || attached.length > 0;
      const step = hasBackground ? String(next.step || "").trim() : "";
      const draft = bm?.next_step || step || "今天有件事，我想慢慢聊聊。";
      $("#today-apps-list").innerHTML = attached.length ? attached.map(source => `<button type="button" class="app-pill ready" data-today-source="${esc(source.id || "")}">${esc(sourceDisplayName(source))} · ${source.stale ? "待核对" : "已接入"}</button>`).join("") : `<button type="button" class="text-btn" id="today-connect-source">选择一份背景资料 →</button>`;
      body.innerHTML = `<div class="today-hello"><b>从这一刻继续</b><p>${latest ? `你确认过：${esc(latest.text)}。` : "聊过的事、愿意留下的记忆和小安排，会慢慢聚在这里。"}</p><div class="row"><button type="button" class="mini-btn confirm" id="today-continue">继续聊聊</button>${latest ? `<button type="button" class="mini-btn" id="today-memory">看记忆</button>` : ""}</div></div>
        ${step ? `<div class="today-card"><div class="k">下一步 · 建议</div><b>${esc(step)}</b><p>${esc(next.rationale || "先核对是否适合此刻，再决定要不要做。")}</p><div class="row"><button type="button" class="mini-btn" id="today-understand">查看理解</button><button type="button" class="mini-btn" id="today-bookmark">存成书签</button></div></div>` : `<div class="today-card"><div class="k">按自己的节奏</div><b>先从一件小事开始</b><p>可以留一份消息草稿，或聊聊今天正在发生的事。</p><div class="row"><button type="button" class="mini-btn" id="today-new-draft">写一段消息草稿</button><button type="button" class="mini-btn" id="today-new-reminder">记下一件小事</button></div></div>`}
        ${bm ? `<div class="today-card"><div class="k">上次留下的书签</div><b>${esc(bm.note)}</b><p>${esc(bm.next_step || bm.choice || "你可以继续，也可以重新选择。")}</p><button type="button" class="mini-btn" id="today-bookmark-tab">查看书签</button></div>` : ""}
        ${actions.slice(0, 3).map((action, index) => `<div class="today-card"><div class="k">本机动作记录 · ${esc({message:"消息草稿", reminder:"提醒", calendar:"日历"}[action.kind] || action.kind)}</div><b>${esc(action.title)}</b><p>${esc(actionStatusLabel(action))}${action.when_text ? ` · ${esc(action.when_text.replace("T", " "))}` : ""}</p><button type="button" class="mini-btn" data-today-task="${index}">${action.status === "previewed" ? "继续确认" : "查看任务"}</button></div>`).join("")}
        <div class="today-footer-actions"><button type="button" class="mini-btn" id="today-tasks">看任务</button><button type="button" class="mini-btn" id="today-connect">连接应用</button></div>`;
      $("#today-continue")?.addEventListener("click", () => putTodayDraft(draft, sid));
      $("#today-memory")?.addEventListener("click", () => { if (state.session?.id === sid) switchTab("memory"); });
      $("#today-understand")?.addEventListener("click", () => { if (state.session?.id === sid) switchTab("understanding"); });
      $("#today-bookmark")?.addEventListener("click", () => bookmarkTodayStep(step, sid));
      $("#today-bookmark-tab")?.addEventListener("click", () => { if (state.session?.id === sid) switchTab("bookmark"); });
      $("#today-tasks")?.addEventListener("click", () => { if (state.session?.id === sid) switchTab("bookmark"); });
      $("#today-new-draft")?.addEventListener("click", () => { if (state.session?.id === sid) openAction("message", -1, {title: "", text: "", manual: true}); });
      $("#today-new-reminder")?.addEventListener("click", () => { if (state.session?.id === sid) openAction("reminder", -1, {title: "", text: "", manual: true}); });
      for (const selector of ["#today-connect", "#today-connect-source"]) $(selector)?.addEventListener("click", () => { if (state.session?.id === sid) openApps(); });
      body.querySelectorAll("[data-today-task]").forEach(button => button.onclick = () => {
        if (state.session?.id !== sid) return;
        const action = actions[Number(button.dataset.todayTask)];
        switchTab("bookmark"); if (action?.status === "previewed") openSavedAction(action);
      });
      $("#today-apps-list").querySelectorAll("[data-today-source]").forEach(button => button.onclick = () => { if (state.session?.id === sid) openApps(); });
    } catch (error) { if (state.session?.id === sid && epoch === sourceUiEpoch) body.innerHTML = `<p class="note">读取失败：${esc(error.message)}</p><button type="button" class="btn ghost small" id="today-retry">重新读取</button>`; $("#today-retry")?.addEventListener("click", loadToday); }
  }

  let authPollTimer = null;
  let authGeneration = 0, authActive = false;
  let authPollGeneration = null, authPopup = null, authPurpose = "document", authForce = false;
  let authSession = null, larkConnectedThisPage = false;
  let authReturnToSource = false;
  function larkCanChooseDocuments() {
    const context = state.context;
    const sources = Array.isArray(context?.sources) ? context.sources : context ? [context] : [];
    return larkConnectedThisPage || sources.some(source => source?.connector_id === "feishu" && !source.stale && !state.session?.source_revoked);
  }
  function reserveLarkAuthWindow() {
    const slot = {window: null, navigated: false};
    if (typeof window.xinjiDesktop?.openLarkAuth === "function") {
      slot.native = window.xinjiDesktop.openLarkAuth.bind(window.xinjiDesktop);
      slot.nativeRequested = false; slot.nativePending = false;
      return slot;
    }
    try { slot.window = window.open?.("about:blank", "_blank") || null; if (slot.window) slot.window.opener = null; }
    catch (_) { try { slot.window?.close(); } catch (_) {} slot.window = null; }
    return slot;
  }
  function discardLarkAuthWindow(slot) {
    if (!slot?.navigated) { try { slot?.window?.close(); } catch (_) {} }
  }
  function officialLarkAuthURL(value) {
    if (typeof value !== "string" || value.length > 8192 || value.trim() !== value) return null;
    try {
      const url = new URL(value);
      return url.protocol === "https:" && !url.username && !url.password && (!url.port || url.port === "443") &&
        ["accounts.feishu.cn", "accounts.larksuite.com"].includes(url.hostname) ? value : null;
    } catch (_) { return null; }
  }
  function returnFromLarkAuth({documentReady = false} = {}) {
    if (!authReturnToSource) return;
    authReturnToSource = false;
    prepareSourceDialog();
    showWz(3);
    if (authPurpose === "account") { renderFeishuAccount(); return; }
    if (documentReady) { renderFeishuPicker(); return; }
    $("#read-head").innerHTML = '<h2 class="wz-title">本次飞书连接尚未完成</h2><p class="note">还没有读取文档。关闭授权窗不会撤销已发起的授权，可以重新连接或先回到聊天。</p><button type="button" class="btn primary small" id="feishu-connect-again">重新连接飞书</button>';
    $("#read-items").innerHTML = "";
    $("#feishu-connect-again").onclick = () => startLarkAuth("document", {force: true});
  }
  function authCurrent(generation) { return authActive && generation === authGeneration && (state.session?.id || null) === authSession; }
  function clearAuthLinks() {
    $("#auth-url").classList.add("is-hidden"); $("#auth-url").removeAttribute("href"); $("#auth-url").textContent = "在飞书中打开授权";
    $("#auth-qr").classList.add("is-hidden"); $("#auth-qr").removeAttribute("src");
  }
  function closeLarkAuth() {
    ++authGeneration; authActive = false; authPollGeneration = null;
    clearInterval(authPollTimer); authPollTimer = null;
    discardLarkAuthWindow(authPopup); authPopup = null;
    clearAuthLinks();
    $("#auth-modal").classList.add("is-hidden");
    returnFromLarkAuth();
  }
  function failAuth(generation, message, response = {}) {
    if (!authCurrent(generation)) return;
    authActive = false; clearInterval(authPollTimer); authPollTimer = null;
    clearAuthLinks(); discardLarkAuthWindow(authPopup); authPopup = null;
    $("#auth-status").textContent = message || "连接尚未完成，请重新发起授权。";
    $("#auth-hint").textContent = "旧授权链接已停止显示。不会自动重试或创建新的 CLI 应用。";
    $("#auth-retry").classList.remove("is-hidden"); $("#auth-retry").disabled = false;
    if (response.error_code === "needs_app_setup" && response.setup_url === "https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md") {
      $("#auth-url").href = response.setup_url;
      $("#auth-url").textContent = "首次配置飞书 CLI 应用";
      $("#auth-url").classList.remove("is-hidden");
      $("#auth-hint").textContent = "先按官方指南完成首次应用配置，再回来重新发起授权。这里不会自动创建应用。";
    }
  }

  async function startLarkAuth(purpose = "document", {force = false} = {}) {
    // Reserve while still inside the user's click. No credentials or authorization URL are stored.
    const popup = reserveLarkAuthWindow();
    if (globalThis.XinjiSourceDialog?.isOpen()) { authReturnToSource = true; closeSourceDialog(); }
    $("#apps-modal")?.classList.add("is-hidden");
    discardLarkAuthWindow(authPopup); authPopup = popup;
    const generation = ++authGeneration;
    const currentPurpose = ["search", "account"].includes(purpose) ? purpose : "document";
    authPurpose = currentPurpose; authForce = force === true; authSession = state.session?.id || null;
    if (currentPurpose === "document") larkConnectedThisPage = false;
    authActive = true; authPollGeneration = null;
    $("#auth-modal").classList.remove("is-hidden");
    $("#auth-cancel")?.focus();
    clearAuthLinks();
    $("#auth-hint").textContent = "正在唤起飞书官方授权…";
    $("#auth-status").textContent = "等待你在飞书中确认…";
    $("#auth-retry").classList.add("is-hidden"); $("#auth-retry").disabled = true;
    $("#auth-retry").onclick = () => startLarkAuth(authPurpose, {force: authForce});
    clearInterval(authPollTimer); authPollTimer = null;
    try {
      const options = {method: "POST"};
      if (authForce) options.body = JSON.stringify({force: true});
      const value = await api(currentPurpose === "account" ? "/api/auth/lark/account/start" : currentPurpose === "search" ? "/api/auth/lark/search/start" : "/api/auth/lark/start", options);
      if (!authCurrent(generation)) { discardLarkAuthWindow(popup); return; }
      if (value.status === "success") { authDone(generation, currentPurpose); return; }
      if (value.status !== "starting" && value.status !== "pending") { failAuth(generation, value.error || "无法启动飞书连接，请重试。", value); return; }
      if (value.status === "pending") { if (!showLarkPending(value, currentPurpose, generation)) return; }
      else $("#auth-hint").textContent = "授权正在准备，请稍候…";
      authPollTimer = setInterval(() => pollLarkAuth(generation, currentPurpose), 2000);
    } catch (error) { failAuth(generation, error.message || "暂时无法连接授权服务，请重试。"); }
  }

  function showLarkPending(value, purpose, generation) {
    if (!authCurrent(generation)) return false;
    const url = officialLarkAuthURL(value.url);
    if (!url) { failAuth(generation, "授权地址不是有效的飞书官方 HTTPS 地址，请重新连接。"); return false; }
    $("#auth-url").href = url; $("#auth-url").classList.remove("is-hidden");
    if (typeof value.qr === "string" && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(value.qr)) { $("#auth-qr").src = value.qr; $("#auth-qr").classList.remove("is-hidden"); }
    const slot = authPopup;
    const updateHint = () => {
      if (!authCurrent(generation) || authPopup !== slot) return;
      $("#auth-hint").textContent = (purpose === "account" ? "请在飞书核对搜索和文档只读权限；授权后会自动完成连接并回到聊天。" : purpose === "search" ? "将单独申请搜索云空间权限。" : "只连接现有飞书 CLI，不会新建应用。") +
        (slot?.nativePending ? "正在请求系统浏览器打开飞书官方页面，也可点击下方链接。" : slot?.navigated ?
          slot.native ? "已请求系统浏览器打开飞书官方页面；若未打开，可点击下方链接。" : "请在已打开的飞书官方页面确认；也可使用下方链接。" :
          "未能自动打开页面，请点击下方链接继续授权。");
    };
    if (slot?.native && !slot.nativeRequested) {
      slot.nativeRequested = true; slot.nativePending = true;
      const settled = opened => {
        if (!authCurrent(generation) || authPopup !== slot) return;
        slot.nativePending = false; slot.navigated = opened === true; updateHint();
      };
      try { Promise.resolve(slot.native(url)).then(settled, () => settled(false)); } catch (_) { settled(false); }
    } else if (!slot?.navigated && slot?.window) {
      try { if (!slot.window.closed) { slot.window.location.replace(url); slot.navigated = true; } } catch (_) {}
    }
    updateHint();
    return true;
  }

  async function pollLarkAuth(generation, purpose) {
    if (!authCurrent(generation) || authPollGeneration === generation) return;
    authPollGeneration = generation;
    try {
      const value = await api(purpose === "account" ? "/api/auth/lark/account/status" : purpose === "search" ? "/api/auth/lark/search/status" : "/api/auth/lark/status");
      if (!authCurrent(generation)) return;
      if (value.status === "success") { await authDone(generation, purpose); return; }
      if (value.status === "pending") { showLarkPending(value, purpose, generation); return; }
      if (value.status !== "starting") failAuth(generation, value.error || "授权已失效或未完成，请重新连接。", value);
    } catch (error) { failAuth(generation, "暂时无法核对授权结果，请重试。不会自动重新授权。"); }
    finally { if (authPollGeneration === generation) authPollGeneration = null; }
  }

  async function authDone(generation, purpose) {
    if (!authCurrent(generation)) return;
    authActive = false; clearInterval(authPollTimer); authPollTimer = null;
    discardLarkAuthWindow(authPopup); authPopup = null; clearAuthLinks();
    if (purpose === "account") {
      $("#auth-status").textContent = "授权已完成，正在连接…";
      $("#auth-hint").textContent = "完成后会自动回到聊天。";
      try {
        const data = await api('/api/lark/account/connect', {method:'POST', body:JSON.stringify({session_id:authSession,start_intro:true})});
        if (generation !== authGeneration || (state.session?.id || null) !== authSession) return;
        if (data?.ok !== true || data.enabled !== true || data.ready === false) throw Error([data?.error || '连接尚未完成', data?.hint].filter(Boolean).join(' · '));
        state.feishuAccount = data; window.XinjiFeishuAccountPicker.syncBadges(document, data);
        authReturnToSource = false; $("#auth-modal").classList.add("is-hidden");
        finishConnection(data); toast('飞书已连接');
      } catch (error) {
        if (generation !== authGeneration || (state.session?.id || null) !== authSession) return;
        $("#auth-status").textContent = error.message + ' 请关闭后重新核对连接状态。';
        $("#auth-hint").textContent = '还没有确认连接成功。';
      }
      return;
    }
    const documentReady = purpose === "document";
    if (documentReady) larkConnectedThisPage = true;
    $("#auth-status").textContent = documentReady ? "已连接当前飞书 CLI，请选择文档。" : "搜索授权流程已完成，请重试搜索；如仍失败可粘贴文档链接。";
    $("#auth-hint").textContent = "还没有读取文档；选择后仍需预览和确认。";
    setTimeout(() => {
      if (generation !== authGeneration || (state.session?.id || null) !== authSession) return;
      $("#auth-modal").classList.add("is-hidden");
      const returning = authReturnToSource;
      returnFromLarkAuth({documentReady: documentReady || larkCanChooseDocuments()});
      if (!returning && !els.onboarding.classList.contains("is-hidden")) { showWz(2); loadRealSources(true); }
      loadToday();
    }, 800);
    toast(documentReady ? "已连接飞书，请选择文档" : "搜索授权流程已完成，请重试搜索");
  }

  let appsCatalogRequest = 0;
  async function openApps() { return switchTab("apps"); }

  async function loadAppsCatalog() {
    const grid = $("#apps-grid"), sid = state.session?.id, request = ++appsCatalogRequest;
    if (!grid) return;
    grid.innerHTML = `<p class="muted">正在检查本机可用来源…</p>`;
    const connected = $("#apps-connected"), sources = connectedSources();
    if (connected) { connected.innerHTML = sourceListMarkup(sources); bindSourceRemoval(connected, sources, sid); }
    try {
      const [data] = await Promise.all([api("/api/onboarding/sources"), readFeishuAccountState()]);
      if (state.session?.id !== sid || state.tab !== "apps" || request !== appsCatalogRequest) return;
      const list = data.sources || [];
      if (connected && !sources.length) connected.innerHTML = sourceListMarkup(sources);
      const labels = {ready:"可选择", needs_click:"需系统权限", needs_config:"需配置", needs_auth:"需授权", needs_install:"需安装", unavailable:"暂不可用", empty:"没有可读内容"};
      grid.innerHTML = list.map(source => `<div class="app-card"><div class="ico">${esc(source.icon)}</div><div class="app-source-content"><b>${esc(source.name)}</b><small>${esc(source.id === "apple_calendar" ? "过去 7 天的日程" : source.id === "apple_reminders" ? "最近 7 天有更新的提醒" : source.blurb || "")}</small><span class="status" ${source.id === "feishu" ? "data-feishu-account-status" : `data-connection-source="${esc(source.id)}" data-connection-idle="${esc(labels[source.status] || source.status)}"`}>${esc(source.id === "feishu" ? window.XinjiFeishuAccountPicker.statusLabel(state.feishuAccount) : window.XinjiConnectionIntro.connected(state.context,source.id) ? "✓ 已连接" : labels[source.status] || source.status)}</span></div><button type="button" class="btn ghost small" data-app-source="${esc(source.id)}" ${source.id === "feishu" ? "data-feishu-account-control" : `data-connection-control="${esc(source.id)}" data-connection-idle="连接"`}>${source.id === "feishu" ? state.feishuAccount?.enabled ? "管理连接" : "连接" : window.XinjiConnectionIntro.connected(state.context,source.id) ? "管理" : source.status === "ready" || source.status === "needs_click" ? "连接" : "查看"}</button></div>`).join("") + `<div class="app-card"><div class="ico">⌁</div><div class="app-source-content"><b>Rokid 眼镜</b><small>设备与官方接口待联调</small><span class="status">尚未可用</span></div><button type="button" class="btn ghost small" id="apps-rokid">能力说明</button></div>`;
      grid.querySelectorAll("[data-app-source]").forEach(button => button.onclick = async () => {
        if (state.session?.id !== sid || state.tab !== "apps") return;
        const id = button.dataset.appSource;
        if (id === "feishu" || id === "apple_calendar" || id === "windows_calendar" || id === "local_files") return openCompanionSource({feishu:"feishu", apple_calendar:"calendar", windows_calendar:"calendar", local_files:"local"}[id]);
        prepareSourceDialog(); await openRealSource(id, list.find(source => source.id === id));
      });
      $("#apps-rokid")?.addEventListener("click", () => { if (state.session?.id === sid) openCompanionSource("rokid"); });
    } catch (error) {
      if (state.session?.id === sid && request === appsCatalogRequest) grid.innerHTML = `<p class="note">状态检查失败：${esc(error.message)}。可以点「重新检查」。</p>`;
    }
  }

  async function loadTaskActions(snapshot = null) {
    const el = $("#task-actions");
    if (!el || !state.session) return;
    const sid = state.session.id, epoch = sourceUiEpoch;
    try {
      const d = snapshot || await api(`/api/actions?session_id=${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid || epoch !== sourceUiEpoch || $("#task-actions") !== el) return;
      const acts = d.actions || [];
      el.innerHTML = acts.length ? window.XinjiActionCards.html(acts, {interactive: true})
        : `<p class="muted small">还没有动作。可以在上方新建消息草稿、提醒或日历安排。</p>`;
      window.XinjiActionCards.bind(el, acts, {onContinue: action => { if (state.session?.id === sid) openSavedAction(action); }, onCheck: action => { if (state.session?.id === sid) checkActionStatus(action); }});
    } catch (e) {
      if (state.session?.id === sid && epoch === sourceUiEpoch && $("#task-actions") === el) el.innerHTML = `<p class="note">${esc(e.message)}</p>`;
    }
  }

  function renderDataSummary(sess,acts,sid=state.session?.id) {
    if(state.session?.id!==sid || sess.session?.id!==sid)return;
      const sources = connectedSources(sess.context, sess.session);
      const m = sess.memories || [];
      const confirmed = m.filter((x) => x.status === "confirmed").length;
      const bm = sess.bookmark;
      const actions = acts.actions || [];
      const sourceName = (sess.session.source_label || "新对话");
      $("#data-body").innerHTML = `
        <div class="data-block"><div class="k">已接入的资料</div><div class="v">${sources.length} 份来源</div>
          <div id="data-connected-sources">${sourceListMarkup(sources)}</div>
          <div class="s">每份来源可分别移除；其他来源及手动记忆会保留。</div></div>
        <div class="data-block"><div class="k">记忆</div><div class="v">${m.length} 条</div>
          <div class="s">已确认 ${confirmed} · 待确认 ${m.length - confirmed} · 版本历史保留</div></div>
        <div class="data-block"><div class="k">动作 / 书签</div><div class="v">${actions.length + (bm ? 1 : 0)}</div>
          <div class="s">${bm ? "书签：" + esc(bm.note.slice(0, 20)) + " · " : ""}提醒/日历 ${actions.length} 条</div>
          ${actions.map((a) => `<div class="action-line"><b>${esc(a.kind)} · ${esc(a.title.slice(0, 18))}</b><span>${esc(actionStatusLabel(a))}${a.receipt ? " · " + esc(a.receipt.slice(0, 16)) : ""}</span></div>`).join("")}</div>
        <div class="data-block"><div class="k">原始内容</div><div class="v">仅本地</div>
          <div class="s">对话与所选内容会保存在本机；模型调用会发送相关上下文给模型服务。</div></div>
        <div class="data-block"><div class="k">下载</div>
          <div class="s">源码包与本机启动说明已随本次交付提供。</div>
          <div class="s">本轮另有内含运行环境的 Apple Silicon Mac 包与 Windows 便携包；平台验收范围见随包说明，原生手机端交付源码。</div></div>`;
      bindSourceRemoval($("#data-connected-sources"), sources, sid);
  }

  async function loadData() {
    if (!state.session) return;
    const sid = state.session.id, epoch = sourceUiEpoch;
    try {
      const [sess, acts] = await Promise.all([
        api(`/api/session/${encodeURIComponent(sid)}`),
        api(`/api/actions?session_id=${encodeURIComponent(sid)}`),
      ]);
      if (state.session?.id !== sid || epoch !== sourceUiEpoch) return;
      const ms = await api("/api/settings/model");
      if (state.session?.id !== sid || epoch !== sourceUiEpoch) return;
      $("#model-status").textContent = ms.configured
        ? `已启用：${ms.model} @ ${ms.base_url}${ms.managed_by_environment ? "。由本机启动环境提供，未复制密钥到此副本；更换需调整启动环境并重启。" : ""}`
        : "当前：规则引擎（未配置模型）";
      for (const id of ["#ms-save", "#ms-clear", "#ms-base", "#ms-model", "#ms-key"]) $(id).disabled = !!ms.managed_by_environment;
      if (ms.model) $("#ms-model").value = ms.model;
      if (ms.base_url) $("#ms-base").value = ms.base_url;
      $("#ms-key").placeholder = ms.managed_by_environment ? "启动环境已提供，不回显密钥" : ms.has_key ? "已保存（留空则保留当前 key）" : "API Key";
      renderDataSummary(sess,acts,sid);
    } catch (e) { if (state.session?.id === sid && epoch === sourceUiEpoch) toast(e.message); }
  }

  let metricsAll = false;

  async function loadMetrics() {
    try {
      const q = `?session_id=${encodeURIComponent(state.session.id)}`;
      const m = await api(`/api/metrics${q}`);
      const mem = m.memories || {};
      const bm = m.bookmarks || {};
      const model = m.model || {};
      const pct = (x) => `${Math.round((x || 0) * 100)}%`;
      $("#metrics-body").innerHTML = `
        <div class="metrics-grid">
          <div class="metric-card"><div class="k">对话记录</div><div class="v">${m.messages}</div><div class="s">条消息 · ${m.audit_events} 条审计</div></div>
          <div class="metric-card"><div class="k">确认率</div><div class="v">${pct(m.rates.confirm)}</div><div class="s">${mem.confirmed || 0} 已确认 / ${mem.total || 0} 条理解</div><div class="metric-bar"><span style="width:${(m.rates.confirm||0)*100}%"></span></div></div>
          <div class="metric-card"><div class="k">纠正次数</div><div class="v">${m.corrections}</div><div class="s">${m.revisions} 个版本快照</div></div>
          <div class="metric-card"><div class="k">书签完成率</div><div class="v">${pct(m.rates.bookmark)}</div><div class="s">${bm.committed || 0} 已确认 / ${(bm.committed||0)+(bm.draft||0)} 个</div><div class="metric-bar"><span style="width:${(m.rates.bookmark||0)*100}%"></span></div></div>
          <div class="metric-card"><div class="k">模型</div><div class="v">${model.calls || 0}</div><div class="s">调用 · 降级 ${model.fallbacks || 0}</div></div>
          <div class="metric-card"><div class="k">飞书只读</div><div class="v">${(m.lark||{}).reads || 0}</div><div class="s">按权限只读 · 可断开</div></div>
        </div>
        <p class="note">记录来自当前对话与本机审计，不展示其他历史对话的统计。</p>`;
      $("#metrics-scope").textContent = "当前对话";
    } catch (e) { toast(e.message); }
  }

  async function exportData() {
    if (!state.session) return;
    try {
      const data = await api(`/api/export?session_id=${encodeURIComponent(state.session.id)}`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `xinji-echo-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast("已导出对话数据");
    } catch (e) { toast(e.message); }
  }

  async function revokeSource() { return revokeSelectedSource(); }

  async function revokeSelectedSource(sourceId = null) {
    if (!state.session || state.attachingSource || state.revokingSource || state.confirmingSource) return;
    if (typeof sourceId !== "string" || !sourceId) sourceId = null;
    const sources = connectedSources();
    const selected = sourceId ? sources.find(source => source.id === sourceId) : null;
    if (sourceId && !selected) { toast("来源列表已变化，请重新核对。"); renderConnectedSources(); return; }
    const label = selected ? `「${sourceDisplayName(selected)}」` : "全部已接入来源";
    const approvalSid = state.session.id;
    state.confirmingSource = true;
    let approved = false;
    try { approved = await window.XinjiDialogs.confirm({title: "收回资料", message: `将从当前对话移除${label}及其派生记忆。${selected ? "其他已接入来源、手动记忆会保留。" : "手动记忆会保留。"}历史消息、已独立修改的副本和第三方授权需要分别处理。`, confirmLabel: "移除所选资料", danger: true}); }
    finally { state.confirmingSource = false; }
    if (!approved || state.session?.id !== approvalSid || state.attachingSource || state.revokingSource) return;
    if (sourceId && !connectedSources().some(source => source.id === sourceId)) { toast("资料已变化，请重新核对。"); return; }
    const sid = state.session.id, epoch = ++sourceUiEpoch;
    window.XinjiCompanionBoundary?.invalidate();
    state.revokingSource = true;
    let revoked = false;
    try {
      const r = await api("/api/source/revoke", {
        method: "POST", body: JSON.stringify({session_id: sid, ...(sourceId ? {source_id: sourceId} : {})}),
      });
      if (!r.ok) throw new Error(r.reason || "无法撤回来源");
      revoked = true;
      const data = await api(`/api/session/${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid || sourceUiEpoch !== epoch) return;
      enterSession(data, {skipIntro: true, preserveDrafts: true});
      state.nextStep = null;
      renderNextStep();
      loadNextStep();
      toast(`${selected ? "所选来源" : "全部来源"}已撤回，清理 ${r.cleaned || 0} 条派生记忆`);
      if (r.review_required) {
        const notice = $("#chat-error");
        notice.textContent = `另有 ${r.review_required} 条来源待核对的记忆或关联副本仍保存在关联记录中，已暂停用于模型和自动建议。请在记忆中逐条核对、确认或删除；历史消息、书签和第三方授权需另行处理。`;
        notice.classList.remove("is-hidden");
      }
      loadAudit();
    } catch (e) {
      if (state.session?.id !== sid || sourceUiEpoch !== epoch) return;
      const notice = $("#chat-error");
      notice.textContent = revoked
        ? "来源已撤回，但界面未能同步。请先复制尚未发送的内容，再刷新页面核对。"
        : "未能确认撤回结果。请先复制尚未发送的内容，再刷新页面核对。";
      notice.classList.remove("is-hidden");
      toast(notice.textContent);
    } finally { state.revokingSource = false; }
  }

  function resetAll() {
    if (!confirm("重新开始会丢失当前会话展示（数据仍在本机 SQLite）。继续？")) return;
    localStorage.removeItem("xinji_session");
    location.reload();
  }

  // ---------------- boot ----------------
  function bind() {
    $("#mindlink-toggle")?.addEventListener("click", toggleMindlink);
    document.addEventListener("visibilitychange", mindlinkVisibilityChanged);
    window.addEventListener("pagehide", stopMindlink);
    window.addEventListener("pagehide", clearCredentialForms);
    renderCredentialPendingNotice();
    $("#source-uncertain-history")?.addEventListener("click", restore);
    $("#source-uncertain-dismiss")?.addEventListener("click", () => {
      try { localStorage.removeItem(credentialPendingKey); } catch (_) {}
      renderCredentialPendingNotice();
    });
    if (window.xinjiDesktop) $("#desktop-badge")?.classList.remove("is-hidden");
    $("#local-file-btn").onclick = openLocalFiles;

    $("#alt-toggle").onclick = () => $("#alt-panel").classList.toggle("is-hidden");
    $("#onboarding-return")?.addEventListener("click", () => closeSourceDialog());
    $("#wz-skip")?.addEventListener("click", () => { closeSourceDialog(); if (!state.session) startSession("empty"); });
    $("#open-connect")?.addEventListener("click", openApps);
    $("#composer-connect")?.addEventListener("click", openApps);
    $("#apps-refresh")?.addEventListener("click", openApps);
    $$("[data-new-action]").forEach(button => button.addEventListener("click", () => openAction(button.dataset.newAction, -1, {title: "", text: "", manual: true})));
    $("#skip-connect")?.addEventListener("click", () => els.input.focus());
    $$("[data-companion-source]").forEach((button) => button.addEventListener("click", () => openCompanionSource(button.dataset.companionSource)));
    $("#wz-back-2").onclick = () => { closeSourceDialog(); openApps(); };
    $("#wz-read").onclick = () => readConfirmedSource();
    $("#wz-start").onclick = () => startRealSource(false);
    $("#wz-edit").onclick = () => startRealSource(true);

    $("#paste-start").onclick = () => {
      const text = $("#seed-text").value.trim();
      if (!text) { toast("先粘贴一段资料，或直接用示例开始"); return; }
      startSession("paste", text);
    };

    els.composer.addEventListener("submit", (e) => {
      e.preventDefault();
      sendMessage(els.input.value);
    });

    els.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage(els.input.value);
      }
    });

    document.addEventListener("click", onMemoryAction);
    window.addEventListener("pagehide", touchLastSeen);
    document.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-insight]");
      if (b) { openInsightBookmark(Number(b.dataset.insight), b.dataset.insightSource); return; }
      const a = ev.target.closest("[data-action]");
      if (a) openAction(a.dataset.action, Number(a.dataset.insightIdx), null, a.dataset.insightSource);
    });
    $("#action-cancel").onclick = closeAction;
    $("#action-confirm").onclick = confirmAction;
    $("#resume-dismiss")?.addEventListener("click", () => $("#resume-banner").classList.add("is-hidden"));
    document.addEventListener("click", (ev) => {
      const c = ev.target.closest("[data-mem]");
      if (!c) return;
      switchTab("memory");
      const item = document.querySelector(`.mem-item[data-id="${c.dataset.mem}"]`);
      if (item) {
        item.scrollIntoView({ block: "center" });
        item.classList.add("flash");
        setTimeout(() => item.classList.remove("flash"), 1600);
      }
    });

    $("#create-bookmark-btn")?.addEventListener("click", openBookmarkModal);
    $("#modal-cancel").onclick = () => els.modal.classList.add("is-hidden");
    $("#modal-save").onclick = saveBookmark;
    $("#stop-btn").onclick = stopWaiting;
    $("#chat-recover")?.addEventListener("click", () => recoverChat().catch(e=>toast(e.message)));
    setupVoice();
    loadPlugins();
    $("#meme-btn")?.addEventListener("click", () => $("#meme-modal").classList.remove("is-hidden"));
    $("#meme-close")?.addEventListener("click", () => $("#meme-modal").classList.add("is-hidden"));
    $("#export-btn").onclick = exportData;
    $("#reset-btn")?.addEventListener("click", resetAll);
    $("#revoke-btn").onclick = revokeSource;
    $("#refresh-audit-btn").onclick = loadAudit;
    $("#refresh-metrics-btn").onclick = loadMetrics;
    $$("[data-more-tab]").forEach((b) => b.onclick = () => switchTab(b.dataset.moreTab));
    $("#apps-btn")?.addEventListener("click", openApps);
    $("#auth-cancel")?.addEventListener("click", closeLarkAuth);
    $("#apps-close")?.addEventListener("click", () => $("#apps-modal").classList.add("is-hidden"));
    $("#today-apps-btn")?.addEventListener("click", openApps);
    $("#today-refresh")?.addEventListener("click", loadToday);
    const historyBtn = $("#history-btn");
    if (historyBtn) historyBtn.onclick = openHistory;
    $("#history-search")?.addEventListener("input", (e) => renderHistoryList(e.target.value.trim()));
    $("#history-close") && ($("#history-close").onclick = () => $("#history-modal").classList.add("is-hidden"));
    $("#refresh-data-btn").onclick = loadData;
    $("#data-export").onclick = exportData;
    $("#data-revoke").onclick = revokeSource;
    $("#ms-save").onclick = async () => {
      try {
        const d = await api("/api/settings/model", {
          method: "POST",
          body: JSON.stringify({ base_url: $("#ms-base").value, model: $("#ms-model").value,
                                 api_key: $("#ms-key").value }),
        });
        toast(d.configured ? `已启用模型：${d.model}` : "已保存");
        $("#ms-key").value = "";
        loadEngine();
        loadData();
      } catch (e) { toast(e.message); }
    };
    $("#ms-test").onclick = async () => {
      const b = $("#ms-test");
      b.disabled = true;
      b.textContent = "测试中…";
      try {
        const r = await api("/api/settings/model/test", { method: "POST" });
        if (r.ok) toast(`连接正常 · ${r.model} · ${r.latency_ms}ms`);
        else toast(`连接失败：${r.error}`);
        $("#model-status").textContent = r.ok
          ? `连接正常：${r.model} · ${r.latency_ms}ms`
          : `连接失败：${r.error}`;
      } catch (e) { toast(e.message); }
      finally { b.disabled = false; b.textContent = "测试连接"; }
    };
    $("#ms-clear").onclick = async () => {
      try {
        await api("/api/settings/model/clear", { method: "POST" });
        toast("已清除模型配置，回到规则引擎");
        loadEngine();
        loadData();
      } catch (e) { toast(e.message); }
    };
    $("#metrics-scope").onclick = loadMetrics;
    $("#add-memory-btn").onclick = addMemoryPrompt;

    $$(".tab").forEach((t) => (t.onclick = () => switchTab(t.dataset.tab)));

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { els.modal.classList.add("is-hidden"); if (!$("#action-modal").classList.contains("is-hidden")) closeAction(); }
    });
  }

  async function addMemoryPrompt() {
    const text = await window.XinjiDialogs.prompt({title: "记下一件事", message: "先保存在待确认记忆里。你可以再改或忘掉。", maxLength: 2000, confirmLabel: "加入待确认"});
    if (!text || !text.trim()) return;
    try {
      const m = await api("/api/memory", {
        method: "POST",
        body: JSON.stringify({ session_id: state.session.id, kind: "fact", text: text.trim() }),
      });
      state.memories.push(m);
      renderAll();
      loadAudit();
      toast("已加入待确认记忆");
    } catch (e) { toast(e.message); }
  }

  function showRestoreFailure() {
    const box = document.createElement("section");
    box.className = "restore-error";
    box.setAttribute("role", "alert");
    box.innerHTML = '<h2>暂时无法恢复对话</h2><p>暂时无法读取对话记录，已有内容未被清除。请检查服务连接后重试。</p><button class="btn primary" type="button">重试</button>';
    box.querySelector("button").onclick = () => location.reload();
    document.body.appendChild(box);
  }

  async function restore() {
    try {
      const data = await api("/api/conversation");
      localStorage.setItem("xinji_session", data.session.id);
      state.session = data.session;
      if (typeof updatePersonaLabels === "function") updatePersonaLabels();
    state.followupReminder?.refresh(); state.companionBoundary?.refresh();
      state.messages = data.messages;
      state.memories = data.memories;
      state.bookmark = data.bookmark;
      state.context = data.context || null;
      globalThis.XinjiSourceDialog?.close({remember: false});
      els.onboarding.classList.add("is-hidden");
      els.app.classList.remove("is-hidden");
      els.sourceLabel.textContent = data.session.source_label || "新对话";
      els.sessionMeta.textContent = "";
      loadEngine();
      setOrb("listening");
      renderAll();
      renderInsightPanel();
      showResumeBanner();
      loadCarryover();
      loadAudit();
      switchTab("today");
      loadToday();
      loadNextStep();
      return true;
    } catch (e) {
      showRestoreFailure();
      return true;
    }
  }

  function mountPersonaPanels() {
    const mount = $("#persona-mount");
    if (!mount) return;
    const src = document.querySelector(".presence .source-panel");
    if (src) mount.appendChild(src);
  }

  function setupCompanionExperience() {
    if (!window.XinjiWelcome) return;
    $$("[data-companion-art]").forEach(element => { element.innerHTML = window.XinjiDesign?.lightMarkup || ""; });
    window.XinjiSourceDialog = window.XinjiWelcome.create({dialog: els.onboarding, backgrounds: [els.app], storageKey: null,
      fallbackFocus: () => els.input, onClose: clearCredentialForms});
  }

  function closeSourceDialog() {
    if (globalThis.XinjiSourceDialog?.isOpen()) window.XinjiSourceDialog.close({remember: false});
    else { clearCredentialForms(); els.onboarding.classList.add("is-hidden"); }
  }

  function prepareSourceDialog() {
    globalThis.XinjiVoice?.stop?.();
    $("#apps-modal")?.classList.add("is-hidden");
    clearTimeout(onboardingExitTimer);
    els.onboarding.classList.remove("leaving");
    if (window.XinjiSourceDialog) window.XinjiSourceDialog.open();
    else els.onboarding.classList.remove("is-hidden");
    $("#onboarding-return")?.classList.remove("is-hidden");
    $("#wz-2-sub").textContent = state.session
      ? "每份资料都会加入当前对话，保留刚才的消息和其他已接入来源。选此刻需要的一份就好，之后可以分别移除。"
      : "想补充一点生活的背景时，再选择一份。读取前会先一起核对范围。";
    $("#wz-skip").textContent = state.session ? "返回当前对话" : "先直接聊聊";
  }

  function showOnboarding() { openApps(); }

  async function openCompanionSource(id) {
    prepareSourceDialog();
    clearCredentialForms();
    state.realSource = null;
    wizard.pendingSource = null;
    $("#wz-read").classList.add("is-hidden");
    $("#read-items").innerHTML = "";
    $("#read-scope").innerHTML = "";
    $("#wz-3 > .section-label").textContent = id === "rokid" ? "能力说明" : "将读取（仅这些）";
    showWz(3);
    if (id === "feishu") { renderFeishuAccount(); return; }
    if (id === "local") {
      if (window.XinjiConnectionIntro.connected(state.context, "local_files")) showConnectedSource("local_files", {name:"本机资料",icon:"⌂"});
      else openLocalFiles(); return; }
    if (id === "rokid") {
      $("#read-head").innerHTML = `<h2 class="wz-title">把陪伴，延伸到眼前</h2><p class="lede">Rokid 眼镜 · 待真机联调</p>`;
      $("#read-items").innerHTML = `<div class="read-item"><b>先从轻量的文字提示开始</b><span>计划把你主动选择的一句提醒、对话摘要或陪伴提示展示在眼前；你可以随时关闭。</span></div><div class="read-item"><b>当前还没有连接设备</b><span>型号、手机系统、官方接口和真机连接仍待核对。这一页只是能力框架，不采集影像、声音或其他设备数据。</span></div>`;
      $("#read-scope").innerHTML = `<button type="button" class="btn ghost small" id="rokid-back-chat">先回到聊天</button>`;
      $("#rokid-back-chat").onclick = closeSourceDialog;
      return;
    }
    $("#read-head").innerHTML = `<h2 class="wz-title">${id === "feishu" ? "选一篇飞书资料" : "看看接下来的安排"}</h2><p class="lede">先看看可用状态，还没有读取内容。</p>`;
    const sid = state.session?.id || null;
    const request = beginCredentialRequest();
    try {
      const result = await api(id === "feishu" ? "/api/onboarding/sources?force=1" : "/api/onboarding/sources", {signal: request.controller.signal});
      if (!credentialRequestCurrent(request) || (state.session?.id || null) !== sid || els.onboarding.classList.contains("is-hidden")) return;
      const sourceId = id === "feishu" ? "feishu" : "apple_calendar";
      const meta = (result.sources || []).find((source) => source.id === sourceId);
      if (!meta) throw new Error(id === "feishu" ? "飞书入口暂不可用，可以稍后再试。" : "这台电脑的日历入口暂不可用。没有读取任何安排。");
      if (id === "feishu" && meta.status === "needs_auth") {
        startLarkAuth("document", {force: true});
        return;
      }
      await openRealSource(sourceId, meta);
    } catch (error) {
      if (credentialRequestCurrent(request)) $("#read-items").innerHTML = `<p class="note" role="status">${esc(error.message)} 可以关闭这页，继续聊天。</p>`;
    }
  }

  function setDesignPanel(open) {
    if (!open && typeof pairedDevicesPanel !== "undefined") pairedDevicesPanel?.suspend();
    const panel = $("#design-context");
    if (!panel) return;
    const isDrawer = !(window.xinjiDesktop || document.documentElement.dataset.desktop === "true") && window.innerWidth < 1200;
    panel.classList.toggle("is-open", !!open);
    $("#design-panel-backdrop")?.classList.toggle("is-open", !!open && isDrawer && window.innerWidth >= 900);
    document.documentElement.dataset.panelCollapsed = String(!open);
    if (open && state.tab === "today" && state.session) { followups.mount($("#today-followups")); typeof mood !== "undefined" && mood?.mount($("#today-mood")); }
    else { followups.stop(); typeof mood !== "undefined" && mood?.stop(); }
    $("#design-panel-toggle")?.setAttribute("aria-expanded", String(!!open));
  }

  function mountDesktopConnectionEntry() {
    const button = $('#desktop-connection-entry'), status = $('#desktop-connection-entry-status');
    if (!button || typeof window.xinjiDesktop?.openConnectionSettings !== 'function') return;
    button.classList.remove('is-hidden');
    button.onclick = async () => {
      if (button.disabled) return;
      button.disabled = true;
      try {
        // The renderer opens the trusted chooser only. It never supplies an
        // address or initiates service selection through this bridge.
        const opened = await window.xinjiDesktop.openConnectionSettings();
        status.textContent = opened ? '连接窗口已打开，请在那里核对并选择服务。' : '暂时无法打开连接窗口，可以从桌面菜单「连接与空间」重试。';
      } catch (_) { status.textContent = '暂时无法打开连接窗口，当前对话与草稿未变。'; }
      finally { button.disabled = false; }
    };
  }

  function setupDesign() {
    if (!window.XinjiDesign) return;
    mountDesktopConnectionEntry();
    if (window.xinjiDesktop || new URLSearchParams(location.search).has("desktop")) document.documentElement.dataset.desktop = "true";
    window.xinjiDesktop?.info?.().then(info => { document.documentElement.dataset.nativePlatform = info.platform; }).catch(() => {});
    if (/Android/i.test(navigator.userAgent)) document.documentElement.dataset.platform = "android";
    window.XinjiWorkspace = window.XinjiDesign.createWorkspace({getState: () => state, backgrounds: [els.app], fallbackFocus: () => els.input,
      onJump: item => {
        if (item.type === "memory") switchTab("memory");
        else { if (window.innerWidth < 900) setDesignPanel(false); }
        const root = item.type === "memory" ? els.memoryList : els.messages;
        const match = [...root.querySelectorAll(item.type === "memory" ? "[data-id]" : "[data-message-id]")].find(element => (element.dataset.id || element.dataset.messageId) === item.id);
        if (match) { match.setAttribute("tabindex", "-1"); match.focus({preventScroll: true}); match.scrollIntoView({block: "center", behavior: "auto"}); }
      }});
    window.XinjiWorkspace.mountTopics($("#design-topics"));
    // 宽屏把「按你的节奏…」这句以浅色放在首条消息上方；原文仍留在工具栏作读屏状态。
    const boundaryHost = $(".conversation-toolbar [data-companion-boundary]");
    if (boundaryHost && typeof MutationObserver !== "undefined") {
      const syncBoundaryNote = () => els.messages.style.setProperty("--boundary-note", JSON.stringify(boundaryHost.querySelector(".companion-boundary-copy")?.textContent?.trim() || ""));
      new MutationObserver(syncBoundaryNote).observe(boundaryHost, {subtree: true, childList: true, characterData: true});
      syncBoundaryNote();
    }
    document.addEventListener("xinji-topic-change", () => window.XinjiWorkspace.filterMessages(els.messages));
    window.XinjiDesign.mountSettings($("#design-settings"));
    $("#design-search-btn").onclick = () => { globalThis.XinjiVoice?.stop?.(); window.XinjiWorkspace.openSearch(); };
    $("#design-settings-btn").onclick = () => switchTab("design");
    $("#design-panel-toggle").onclick = () => setDesignPanel(document.documentElement.dataset.panelCollapsed === "true" || !$("#design-context").classList.contains("is-open"));
    for (const selector of ["#design-panel-backdrop", "#design-context-close"]) $(selector).onclick = () => { setDesignPanel(false); $("#design-panel-toggle").focus(); };
    document.addEventListener("keydown", event => { if (event.key === "Escape" && window.innerWidth < 1200 && !window.xinjiDesktop) setDesignPanel(false); });
    $$("[data-design-nav]").forEach(button => button.onclick = () => {
      $$("[data-design-nav]").forEach(item => item.classList.toggle("active", item.dataset.designNav === button.dataset.designNav));
      if (button.dataset.designNav === "chat") { if (window.innerWidth < 1200) setDesignPanel(false); els.input.focus(); }
      else switchTab(button.dataset.designNav);
    });
    $$("[data-design-route]").forEach(button => button.onclick = () => switchTab(button.dataset.designRoute));
    els.input.addEventListener("input", () => { document.documentElement.dataset.presenceState = els.input.value ? "input" : "quiet"; });
    window.xinjiDesktop?.onCommand?.(command => {
      if (command.action === "chat") { setDesignPanel(false); els.input.focus(); }
      else if (command.action === "draft") { els.input.value = [els.input.value, command.text || ""].filter(Boolean).join("\n"); els.input.focus(); }
      else if (command.action === "new-memory") addMemoryPrompt();
      else if (command.action === "quiet") { window.XinjiCompanionBoundary?.invalidate(); setOrb(command.pausedUntil && Date.parse(command.pausedUntil) > Date.now() ? "quiet" : "listening"); }
      else if ({today:1,memory:1,apps:1,settings:1,tasks:1}[command.action]) switchTab({settings:"design",tasks:"bookmark"}[command.action] || command.action);
    });
    const alignHeader = () => document.documentElement.style.setProperty("--design-header-bottom", `${$(".topbar").getBoundingClientRect().bottom + 12}px`);
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(alignHeader).observe($(".topbar"));
    setDesignPanel(window.xinjiDesktop || window.innerWidth >= 1200);
  }

  async function boot() {
    bind();
    mountPersonaPanels();
    setupCompanionExperience();
    setupDesign();
    window.XinjiComposerDraft = window.XinjiForegroundSync.draft(els.input, "web");
    await restore();
    if (!state.session) return;
    restoreChatLedger();
    connectionIntro.resume();
    els.input.addEventListener('input', keepChatDraft);
    window.addEventListener('pagehide', () => { keepChatDraft(); connectionIntro.stop(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden) keepChatDraft(); });
    setDesignPanel(window.xinjiDesktop || document.documentElement.dataset.desktop === "true" || window.innerWidth >= 1200);
    if (new URLSearchParams(location.search).has("onboarding")) openApps();
    else els.input?.focus();
    const canRefresh = () => !!state.session && !document.hidden && !activeTurn && !state.delivery?.pending() && !turnQueue.length && !queuedTurns.length && !chatBlocked && !contentMutationCount && !state.attachingSource && !state.revokingSource && !state.confirmingSource && !state.memorySaving && !memoryDrafts.size && followups.canRefresh() && mood?.canRefresh() !== false && state.companionBoundary?.canRefresh() !== false && !document.querySelector('dialog[open], [aria-modal="true"]:not(.is-hidden), .mem-edit') && !document.activeElement?.matches('input:not(#input),textarea:not(#input),select,[contenteditable="true"]');
    const legacyRefresh = window.XinjiForegroundSync.create({canRefresh, version:() => `${state.session?.id}:${sourceUiEpoch}:${contentMutationEpoch}`, read: () => api('/api/conversation'), apply: data => {
      if (data.session?.id !== state.session?.id) return;
      state.messages = data.messages; state.memories = data.memories; state.bookmark = data.bookmark; state.context = data.context || null; state.session = data.session;
      if (typeof updatePersonaLabels === "function") updatePersonaLabels(); renderMessages(); renderUnderstanding(); renderMemoryList(); renderConnectedSources(); renderStarterBar(); if (typeof loadPersonaPicker === "function") loadPersonaPicker();
      if (state.tab === 'today') loadToday();
    }});
    let updates;
    const showUpdate = window.XinjiContentUpdates.mountStatus(document.querySelector('[data-content-update]'), () => updates?.state().supported === false ? legacyRefresh() : updates?.check());
    updates = window.XinjiContentUpdates.create({api, identity:() => state.session?.id,
      revision:() => `${sourceUiEpoch}:${contentMutationEpoch}:${state.tab}`, canApply:canRefresh,
      read:(_changes,get) => window.XinjiContentUpdates.snapshot(state.session.id,get,{today:true}),
      apply:snapshot => {
        const data=snapshot.conversation;
        if (data.session?.id!==state.session?.id || !canRefresh()) return false;
        sourceUiEpoch++;
        state.delivery?.invalidateReads();
        state.nextStep=snapshot.next;
        state.session=data.session; state.messages=data.messages; state.memories=data.memories; state.bookmark=data.bookmark; state.context=data.context||null;
        renderMessages(); renderUnderstanding(); renderMemoryList(); renderConnectedSources(); renderStarterBar(); renderBookmark(); renderNextStep();
        if(state.tab==='bookmark')void loadTaskActions(snapshot.actions);
        if(state.tab==='data')renderDataSummary(data,snapshot.actions);
        followups.acceptSnapshot(snapshot.followups); mood?.acceptSnapshot(snapshot.moods); state.companionBoundary?.acceptSnapshot(snapshot.boundary);
        if(state.tab==='today')void loadToday(snapshot);
        return true;
      }, onState:showUpdate});
    updates.start();
    window.addEventListener('focus',()=>updates.visibilityChanged());
    document.addEventListener('visibilitychange',()=>updates.visibilityChanged());
    window.addEventListener('pagehide',()=>updates.stop());
    window.addEventListener('pageshow',event=>{if(event.persisted)updates.start();});
  }

  boot();
})();
