/* 念响 · 移动端 H5（复用同一 API） */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s = "") => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  document.addEventListener("xinji-space-sync-error", (event) => {
    const text = event.detail?.error?.message || "当前人格未能同步，请检查服务连接后重试。";
    const toast = $("#m-toast");
    if (toast) { toast.textContent = text; toast.classList.remove("is-hidden"); setTimeout(() => toast.classList.add("is-hidden"), 2600); }
  });
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

  const state = { session: null, messages: [], memories: [], bookmark: null, nextStep: null, context: null, deviceOn: false, timer: null, lastDisplay: null };
  let personaOptions = [];
  let personaRequest = 0;
  function personaName(id) { return personaOptions.find(item => item.id === id)?.name || (id === "whale" ? "小鲸鱼" : "念响"); }
  function updatePersonaLabels() {
    const id = state.session?.persona_id || "nianxiang";
    const label = $("#m-persona-name");
    if (label) label.textContent = personaName(id);
    document.title = `${personaName(id)} · 移动端`;
  }
  async function loadMobilePersonas(host, sid, epoch) {
    const request = ++personaRequest, sheet = $("#m-sheet");
    const data = await api("/api/personas");
    if (request !== personaRequest || state.session?.id !== sid || sheet._xinjiEpoch !== epoch) return;
    personaOptions = (data.personas || []).filter(item => ["nianxiang", "whale"].includes(item.id));
    const selected = state.session.persona_id || data.default_persona || "nianxiang";
    host.insertAdjacentHTML("afterbegin", `<div class="m-today-card"><div class="k">当前伙伴</div><p>可以随时切换，聊天、记忆和语气偏好都会保留。</p><div class="persona-options" role="radiogroup" aria-label="选择聊天伙伴">${personaOptions.map(item => `<button type="button" class="persona-option ${item.id === selected ? "is-selected" : ""}" data-m-persona-id="${esc(item.id)}" role="radio" aria-checked="${item.id === selected}"><span><b>${esc(item.name)}</b><small>${esc(item.description || "")}</small><em>${(item.tags || []).map(tag => esc(tag)).join(" · ")}</em></span><span class="persona-check" aria-hidden="true">${item.id === selected ? "✓" : ""}</span></button>`).join("")}</div></div>`);
    host.querySelectorAll("[data-m-persona-id]").forEach(button => button.onclick = async () => {
      const next = button.dataset.mPersonaId;
      if (!next || next === (state.session?.persona_id || "nianxiang") || button.disabled) return;
      button.disabled = true;
      try {
        const result = await api(`/api/session/${encodeURIComponent(sid)}/persona`, {method: "PUT", body: JSON.stringify({persona_id: next})});
        if (state.session?.id !== sid) return;
        state.session = result.session || result;
        if (typeof updatePersonaLabels === "function") updatePersonaLabels();
        await renderPersonaMobile();
        toast(`已切换为${personaName(next)}`);
      } catch (error) { button.disabled = false; toast(error.message || "切换伙伴失败"); }
    });
  }

  let mobileOpeningEntry = 0, mobileRokidReturn = null;
  let mobileWizard = null, mobileWizardMode = "user", mobileWizardResume = null;
  let mobileAuthSurface = null, mobileAuthClosing = false;

  function getMobileWizard() {
    if (mobileWizard || !window.XinjiWelcome?.create) return mobileWizard;
    mobileWizard = window.XinjiWelcome.create({
      dialog: $("#m-onboard"), backgrounds: [$("#m-app"), $("#m-sheet")], storageKey: null,
      fallbackFocus: () => $("#m-input"), onClose: () => {
        if (mobileWizardMode !== "suspend") { clearMobileSourceForm(); mobileOpeningEntry++; }
      },
    });
    return mobileWizard;
  }

  function openMobileWizard() {
    globalThis.XinjiVoice?.stop?.();
    const wizard = getMobileWizard();
    if (wizard) wizard.open(); else $("#m-onboard").classList.remove("is-hidden");
  }

  function closeMobileWizard({suspend = false} = {}) {
    mobileWizardMode = suspend ? "suspend" : "user";
    if (mobileWizard?.isOpen?.()) mobileWizard.close({remember: false});
    else { $("#m-onboard").classList.add("is-hidden"); if (!suspend) { clearMobileSourceForm(); mobileOpeningEntry++; } }
    mobileWizardMode = "user";
  }

  function focusMobileWizardStep(step) {
    if (!mobileWizard?.isOpen?.()) return;
    const dialog = $("#m-onboard"), active = document.activeElement;
    if (active && dialog.contains(active) && !active.closest(".is-hidden, [inert]")) return;
    const target = $(`#m-wz-${step}`)?.querySelector('button:not([disabled]), input:not([disabled]), textarea:not([disabled])');
    (target || dialog).focus();
  }

  function getMobileAuthSurface() {
    if (mobileAuthSurface || !window.XinjiWelcome?.create) return mobileAuthSurface;
    mobileAuthSurface = window.XinjiWelcome.create({dialog: $("#m-auth"), storageKey: null,
      backgrounds: [$("#m-app"), $("#m-onboard"), $("#m-sheet")], fallbackFocus: () => $("#m-input"),
      onClose: () => { if (!mobileAuthClosing) closeLarkAuthMobile(); },
    });
    return mobileAuthSurface;
  }

  function beginMobileAuthSurface() {
    if (mobileWizard?.isOpen?.()) {
      mobileWizardResume = {sessionId: state.session?.id || null, epoch: mobileSourceFormEpoch};
      closeMobileWizard({suspend: true});
    }
    getMobileAuthSurface()?.open();
  }

  function finishMobileAuthSurface({resume = true, documentReady = false, accountReady = false} = {}) {
    const origin = mobileWizardResume;
    mobileWizardResume = null;
    mobileAuthClosing = true;
    mobileAuthSurface?.close?.({remember: false});
    mobileAuthClosing = false;
    if (resume && origin && (state.session?.id || null) === origin.sessionId && mobileSourceFormEpoch === origin.epoch) {
      openMobileWizard();
      if (accountReady) openMobileFeishuAccount();
      else if (documentReady) openMobileFeishu();
      return true;
    }
    return false;
  }

  function mountMobileCompanions() {
    if (!window.XinjiDesign?.lightMarkup) return;
    $$("[data-design-light]").forEach(scene => { scene.innerHTML = window.XinjiDesign.lightMarkup; });
  }

  function openMobileRokid(opener = document.activeElement) {
    const dialog = $("#m-rokid-outline");
    if (!dialog || typeof dialog.showModal !== "function") { toast("Rokid 仍待联调；当前可以先聊聊和保存你选择的提醒。"); return; }
    mobileRokidReturn = opener;
    if (!dialog.open) dialog.showModal();
  }

  function closeMobileRokid() {
    const dialog = $("#m-rokid-outline");
    if (dialog?.open) dialog.close();
    const previous = mobileRokidReturn;
    mobileRokidReturn = null;
    const visible = previous?.isConnected && !previous.closest?.(".is-hidden, [inert]");
    (visible ? previous : $("#m-input"))?.focus();
  }

  async function openMobileEntry(id, opener) {
    if (id === "rokid") { clearMobileSourceForm(); mobileOpeningEntry++; closeMobileWizard(); openMobileRokid(opener); return; }
    if (state.attachingSource || state.revokingSource) { toast("这份资料还在更新，稍等一下就好。"); return; }
    const request = ++mobileOpeningEntry, sessionId = state.session?.id || null;
    clearMobileSourceForm();
    const epoch = mobileSourceFormEpoch;
    wz.directEntry = true;
    openMobileWizard();
    if (id !== "feishu" && window.XinjiConnectionIntro.connected(state.context, id)) { showConnectedMobileSource(id, {name:({local_files:"本机资料",apple_calendar:"日历"})[id] || id}); return; }
    if (id === "local_files") { openMobileLocalFiles(); return; }
    if (id === "waytoagi" || id === "jike") { openMobilePublicSource(id); return; }
    if (id === "apple_calendar") {
      openMobileReal("apple_calendar", "needs_click", {name: "日历", blurb: "看看过去 7 天的安排，只读日程", reads: ["过去 7 天日程"]});
      return;
    }
    if (id === "feishu") openMobileFeishuAccount();
  }

  let contentMutationEpoch = 0, contentMutationCount = 0;
  const api = async (path, opts = {}) => {
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
  };

  function toast(msg) {
    const el = $("#m-toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("show"), 2400);
  }

  const followups = window.XinjiFollowups.create({api, surface:"h5", getSessionId: () => state.session?.id});
  const mood = window.XinjiMood?.create({api, surface:"h5", getSessionId: () => state.session?.id, onContext:putMobileMoodIntoChat});
  function putMobileMoodIntoChat(text) {
    if (typeof text !== "string" || !text || !state.session) return;
    const input = $("#m-input");
    if (!input.value.includes(text)) input.value = input.value.trim() ? input.value + "\n\n" + text : text;
    window.XinjiComposerDraft?.save(); keepMobileChatDraft(); closeSheet(); input.focus(); toast("已放到输入框，由你决定是否发送。");
  }
  state.followupReminder = window.XinjiFollowups.startReminder({api, getSessionId: () => state.session?.id});
  state.companionBoundary = window.XinjiCompanionBoundary?.create({api, getSessionId: () => state.session?.id, host:document.querySelector("[data-companion-boundary]")});
  void window.XinjiVoice.configure({api});

  const connectionIntro = window.XinjiConnectionIntro.create({api, host: $("#m-connection-intro"),
    getSessionId: () => state.session?.id,
    canApply: () => !mActiveTurn && !state.delivery?.pending() && !mQueuedTurns.length && !mTurnQueue.length && !contentMutationCount && !state.attachingSource && !state.revokingSource && !state.confirmingSource,
    revision: () => `${state.session?.id}:${contentMutationEpoch}:${state.sourceGeneration}:${state.messages.length}`,
    apply: data => {
      state.session = data.session; state.messages = data.messages; state.memories = data.memories;
      state.context = data.context || null; state.bookmark = data.bookmark || null;
      renderMessages(); window.XinjiConnectionIntro.syncBadges(document, state.context);
    }});
  function finishConnection(data) {
    closeMobileWizard(); closeSheet(); window.XinjiConnectionIntro.syncBadges(document, state.context);
    connectionIntro.start(data?.intro); $("#m-input")?.focus();
  }
  async function beginConnectionIntro(sourceId) {
    const sid = state.session?.id;
    if (!sid) return;
    const data = await api('/api/connections/intro', {method:'POST', body:JSON.stringify({session_id:sid,source_id:sourceId})});
    if (state.session?.id !== sid) return;
    closeMobileWizard(); closeSheet(); connectionIntro.start(data.intro || data); $("#m-input")?.focus();
  }
  function showConnectedMobileSource(id, meta) {
    $("#m-read-btn").classList.add('is-hidden'); $("#m-read-items").innerHTML = ''; $("#m-read-scope").innerHTML = '';
    $("#m-read-head").innerHTML = `<div class="connection-card"><div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">${esc(meta?.icon || '✓')}</span><h3>${esc(meta?.name || '已连接')}</h3></div><p class="connection-value">✓ 已连接，可以接着聊了。</p><p class="connection-scope">需要时会参考已接入的内容。你可以在资料管理里移除。</p><button type="button" class="btn primary" id="m-connection-return">回到聊天</button><button type="button" class="text-btn" id="m-connection-manage">管理资料</button></div>`;
    $("#m-connection-return").onclick = () => { closeMobileWizard(); closeSheet(); };
    $("#m-connection-manage").onclick = () => { closeMobileWizard(); openSheet('more'); };
    showWz(3);
  }

  // ---------- onboarding ----------
  function enterSessionData(d) {
    if (typeof pairedDevicesPanel !== "undefined") pairedDevicesPanel?.suspend();
    const previous = state.session?.id;
    if (previous && previous !== d.session.id) {
      followups.stop();
      state.mobileDrafts = state.mobileDrafts || {};
      state.mobileDrafts[previous] = $("#m-input")?.value || "";
      const input = $("#m-input");
      if (input) input.value = state.mobileDrafts[d.session.id] || "";
    }
    clearMobileSourceForm();
    state.sourceGeneration = (state.sourceGeneration || 0) + 1;
    state.session = d.session;
    if (typeof updatePersonaLabels === "function") updatePersonaLabels();
    state.followupReminder?.refresh(); state.companionBoundary?.refresh();
    $("#m-chat-error")?.classList.add("is-hidden");
    state.messages = d.messages;
    state.memories = d.memories;
    state.bookmark = d.bookmark || null;
    state.context = d.context || null;
    if (previous !== d.session.id) state.sourceReviewNotice = "";
    if ((state.memories || []).some(memory => memory.status === "candidate" && (memory.source || "").includes("撤回后来源待核对"))) {
      state.sourceReviewNotice = "有来源待核对的记忆仍保留为候选，暂不用于模型回复。可在记忆中逐条核对、确认或删除。";
    }
    if (state.sourceReviewNotice) {
      $("#m-chat-error").textContent = state.sourceReviewNotice;
      $("#m-chat-error").classList.remove("is-hidden");
    }
    localStorage.setItem("xinji_session", state.session.id);
    if (typeof closeLarkAuthMobile === "function") closeLarkAuthMobile(false);
    if (typeof closeSheet === "function") closeSheet();
    if (typeof closeMobileWizard === "function") closeMobileWizard();
    else $("#m-onboard").classList.add("is-hidden");
    $("#m-app").classList.remove("is-hidden");
    renderAll();
    loadEngine();
    loadNextStep();
    renderStarters();
    window.XinjiConnectionIntro.syncBadges(document, state.context);
    connectionIntro.start(d.intro);
    $("#m-input")?.focus();
  }

  async function startSession() {
    // Resume the server's canonical conversation; this client never creates a replacement conversation.
    return restore();
  }

  // ---------- onboarding wizard (mobile) ----------
  const wz = { connector: null, read: null };
  const mobilePendingPrefix = "xinji_h5_source_pending_";

  function mobilePendingKeys() {
    try {
      const keys = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key?.startsWith(mobilePendingPrefix)) keys.push(key);
      }
      return keys;
    } catch (_) { return []; }
  }

  function renderMobilePendingNotice() {
    $("#m-source-uncertain-notice")?.classList.toggle("is-hidden", mobilePendingKeys().length === 0);
  }

  function markMobileSourceStart() {
    const key = mobilePendingPrefix + `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    try {
      localStorage.setItem(key, "1");
      if (localStorage.getItem(key) !== "1") return null;
    } catch (_) { return null; }
    renderMobilePendingNotice();
    return key;
  }

  function finishMobileSourceStart(key) {
    try { localStorage.removeItem(key); } catch (_) {}
    renderMobilePendingNotice();
  }

  function dismissMobilePendingNotice() {
    try { for (const key of mobilePendingKeys()) localStorage.removeItem(key); } catch (_) {}
    renderMobilePendingNotice();
  }
  let mobileSourceFormEpoch = 0;

  function clearMobileSourceForm() {
    mobileSourceFormEpoch++;
    for (const id of ["#m-gmail-password", "#m-notion-token"]) {
      const input = $(id);
      if (input) input.value = "";
    }
  }

  function showWz(n) {
    $("#m-onboard").classList.toggle("connection-compact", n === 3);
    if (n !== 3) clearMobileSourceForm();
    $("#m-onboarding-return")?.classList.toggle("is-hidden", !state.session);
    [1, 2, 3, 4].forEach((i) => $(`#m-wz-${i}`)?.classList.toggle("is-hidden", i !== n));
    $("#m-paste-box")?.classList.add("is-hidden");
    $(".onboard-top")?.classList.toggle("is-hidden", n > 1);
    if (typeof focusMobileWizardStep === "function") focusMobileWizardStep(n);
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

  async function loadRealSources() {
    const request = ++mobileOpeningEntry, epoch = mobileSourceFormEpoch, sid = state.session?.id || null;
    const box = $("#m-reco");
    const current = () => request === mobileOpeningEntry && epoch === mobileSourceFormEpoch && (state.session?.id || null) === sid && !$("#m-wz-2").classList.contains("is-hidden");
    box.innerHTML = `<p class="synthetic">正在检查可用的连接…</p>`;
    try {
      const [d] = await Promise.all([api("/api/onboarding/sources?force=1"), readFeishuAccountState()]);
      if (!current()) return;
      const labels = { ready: "可读取", needs_click: "读取前确认权限", needs_config: "需填写配置", needs_auth: "需授权", needs_install: "需安装", unavailable: "暂不可用", empty: "暂无内容" };
      box.innerHTML = (d.sources || []).map((source) => `<div class="m-connector">
        <div class="ico">${esc(source.icon)}</div><div class="bd"><b>${esc(source.name)}</b>
        <small>${esc(source.id === "apple_calendar" ? "过去 7 天的日程" : source.id === "apple_reminders" ? "最近 7 天有更新的提醒" : source.blurb)} · <span ${source.id === "feishu" ? "data-feishu-account-status" : `data-connection-source="${esc(source.id)}" data-connection-idle="${esc(labels[source.status] || "待检查")}"`}>${esc(source.id === "feishu" ? window.XinjiFeishuAccountPicker.statusLabel(state.feishuAccount) : window.XinjiConnectionIntro.connected(state.context,source.id) ? "✓ 已连接" : labels[source.status] || "待检查")}</span></small></div>
        <button type="button" class="go" data-real="${esc(source.id)}" ${source.id === "feishu" ? "data-feishu-account-control" : `data-connection-control="${esc(source.id)}" data-connection-idle="连接"`}>${source.id === "feishu" ? state.feishuAccount?.enabled ? "管理连接" : "连接" : window.XinjiConnectionIntro.connected(state.context,source.id) ? "管理" : source.id === "git" ? "选目录" : ["ready", "needs_click"].includes(source.status) ? "连接" : "查看"}</button>
      </div>`).join("") || `<p class="synthetic">暂时没有可用来源，可以先返回聊天。</p>`;
      box.querySelectorAll("[data-real]").forEach(button => {
        button.onclick = () => { if (current()) { const source = d.sources.find(item => item.id === button.dataset.real); if (source) openMobileReal(source.id, source.status, source); } };
      });
    } catch (error) {
      if (!current()) return;
      box.innerHTML = `<p class="synthetic">${esc(error.message)}</p><button type="button" class="btn ghost wide" id="m-source-retry">重新检查连接</button>`;
      $("#m-source-retry").onclick = () => { if (current()) loadRealSources(); };
    }
  }

  async function openMobileReal(id, status, meta) {
    clearMobileSourceForm();
    if (id !== "feishu" && window.XinjiConnectionIntro.connected(state.context, id)) { showConnectedMobileSource(id, meta); return; }
    if (id === "local_files") { openMobileLocalFiles(); return; }
    if (id === "waytoagi" || id === "jike") { openMobilePublicSource(id); return; }
    if (id === "git") { openMobileGit(); return; }
    if (id === "gmail" || id === "notion") { openMobileCredentialSource(id); return; }
    if (id === "feishu") { openMobileFeishuAccount(); return; }
    if (id === "github" && status !== "ready") {
      const sid = state.session?.id || null, epoch = mobileSourceFormEpoch;
      showWz(3);
      $("#m-wz3-title").textContent = "连接 GitHub";
      $("#m-read-btn").classList.add("is-hidden");
      $("#m-read-items").innerHTML = "";
      $("#m-read-scope").innerHTML = "";
      $("#m-read-head").innerHTML = `<p class="lede">${esc(meta?.hint || "先确认本机 GitHub CLI 的登录状态。")}</p><p class="note">这里只读取你创建的最近 PR；检查连接不会读取 PR，也不会自动授权或扩大权限。</p><button type="button" class="btn ghost wide" id="m-github-recheck">我已处理，重新检查</button><p class="note" id="m-github-status" role="status"></p>`;
      const button = $("#m-github-recheck"), hint = $("#m-github-status");
      button.onclick = async () => {
        if (button.disabled || epoch !== mobileSourceFormEpoch || (state.session?.id || null) !== sid) return;
        button.disabled = true;
        try {
          const data = await api("/api/onboarding/sources?force=1");
          if (epoch !== mobileSourceFormEpoch || (state.session?.id || null) !== sid) return;
          const source = data.sources?.find(item => item.id === "github");
          if (source?.status === "ready") openMobileReal(source.id, source.status, source);
          else hint.textContent = source?.hint || "仍未确认连接，可先返回聊天。";
        } catch (error) { if (epoch === mobileSourceFormEpoch && (state.session?.id || null) === sid) hint.textContent = error.message; }
        finally { button.disabled = false; }
      };
      return;
    }
    if (status === "needs_auth" || status === "needs_config" || status === "needs_install" || status === "empty") {
      toast(meta?.hint || "先完成授权/配置"); return;
    }
    wz.realSource = null;
    wz.pendingSource = id;
    $("#m-wz3-title").textContent = `连接${meta?.name || "来源"}`;
    const scope = id === 'apple_calendar' ? '只读过去 7 天的日程，相关片段会发送给当前模型。'
      : id === 'apple_reminders' ? '只读最近 7 天相关提醒；可用时间范围以实际读取结果为准，相关片段会发送给当前模型。'
      : '只读当前来源支持的内容，相关片段会发送给当前模型。';
    $("#m-read-head").innerHTML = `<div class="connection-card"><div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">${esc(meta?.icon || '▦')}</span><h3>连接${esc(meta?.name || id)}</h3></div><p class="connection-value">陪你看看最近发生的事，找到此刻值得聊的一件。</p><p class="connection-scope">${esc(scope)}</p></div>`;
    $("#m-read-items").innerHTML = '';
    $("#m-read-scope").innerHTML = '';
    $("#m-read-btn").classList.remove("is-hidden");
    $("#m-read-btn").textContent = "授权";
    $("#m-read-btn").disabled = false;
    showWz(3);
  }

  function openMobileGit() {
    clearMobileSourceForm();
    const initialSession = state.session?.id || null;
    wz.realSource = null;
    wz.pendingSource = null;
    showWz(3);
    $("#m-wz3-title").textContent = "选择本机代码库";
    $("#m-read-btn").classList.add("is-hidden");
    $("#m-read-items").innerHTML = "";
    $("#m-read-scope").innerHTML = "";
    $("#m-read-head").innerHTML = `<div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">git</span><h3>连接代码库</h3></div><p class="connection-value">看看最近的进展，陪你理一理下一步。</p><p class="connection-scope">只读所选代码库最近最多 8 条提交；相关片段会发送给当前模型。</p>
      <div class="mobile-source-form"><label>代码库目录<input id="m-git-path" type="text" autocomplete="off" spellcheck="false" placeholder="例如 C:\\Users\\你的用户名\\Projects\\my-project 或 ~/Projects/my-project"></label>
      <button class="btn primary wide" id="m-git-preview">授权</button><p class="synthetic" id="m-git-hint" role="status">支持 ~/Projects/my-project；填写目录路径即可，不要输入终端命令。</p></div>`;
    const input = $("#m-git-path"), button = $("#m-git-preview"), hint = $("#m-git-hint");
    input.oninput = () => { clearMobileSourceForm(); $("#m-read-items").innerHTML = ""; hint.textContent = "目录已更改，请重新读取。"; button.disabled = false; };
    button.onclick = async () => {
      const path = input.value.trim();
      if (!path) { hint.textContent = "请先填写代码库的完整目录。"; return; }
      if (button.disabled) return;
      const epoch = mobileSourceFormEpoch;
      button.disabled = true;
      $("#m-read-items").innerHTML = "";
      hint.textContent = "正在读取所选代码库…";
      try {
        const result = await api("/api/onboarding/real/read", {method: "POST", body: JSON.stringify({source_id: "git", path, start_intro:true})});
        if (epoch !== mobileSourceFormEpoch || input.value.trim() !== path || (state.session?.id || null) !== initialSession) return;
        if (!result.ok || !result.preview_id || !Array.isArray(result.items)) {
          hint.textContent = [result.error || "读取失败", result.hint].filter(Boolean).join(" · "); return;
        }
        $("#m-read-items").classList.add("connection-auto-snapshot");
        $("#m-read-items").innerHTML = `<p class="synthetic">实际代码库：${esc(result.selected_path || path)} · ${result.items.length} 条提交</p>` + result.items.map(item =>
          `<div class="m-read-item"><b>${esc(item.title)}</b><span>${esc(item.meta)} · ${esc(item.summary)}</span></div>`).join("") +
          `<button class="btn primary wide" id="m-git-use">核对这些提交并继续</button>`;
        hint.textContent = "请核对快照，也可以修改目录后重新读取。预览 10 分钟内有效。";
        $("#m-git-use").onclick = () => {
          if (epoch !== mobileSourceFormEpoch || input.value.trim() !== path || (state.session?.id || null) !== initialSession) return;
          wz.realSource = {id: "git", read: result, sessionId: initialSession};
          wz.read = result;
          wz.connector = result.connector;
          return startMobileReal();
        };
        await $("#m-git-use").onclick();
      } catch (error) { if (epoch === mobileSourceFormEpoch) hint.textContent = `读取失败：${error.message}；可修改目录后重试。`; }
      finally { if (epoch === mobileSourceFormEpoch) button.disabled = false; }
    };
  }

  function openMobileCredentialSource(id) {
    clearMobileSourceForm();
    const gmail = id === "gmail";
    const initialSession = state.session?.id || null;
    showWz(3);
    $("#m-wz3-title").textContent = gmail ? "只读 Gmail 未读邮件" : "只读 Notion 页面或数据库";
    $("#m-read-btn").classList.add("is-hidden");
    $("#m-read-scope").innerHTML = "";
    $("#m-read-items").innerHTML = "";
    $("#m-read-head").innerHTML = gmail ? `<div class="connection-card"><div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">M</span><h3>连接 Gmail</h3></div>
      <p class="connection-value">看看最近的未读消息，一起理清在意的事。</p><p class="connection-scope">只读最近 5 封未读邮件的主题、发件人和日期，必要内容会发送给当前模型。密码仅本次使用。</p>
      <div class="mobile-source-form"><label>Gmail 地址<input id="m-gmail-address" type="email" autocomplete="off"></label><label>应用专用密码<input id="m-gmail-password" type="password" autocomplete="off" placeholder="不是 Google 登录密码"></label>
      <button class="btn primary wide" id="m-source-preview">授权</button><p class="connection-status" id="m-source-hint" role="status"></p></div></div>` : `<div class="connection-card"><div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">N</span><h3>连接 Notion</h3></div>
      <p class="connection-value">带上一页想法，从你正在做的事聊起。</p><p class="connection-scope">只读所选页面前 50 个文本块或数据库前 20 条，相关内容会发送给当前模型。Token 仅本次使用。</p>
      <div class="mobile-source-form"><label>连接方式<select id="m-notion-method"><option value="token">集成 Token</option><option value="cli">本机已登录的 Notion CLI</option></select></label><label>集成 Token<input id="m-notion-token" type="password" autocomplete="off"></label><label>页面或数据库链接<input id="m-notion-url" type="url" autocomplete="off" placeholder="Notion 链接"></label>
      <button class="btn primary wide" id="m-source-preview">授权</button><p class="connection-status" id="m-source-hint" role="status"></p></div><details><summary>连接帮助</summary><a href="https://developers.notion.com/cli/get-started/authentication" target="_blank" rel="noopener noreferrer">Notion 官方 CLI 连接说明</a></details></div>`;
    if (!gmail) $("#m-notion-method").onchange = () => { clearMobileSourceForm(); $("#m-source-preview").disabled = false; $("#m-source-hint").textContent = $("#m-notion-method").value === "cli" ? "使用本机 ntn 已有登录；填写单页链接，只读前 50 个顶层文本块。" : "填写集成 Token 和页面或数据库链接。"; $("#m-notion-token").value = ""; $("#m-notion-token").disabled = $("#m-notion-method").value === "cli"; $("#m-read-items").innerHTML = ""; };
    $("#m-source-preview").onclick = async () => {
      const button = $("#m-source-preview"), hint = $("#m-source-hint"), items = $("#m-read-items");
      if (button.disabled) return;
      const secret = $(gmail ? "#m-gmail-password" : "#m-notion-token");
      const body = gmail ? {address: $("#m-gmail-address").value.trim(), password: secret.value.trim()}
        : {url: $("#m-notion-url").value.trim(), token: secret.value.trim(), method: $("#m-notion-method").value || "token"};
      if (!(gmail ? body.address && body.password : body.url && (body.method === "cli" || body.token))) { hint.textContent = "请填写两个输入项。"; return; }
      const epoch = mobileSourceFormEpoch;
      secret.value = "";
      button.disabled = true;
      items.innerHTML = "";
      hint.textContent = "正在读取…";
      try {
        const d = await api(`/api/${id}/preview`, {method:"POST", body:JSON.stringify(body)});
        if (epoch !== mobileSourceFormEpoch) return;
        if (!d.ok || !d.preview_id || !Array.isArray(d.items)) {
          hint.textContent = [d.error || "读取失败", d.hint].filter(Boolean).join(" · "); return;
        }
        const facts = (d.understanding?.facts || []).slice(0, 4);
        items.innerHTML = `<p class="lede">${esc(d.title)} · ${d.items.length} 条快照</p>` + d.items.map((item, i) =>
          `<div class="m-read-item"><b>${esc(item.title)}</b><span>${esc(item.meta)} · ${esc(item.summary)}</span>${i < 8 ? '<span>生成理解时可能发送给模型</span>' : ''}</div>`).join("") +
          `<p class="synthetic">生成理解时可能一并发送的提取事实：</p>` + facts.map(f => `<div class="m-read-item">${esc(f)}</div>`).join("") +
          `<p class="synthetic">${initialSession ? "确认后接入当前对话，保留刚才的消息。" : "确认后开始新对话。"}接入后若已配置模型服务，可能向模型发送必要的标题、元信息、摘要和列出的提取事实，用于初步理解或后续对话。预览仅能使用一次，10 分钟内有效。</p><button class="btn primary wide" id="m-source-start">${initialSession ? "接入当前对话" : "确认并开始"}</button>`;
        hint.textContent = "请核对以上快照。";
        $("#m-source-start").onclick = async () => {
          const start = $("#m-source-start");
          if (start.disabled) return;
          if ((state.session?.id || null) !== initialSession || state.attachingSource || state.revokingSource || state.confirmingSource || mActiveTurn || mQueuedTurns.length || mTurnQueue.length) {
            hint.textContent = "对话已切换或消息仍在发送，请返回对话后重新预览。"; return;
          }
          const pendingKey = markMobileSourceStart();
          if (!pendingKey) {
            hint.textContent = "本机存储不可用，无法保留创建结果提示，请先检查浏览器设置再试。";
            return;
          }
          start.disabled = true;
          state.attachingSource = true;
          hint.textContent = initialSession ? "正在接入当前对话…" : "正在开始新对话…";
          try {
            const result = await api(`/api/${id}/start`, {method:"POST", body:JSON.stringify({preview_id:d.preview_id,start_intro:true,...(initialSession ? {session_id:initialSession} : {})})});
            if (!result?.session) throw Error("结果无效");
            if (epoch !== mobileSourceFormEpoch || (state.session?.id || null) !== initialSession) {
              toast("来源接入结果未确认，请在已接入资料列表中核对。"); return;
            }
            finishMobileSourceStart(pendingKey);
            clearMobileSourceForm();
            enterSessionData(result);
            toast(initialSession ? "已接入当前对话" : "已开始新对话");
          } catch (e) {
            if ([400,404,409].includes(e.status)) finishMobileSourceStart(pendingKey);
            if (epoch !== mobileSourceFormEpoch) {
              if (e.status !== 400) toast("创建请求已发出，结果未确认；请在已接入资料列表中核对。");
              return;
            }
            hint.textContent = e.status === 400 ? "预览已失效，请重新读取并确认。" : [404,409].includes(e.status) ? e.message : "未能确认接入结果，请在已接入资料列表中核对；如需重试，请重新读取预览。";
          } finally { state.attachingSource = false; }
        };
        await $("#m-source-start").onclick();
      } catch (e) { if (epoch === mobileSourceFormEpoch) hint.textContent = `读取失败：${e.message}`; }
      finally { if (epoch === mobileSourceFormEpoch) button.disabled = false; }
    };
  }

  function openMobilePublicSource(id) {
    const sid = state.session?.id || null, epoch = mobileSourceFormEpoch;
    $("#m-wz3-title").textContent = id === 'jike' ? '即刻公开帖子' : 'WaytoAGI 公开资料';
    $("#m-read-btn").classList.add('is-hidden');
    $("#m-read-items").innerHTML = ''; $("#m-read-scope").innerHTML = '';
    window.XinjiPublicLinkPicker.mount($("#m-read-head"), {
      sourceId:id, api, autoAttach:true, isCurrent:() => epoch === mobileSourceFormEpoch && (state.session?.id || null) === sid,
      onConfirm: async (read) => {
        if (epoch !== mobileSourceFormEpoch || (state.session?.id || null) !== sid || state.attachingSource || state.revokingSource || state.confirmingSource || mActiveTurn || mQueuedTurns.length || mTurnQueue.length) throw Error('对话正在更新，请稍后重新读取。');
        state.attachingSource = true;
        try {
          const data = await api('/api/onboarding/real/start', {method:'POST',body:JSON.stringify({source_id:id,preview_id:read.preview_id,session_id:sid,start_intro:true})});
          if (!data?.session || (sid && data.session.id !== sid)) throw Error('接入结果未确认');
          if (epoch === mobileSourceFormEpoch && (state.session?.id || null) === sid) { enterSessionData(data); toast('公开正文已接入当前对话'); }
        } finally { state.attachingSource = false; }
      }
    });
    showWz(3);
  }

  function openMobileLocalFiles() {
    clearMobileSourceForm(); const epoch = mobileSourceFormEpoch;
    $("#m-wz3-title").textContent = "选择文本文件";
    $("#m-read-btn").classList.add("is-hidden");
    $("#m-read-items").innerHTML = "";
    $("#m-read-scope").innerHTML = "";
    const initialSession = state.session?.id || null;
    window.XinjiFilePicker.mount($("#m-read-head"), {sessionId: initialSession, autoAttach:true, isCurrent: () => epoch === mobileSourceFormEpoch, onConfirm: async (files, sid) => {
      if (epoch !== mobileSourceFormEpoch || (state.session?.id || null) !== sid || state.attachingSource || state.revokingSource || state.confirmingSource || mActiveTurn || mQueuedTurns.length || mTurnQueue.length) {
        const e = new Error("对话已切换或消息仍在发送，请回到对话后重新选择。"); e.status = 409; throw e;
      }
      state.attachingSource = true;
      try {
        const d = await api("/api/local-files/confirm", {method: "POST", body: JSON.stringify({session_id: sid, files, start_intro:true})});
        if (!d?.session || (sid && d.session.id !== sid)) throw Error("接入结果未确认");
        if (epoch !== mobileSourceFormEpoch || (state.session?.id || null) !== sid) { connectionIntro.start(d.intro); return; }
        enterSessionData(d); toast(sid ? "已接入当前对话" : "已开始新对话");
      } finally { state.attachingSource = false; }
    }});
    showWz(3);
  }

  async function readMobileConfirmedSource() {
    const id = wz.pendingSource;
    const button = $("#m-read-btn");
    if (!id || button.disabled) return;
    const sessionId = state.session?.id || null;
    const epoch = mobileSourceFormEpoch;
    let uncertain = false, pendingKey = null;
    button.disabled = true; button.textContent = "连接中…";
    $("#m-read-scope").textContent = "正在读取，若出现系统权限窗口，请完成后稍等。";
    try {
      const read = await api('/api/onboarding/real/read', {method:'POST',  body:JSON.stringify({source_id:id,read_window:'recent7',start_intro:true})});
      if (epoch !== mobileSourceFormEpoch) return;
      if (!read.ok || !read.preview_id) throw Error([read.error || '读取失败', read.hint].filter(Boolean).join(' · '));
      if ((state.session?.id || null) !== sessionId || state.attachingSource || state.revokingSource || state.confirmingSource || mActiveTurn || mQueuedTurns.length || mTurnQueue.length) throw Error('对话正在更新，请稍后重新授权。');
      state.attachingSource = true;
      pendingKey = markMobileSourceStart();
      uncertain = true;
      const data = await api('/api/onboarding/real/start', {method:'POST',body:JSON.stringify({source_id:id,preview_id:read.preview_id,session_id:sessionId,start_intro:true})});
      if (!data?.session || (sessionId && data.session.id !== sessionId)) throw Error('接入结果尚未确认');
      uncertain = false; finishMobileSourceStart(pendingKey);
      if (epoch !== mobileSourceFormEpoch || (state.session?.id || null) !== sessionId) return;
      wz.pendingSource = null;
      enterSessionData(data);
    } catch (error) {
      if (error.status >= 400 && error.status < 500) { uncertain = false; if (pendingKey) finishMobileSourceStart(pendingKey); }
      if (epoch === mobileSourceFormEpoch) $("#m-read-scope").textContent = uncertain ? '连接结果尚未确认，请返回聊天后核对连接状态。' : error.message;
    } finally {
      state.attachingSource = false;
      if (epoch === mobileSourceFormEpoch) { button.disabled = uncertain; button.textContent = uncertain ? '请先核对连接状态' : '授权'; }
    }
  }

  async function confirmMobileFeishu(url, previewId, hint, button, guard = null) {
    if (guard && !guard.current()) return;
    if (button.disabled) return;
    if (state.attachingSource || state.revokingSource || state.confirmingSource || mActiveTurn || mQueuedTurns.length || mTurnQueue.length) {
      hint.textContent = "对话消息还在发送，请等回复完成后再接入文档。";
      return;
    }
    if (guard) {
      guard.pendingKey = markMobileSourceStart();
      if (!guard.pendingKey) { hint.textContent = "本机存储不可用，请检查设置后再接入。"; return; }
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
      if ((sid && state.session?.id !== sid) || (guard && !guard.current())) return;
      if (guard?.pendingKey) finishMobileSourceStart(guard.pendingKey);
      enterSessionData(data);
      toast(sid ? "已接入当前对话" : "已开始新对话");
    } catch (e) {
      if (guard?.pendingKey && [400,404,409].includes(e.status)) finishMobileSourceStart(guard.pendingKey);
      if ((sid && state.session?.id !== sid) || (guard && !guard.current())) return;
      if (e.status === 409) {
        hint.textContent = e.message;
        button.disabled = false;
      } else if (e.status === 400) {
        hint.textContent = "读取预览已失效，请重新读取并确认文档。";
      } else {
        hint.textContent = "接入结果未确认。请在已接入资料列表中刷新核对，确认是否已接入；如未接入请重新预览。";
      }
    } finally {
      state.attachingSource = false;
    }
  }

  function openMobileFeishuAccount() {
    clearMobileSourceForm();
    const epoch = mobileSourceFormEpoch;
    let sessionId = state.session?.id || null;
    const current = () => epoch === mobileSourceFormEpoch && !$("#m-onboard").classList.contains("is-hidden") &&
      (!sessionId || state.session?.id === sessionId);
    showWz(3); $("#m-wz3-title").textContent = "连接飞书";
    $("#m-read-btn").classList.add("is-hidden"); $("#m-read-items").innerHTML = ""; $("#m-read-scope").innerHTML = "";
    window.XinjiFeishuAccountPicker.mount($("#m-read-head"), {api, getSessionId: () => state.session?.id, isCurrent: current,
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
        sessionId = state.session.id; return sessionId;
      },
      onAuthorize: () => startLarkAuthMobile("account"),
      onConnected: data => finishConnection(data),
      onReturn: () => { closeSheet(); closeMobileWizard(); $("#m-input")?.focus(); },
      onSingleDocument: openMobileFeishu,
      onManageSources: () => { closeMobileWizard(); openSheet("more"); },
      onStateChange: data => { state.feishuAccount = data; window.XinjiFeishuAccountPicker.syncBadges(document, data); },
    });
  }

  function openMobileFeishu() {
    clearMobileSourceForm();
    const initialSession = state.session?.id || null, epoch = mobileSourceFormEpoch;
    let requestId = 0;
    const current = () => epoch === mobileSourceFormEpoch && (state.session?.id || null) === initialSession;
    showWz(3);
    $("#m-wz3-title").textContent = "选择飞书文档";
    $("#m-read-btn").classList.add("is-hidden");
    $("#m-read-scope").innerHTML = "";
    $("#m-read-items").innerHTML = "";
    $("#m-read-head").innerHTML = `
      <p class="lede">只接入你指定的单篇文档快照。读取时会核对飞书权限；如需授权，可点击重新连接。</p>
      <button type="button" class="btn ghost small" id="m-feishu-reconnect">重新连接飞书</button>
      <div class="feishu-search-row"><input id="m-feishu-q" placeholder="项目 / 周会 / PRD" /><button class="btn ghost small" id="m-feishu-search">搜索</button></div>
      <details><summary>搜索不可用？指定一篇文档</summary><div class="feishu-search-row"><input id="m-feishu-url" placeholder="飞书文档链接" /><button class="btn ghost small" id="m-feishu-url-read">读取</button></div></details>
      <button class="btn ghost small is-hidden" id="m-feishu-search-auth">授权搜索云空间</button>
      <p class="synthetic" id="m-feishu-hint">不会遍历全库。</p>`;
    $("#m-feishu-reconnect").onclick = () => startLarkAuthMobile("document", {force: true});
    const previewSelected = async (url) => {
      const request = ++requestId;
      const hint = $("#m-feishu-hint");
      $("#m-read-items").innerHTML = "";
      if (!url) { hint.textContent = "先选择一篇文档"; return; }
      if (!readableFeishuUrl(url)) { hint.textContent = "该类型暂不支持读取；请提供飞书文档或知识库链接。"; return; }
      try {
        hint.textContent = "正在读取所选文档…";
        const pv = await api("/api/lark/preview", { method: "POST", body: JSON.stringify({ url }) });
        if (!current() || request !== requestId) return;
        if (!pv.ok) { hint.textContent = pv.error + (pv.hint ? " · " + pv.hint : ""); return; }
        $("#m-read-items").innerHTML = `<p class="lede">${esc(pv.title)} · 提取后保留 ${pv.length} 字</p>${feishuPreviewMarkup(pv)}<p class="note">${feishuDisclosure}</p><button class="btn primary wide" id="m-feishu-start">${state.session ? "确认接入当前对话" : "确认并开始"}</button>`;
        $("#m-feishu-start").onclick = () => {
          const button = $("#m-feishu-start");
          if (!current() || request !== requestId || button.disabled) return;
          return confirmMobileFeishu(url, pv.preview_id, hint, button, {current});
        };
        hint.textContent = "请确认文档后继续。";
      } catch (e) { if (current() && request === requestId) hint.textContent = e.message; }
    };
    const run = async () => {
      const request = ++requestId;
      const q = $("#m-feishu-q").value.trim();
      if (!q) { $("#m-feishu-hint").textContent = "先输入关键词"; return; }
      $("#m-feishu-hint").textContent = "搜索中…";
      const d = await api("/api/lark/docs", {method:"POST", body:JSON.stringify({q})});
      if (!current() || request !== requestId) return;
      if (!d.ok) {
        $("#m-feishu-hint").textContent = d.error + (d.hint ? " · " + d.hint : "");
        $("#m-feishu-search-auth").classList.toggle("is-hidden", d.permission_issue !== "user_grant");
        return;
      }
      $("#m-feishu-search-auth").classList.add("is-hidden");
      if (!d.items.length) { $("#m-feishu-hint").textContent = "没有找到可访问的文档"; return; }
      $("#m-feishu-hint").textContent = "仅支持文档或知识库链接；妙搭应用等其他类型暂不能读取。";
      $("#m-read-items").innerHTML = d.items.map((it, i) => `<button class="feishu-doc" data-mfeishu="${i}" ${readableFeishuUrl(it.url) ? "" : "disabled"}><b>${esc(it.title)}</b><span>${esc(it.type)}${readableFeishuUrl(it.url) ? "" : " · 该类型暂不支持读取"}</span></button>`).join("");
      $("#m-read-items").querySelectorAll("[data-mfeishu]").forEach((b) => {
        b.onclick = () => previewSelected(d.items[Number(b.dataset.mfeishu)].url);
      });
    };
    const searchSafely = () => {
      const expected = requestId + 1;
      return run().catch((e) => { if (current() && requestId === expected) $("#m-feishu-hint").textContent = `搜索失败：${e.message}`; });
    };
    $("#m-feishu-search").onclick = searchSafely;
    $("#m-feishu-search-auth").onclick = () => startLarkAuthMobile("search");
    $("#m-feishu-url-read").onclick = () => previewSelected($("#m-feishu-url").value.trim());
    $("#m-feishu-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); searchSafely(); } });
  }

  async function startMobileReal(editFirst = false) {
    if (!wz.realSource) { toast("请先选择并核对一份真实来源。"); return; }
    const selected = wz.realSource;
    const sid = selected.sessionId;
    if ((state.session?.id || null) !== sid || state.attachingSource || state.revokingSource || state.confirmingSource || mActiveTurn || mQueuedTurns.length || mTurnQueue.length) { toast("对话已切换或消息仍在发送，请重新选择。"); return; }
    state.attachingSource = true;
    try {
      const d = await api("/api/onboarding/real/start", { method: "POST", body: JSON.stringify({ source_id: wz.realSource.id, start_intro:true, preview_id: wz.realSource.read.preview_id, ...(sid ? {session_id:sid} : {}) }) });
      if (wz.realSource !== selected || (state.session?.id || null) !== sid) { connectionIntro.start(d.intro); return; }
      enterSessionData(d);
      if (editFirst) openSheet("understand");
    } catch (e) { toast(e.message); }
    finally { state.attachingSource = false; }
  }

  let mobileAction = null;

  function openMobileAction(kind, idx, draft = null) {
    const ins = draft ? {title: draft.title, text: draft.text} : (state.context?.insights || [])[idx];
    if (!ins || !state.session || !["message", "reminder", "calendar"].includes(kind)) return;
    if (!draft && (ins.source_id || state.context?.sources) && !mobileInsightUsable(ins)) {
      toast("相关来源已移除或待核对，请重新打开记忆。"); return;
    }
    mobileAction = {kind, title: ins.title || "", detail: ins.text || "", sessionId: state.session.id};
    const titles = {reminder: "新建提醒", calendar: "新建日历安排", message: "新建消息草稿"};
    $("#m-action-title").textContent = titles[kind];
    $("#m-action-detail").textContent = kind === "message" ? "编辑后只保存本机草稿，不会发送。" : "先编辑并核对，默认只保存在本机；写入系统需要你另行勾选。提醒的时间只存本机，系统提醒目前只写标题、不设到期。";
    $("#m-action-name").value = ins.title || "";
    $("#m-action-name").readOnly = false;
    $("#m-action-message-row").classList.remove("is-hidden");
    $("#m-action-message").value = ins.text || "";
    $("#m-action-message").readOnly = false;
    $("#m-action-content-label").textContent = kind === "message" ? "草稿正文" : "补充说明（仅保存本机）";
    const realRow = $("#m-action-real-row");
    realRow.classList.toggle("is-hidden", kind === "message");
    if (kind !== "message") realRow.lastChild.textContent = kind === "calendar" ? " 尝试写入系统日历（仅标题与时间，需权限）" : " 尝试写入系统提醒事项（仅标题，不设到期，需权限）";
    $("#m-action-when-row").classList.toggle("is-hidden", kind === "message");
    const when = $("#m-action-when");
    when.disabled = false;
    when.value = "";
    if (kind === "calendar") {
      const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
      const pad = value => String(value).padStart(2, "0");
      when.value = `${tomorrow.getFullYear()}-${pad(tomorrow.getMonth() + 1)}-${pad(tomorrow.getDate())}T10:00`;
    }
    $("#m-action-real").checked = false;
    $("#m-action-real").disabled = false;
    $("#m-action-confirm").disabled = false;
    $("#m-action-result").classList.add("is-hidden");
    $("#m-action").classList.remove("is-hidden");
  }

  async function confirmMobileAction() {
    if (!mobileAction || !state.session) return;
    const action = mobileAction, button = $("#m-action-confirm"), result = $("#m-action-result");
    if (button.disabled) return;
    if (action.sessionId !== state.session.id) {
      result.textContent = "对话已变化，请重新打开草稿预览。";
      result.classList.remove("is-hidden"); return;
    }
    const when = action.fromSaved ? action.when || "" : action.kind === "message" ? "" : $("#m-action-when")?.value || "";
    const real = !!$("#m-action-real")?.checked && ["reminder", "calendar"].includes(action.kind);
    if ((real || !action.fromSaved) && action.kind === "calendar" && !when) {
      result.textContent = "请先选择日历的时间。"; result.classList.remove("is-hidden"); return;
    }
    const title = action.fromSaved ? action.title : ($("#m-action-name")?.value ?? action.title).trim();
    const detail = action.fromSaved ? action.detail : ($("#m-action-message")?.value ?? action.detail);
    if (!title || title.length > 200) { result.textContent = "请填写 1–200 字的标题。"; result.classList.remove("is-hidden"); return; }
    if ((action.kind === "message" && !detail.trim()) || detail.length > 2000) {
      result.textContent = detail.trim() ? "草稿仍完整保留在编辑框。本机保存上限为 2000 字，请精简后再确认。" : "先填写想保存的草稿正文。";
      result.classList.remove("is-hidden"); return;
    }
    button.disabled = true;
    result.classList.add("is-hidden");
    try {
      if (action.existingId) {
        const data = await api(`/api/actions?session_id=${encodeURIComponent(action.sessionId)}`);
        if (mobileAction !== action || state.session?.id !== action.sessionId) return;
        const existing = (data.actions || []).find(item => item.id === action.existingId);
        if (!existing || existing.status !== "previewed") {
          result.textContent = !existing ? "没有找到这条本机预览，请在任务页核对。" : "此记录已处理或结果待确认，请在任务页核对；不会再次写入。";
          result.classList.remove("is-hidden"); return;
        }
      } else {
        const created = await api("/api/action", {method: "POST", body: JSON.stringify({session_id: action.sessionId, kind: action.kind, title, detail, when})});
        if (!created?.id) throw Error("预览记录结果未确认");
        action.existingId = created.id;
      }
      if (mobileAction !== action || state.session?.id !== action.sessionId) return;
      const done = await api(`/api/action/${encodeURIComponent(action.existingId)}/commit`, {method: "POST", body: JSON.stringify({real})});
      if (mobileAction !== action || state.session?.id !== action.sessionId) return;
      if (done.status !== "committed") {
        result.textContent = action.kind === "message" ? "草稿保存结果未确认，请到任务页核对，暂勿重复保存。" : ["unknown", "executing"].includes(done.status) ? "未确认写入，请先到系统检查，再到任务页核对；当前不会重试写入。" : done.error || "未能完成，请到任务页查看记录。";
        result.classList.remove("is-hidden"); return;
      }
      toast(done.real ? `已写入系统${action.kind === "calendar" ? "日历" : "提醒事项"}` : action.kind === "message" ? "消息草稿已保存（未发送）" : "已保存在本机，未写入系统。");
      $("#m-action").classList.add("is-hidden");
      mobileAction = null;
      if (typeof loadMobileTaskActions === "function") loadMobileTaskActions();
    } catch (error) {
      if (mobileAction !== action || state.session?.id !== action.sessionId) return;
      result.textContent = action.kind === "message" ? "草稿保存结果未确认，请到任务页核对，暂勿重复保存。" : "未确认写入，请先到系统检查，再到任务页核对；当前不会重试写入。";
      result.classList.remove("is-hidden");
    }
  }

  function closeMobileAction() {
    mobileAction = null;
    $("#m-action").classList.add("is-hidden");
  }

  function renderInsights() {
    const r = wz.read;
    $("#m-wz-start").textContent = state.session ? "接入当前对话" : "开始对话";
    $("#m-insights").innerHTML = (['apple_calendar', 'apple_reminders'].includes(r.connector?.id) && !r.items?.length ? `<div class="m-insight"><b>读取成功，当前没有条目</b><p>${esc(r.connector?.id === 'apple_reminders' ? '没有未完成的提醒事项。可以保存这次读取结果，之后再重新读取。' : '所选范围内没有日程。可以保存这次读取结果，之后再重新读取。')}</p></div>` : '') + r.insights.map((i) =>
      `<div class="m-insight"><div class="t">${esc(i.type.toUpperCase())}</div><b>${esc(i.title)}</b><p>${esc(i.text)}</p></div>`).join("");
    const u = r.understanding;
    const row = (k, list) => list.map((x) => `<div class="m-row"><b>${k}</b>${esc(x)}</div>`).join("");
    $("#m-under").innerHTML = row("事实", u.facts) + row("推测", u.inferences) + row("问题", u.questions);
    showWz(4);
  }

  async function startConnector() { toast("请先选择并核对一份真实来源。"); }

  // ---------- render ----------
  function renderAll() {
    renderMessages();
    renderNext();
    updateCount();
  }

  window.XinjiCompanionChoices.bind(document, $("#m-input"));

  const chatScroll = window.createChatScroll($("#m-main"), $("#m-chat-new-messages"));
  let renderedChatSession = null;
  let renderedMessageIds = new Set();
  state.delivery = window.XinjiChatDelivery.create({state, api, render: () => renderMessages(),
    stopButton: $("#m-stop"), busy: () => !!mActiveTurn,
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
    const box = $("#m-messages");
    const empty = state.messages.filter((m) => m.role === "user").length === 0;
    const showEmpty = empty && state.session?.mode === "empty" && !state.messages.some(message => message.connection_intro) && !(state.context?.sources?.length || state.context?.connector_id || state.context?.items?.length);
    $("#m-chat-empty")?.classList.toggle("is-hidden", !showEmpty);
    const lastAssistant = [...state.messages].reverse().find((m) => m.role === "assistant");
    const visibleMessages = showEmpty ? [] : state.messages;
    visibleMessages.forEach(decorateAssistantMessage);
    const sessionChanged = renderedChatSession !== state.session?.id;
    const newMessage = !sessionChanged && visibleMessages.some(message => !String(message.id).startsWith("local-") && !renderedMessageIds.has(message.id));
    const update = () => { box.innerHTML = visibleMessages.map((m, index) => {
      const role = m.role === "user" ? "user" : "assistant";
      const sugg = (lastAssistant && m.id === lastAssistant.id && (m.suggestions || []).length)
        ? `<div class="m-suggests">${m.suggestions.map((s) => `<button class="m-suggest" data-suggest="${esc(s)}">${esc(s)}</button>`).join("")}</div>`
        : "";
      const cites = window.XinjiFeishuAccountPicker?.renderCitations(m, {includeMemories:false}) || "";
      const draft = window.XinjiActionCards.chatDraft(visibleMessages, index);
      const draftButton = draft ? `<div class="m-suggests"><button class="m-suggest" data-chat-draft="${index}">查看并保存为消息草稿</button></div>` : "";
      const parts = role === "assistant" && Array.isArray(m.bubbles) && m.bubbles.length ? m.bubbles : [m.text];
      const voiceButton = role === "assistant" && !m.delivery_pending ? `<button type="button" class="message-topic" data-voice-message="${index}" aria-label="朗读这条回复" title="${esc(window.EchoShared?.copy?.['voice.disclosure'] || '由设备语音朗读，不会自动播放或创建语音文件。')}" aria-pressed="false">${esc(window.EchoShared?.copy?.['voice.read'] || '朗读')}</button><button type="button" class="message-topic" hidden data-voice-clip="${index}">生成语音</button><span data-voice-clip-slot="${index}"></span>` : "";
      const proposalButton = m.action_proposal && !m.delivery_pending ? `<div class="m-suggests"><button class="m-suggest" data-action-proposal="${index}">查看提醒预览</button></div>` : "";
      return `<div class="msg ${role}" data-message-id="${esc(m.id)}" data-persona-id="${esc(m.persona_id || '')}" data-interaction-mode="${esc(m.interaction_mode || '')}">${parts.map(part => `<div class="bubble">${renderMemeText(part)}</div>`).join("")}${cites ? `<div class="cites">${cites}</div>` : ""}${sugg}${draftButton}${proposalButton}${voiceButton}<button type="button" class="message-topic" data-topic-message="${esc(m.id)}" ${String(m.id).startsWith("local-") ? 'disabled title="发送完成后可标记话题"' : ""}>标记话题</button></div>`;
    }).join(""); };
    if (showEmpty) {
      update();
      $("#m-main").scrollTop = 0;
      $("#m-chat-new-messages").classList.add("is-hidden");
    } else {
      chatScroll.render(update, { forceBottom: forceBottom || sessionChanged, newMessage });
    }
    globalThis.XinjiMobileWorkspace?.filterMessages(box);
    renderedChatSession = state.session?.id;
    renderedMessageIds = new Set(visibleMessages.map(message => message.id));
    state.delivery?.schedule();
    const draftSession = state.session?.id;
    window.XinjiVoice.pruneClips(draftSession, visibleMessages);
    box.querySelectorAll("[data-voice-message]").forEach(button => {
      const message = visibleMessages[Number(button.dataset.voiceMessage)];
      if (message) window.XinjiVoice.bindMessage(message.id, window.XinjiVoice.readText(message), button, draftSession);
      button.onclick = () => { if (message && state.session?.id === draftSession) window.XinjiVoice.playMessage(message.id, window.XinjiVoice.readText(message), button, draftSession); };
    });
    box.querySelectorAll("[data-voice-clip]").forEach(button => {
      const index = Number(button.dataset.voiceClip), message = visibleMessages[index];
      const container = box.querySelector(`[data-voice-clip-slot="${index}"]`);
      if (!message || !container) return;
      window.XinjiVoice.bindClipControl(button, window.XinjiVoice.clipEligible(message));
      if (window.XinjiVoice.attachClip(draftSession, message.id, message.text, container)) button.textContent = '语音已生成';
      button.onclick = () => window.XinjiVoice.makeClip({sessionId:draftSession, id:message.id, text:message.text, button, container,
        isCurrent:() => state.session?.id === draftSession && state.messages.some(m => m.id === message.id && m.text === message.text && !m.delivery_pending),
        onReady:() => renderMessages()});
    });
    box.querySelectorAll("[data-action-proposal]").forEach(button => {
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
          if (result === "ready") openSheet("today");
          else if (result === "draft") { openSheet("today"); toast("你已有未保存的跟进草稿，请先处理它，再打开这条建议。"); }
          else if (result === "pending") { openSheet("today"); toast("上一条跟进的保存结果待核对，请先处理它。"); }
          else toast("这条建议已变化，请重新发起提醒。");
        } catch (error) { if (state.session?.id === draftSession) toast(`暂时无法核对建议：${error.message}`); }
        finally { button.disabled = false; }
      };
    });
    box.querySelectorAll("[data-chat-draft]").forEach((button) => {
      button.onclick = () => {
        if (state.session?.id !== draftSession) return;
        const draft = window.XinjiActionCards.chatDraft(visibleMessages, Number(button.dataset.chatDraft));
        if (draft) openMobileAction("message", null, draft);
      };
    });
    box.querySelectorAll("[data-suggest]").forEach((b) => { b.onclick = () => send(b.dataset.suggest); });
  }

  let mAuthTimer = null;
  let mAuthGeneration = 0, mAuthActive = false;
  let mAuthPollGeneration = null, mAuthPopup = null, mAuthPurpose = "document", mAuthForce = false;
  let mAuthSession = null, larkConnectedThisPage = false;
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
  function mAuthCurrent(generation) { return mAuthActive && generation === mAuthGeneration && (state.session?.id || null) === mAuthSession; }
  function clearMAuthLinks() {
    $("#m-auth-url").classList.add("is-hidden"); $("#m-auth-url").removeAttribute("href"); $("#m-auth-url").textContent = "在飞书中打开授权";
  }
  function closeLarkAuthMobile(resume = true) {
    ++mAuthGeneration; mAuthActive = false; mAuthPollGeneration = null;
    clearInterval(mAuthTimer); mAuthTimer = null;
    discardLarkAuthWindow(mAuthPopup); mAuthPopup = null;
    clearMAuthLinks();
    $("#m-auth").classList.add("is-hidden");
    if (typeof finishMobileAuthSurface === "function") finishMobileAuthSurface({resume});
  }
  function failMAuth(generation, message, response = {}) {
    if (!mAuthCurrent(generation)) return;
    mAuthActive = false; clearInterval(mAuthTimer); mAuthTimer = null;
    clearMAuthLinks(); discardLarkAuthWindow(mAuthPopup); mAuthPopup = null;
    $("#m-auth-status").textContent = message || "连接尚未完成，请重新发起授权。";
    $("#m-auth-hint").textContent = "旧授权链接已停止显示。不会自动重试或创建新的 CLI 应用。";
    $("#m-auth-retry").classList.remove("is-hidden"); $("#m-auth-retry").disabled = false;
    if (response.error_code === "needs_app_setup" && response.setup_url === "https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md") {
      $("#m-auth-url").href = response.setup_url;
      $("#m-auth-url").textContent = "首次配置飞书 CLI 应用";
      $("#m-auth-url").classList.remove("is-hidden");
      $("#m-auth-hint").textContent = "先按官方指南完成首次应用配置，再回来重新发起授权。这里不会自动创建应用。";
    }
  }

  async function startLarkAuthMobile(purpose = "document", {force = false} = {}) {
    // Reserve while still inside the user's click. No credentials or authorization URL are stored.
    const popup = reserveLarkAuthWindow();
    if (typeof beginMobileAuthSurface === "function") beginMobileAuthSurface();
    discardLarkAuthWindow(mAuthPopup); mAuthPopup = popup;
    const generation = ++mAuthGeneration;
    const currentPurpose = ["search", "account"].includes(purpose) ? purpose : "document";
    mAuthPurpose = currentPurpose; mAuthForce = force === true; mAuthSession = state.session?.id || null;
    if (currentPurpose === "document") larkConnectedThisPage = false;
    mAuthActive = true; mAuthPollGeneration = null;
    $("#m-auth").classList.remove("is-hidden");
    clearMAuthLinks();
    $("#m-auth-hint").textContent = "正在唤起飞书官方授权…";
    $("#m-auth-status").textContent = "等待你在飞书中确认…";
    $("#m-auth-retry").classList.add("is-hidden"); $("#m-auth-retry").disabled = true;
    $("#m-auth-retry").onclick = () => startLarkAuthMobile(mAuthPurpose, {force: mAuthForce});
    clearInterval(mAuthTimer); mAuthTimer = null;
    try {
      const options = {method: "POST"};
      if (mAuthForce) options.body = JSON.stringify({force: true});
      const value = await api(currentPurpose === "account" ? "/api/auth/lark/account/start" : currentPurpose === "search" ? "/api/auth/lark/search/start" : "/api/auth/lark/start", options);
      if (!mAuthCurrent(generation)) { discardLarkAuthWindow(popup); return; }
      if (value.status === "success") { mAuthDone(generation, currentPurpose); return; }
      if (value.status !== "starting" && value.status !== "pending") { failMAuth(generation, value.error || "无法启动飞书连接，请重试。", value); return; }
      if (value.status === "pending") { if (!showMobileLarkPending(value, currentPurpose, generation)) return; }
      else $("#m-auth-hint").textContent = "授权正在准备，请稍候…";
      mAuthTimer = setInterval(() => pollMobileLarkAuth(generation, currentPurpose), 2000);
    } catch (error) { failMAuth(generation, error.message || "暂时无法连接授权服务，请重试。"); }
  }

  function showMobileLarkPending(value, purpose, generation) {
    if (!mAuthCurrent(generation)) return false;
    const url = officialLarkAuthURL(value.url);
    if (!url) { failMAuth(generation, "授权地址不是有效的飞书官方 HTTPS 地址，请重新连接。"); return false; }
    $("#m-auth-url").href = url; $("#m-auth-url").classList.remove("is-hidden");
    const slot = mAuthPopup;
    const updateHint = () => {
      if (!mAuthCurrent(generation) || mAuthPopup !== slot) return;
      $("#m-auth-hint").textContent = (purpose === "account" ? "请在飞书核对搜索和文档只读权限；授权后会自动完成连接并回到聊天。" : purpose === "search" ? "将单独申请搜索云空间权限。" : "只连接现有飞书 CLI，不会新建应用。") +
        (slot?.nativePending ? "正在请求系统浏览器打开飞书官方页面，也可点击下方链接。" : slot?.navigated ?
          slot.native ? "已请求系统浏览器打开飞书官方页面；若未打开，可点击下方链接。" : "请在已打开的飞书官方页面确认；也可使用下方链接。" :
          "未能自动打开页面，请点击下方链接继续授权。");
    };
    if (slot?.native && !slot.nativeRequested) {
      slot.nativeRequested = true; slot.nativePending = true;
      const settled = opened => {
        if (!mAuthCurrent(generation) || mAuthPopup !== slot) return;
        slot.nativePending = false; slot.navigated = opened === true; updateHint();
      };
      try { Promise.resolve(slot.native(url)).then(settled, () => settled(false)); } catch (_) { settled(false); }
    } else if (!slot?.navigated && slot?.window) {
      try { if (!slot.window.closed) { slot.window.location.replace(url); slot.navigated = true; } } catch (_) {}
    }
    updateHint();
    return true;
  }

  async function pollMobileLarkAuth(generation, purpose) {
    if (!mAuthCurrent(generation) || mAuthPollGeneration === generation) return;
    mAuthPollGeneration = generation;
    try {
      const value = await api(purpose === "account" ? "/api/auth/lark/account/status" : purpose === "search" ? "/api/auth/lark/search/status" : "/api/auth/lark/status");
      if (!mAuthCurrent(generation)) return;
      if (value.status === "success") { await mAuthDone(generation, purpose); return; }
      if (value.status === "pending") { showMobileLarkPending(value, purpose, generation); return; }
      if (value.status !== "starting") failMAuth(generation, value.error || "授权已失效或未完成，请重新连接。", value);
    } catch (error) { failMAuth(generation, "暂时无法核对授权结果，请重试。不会自动重新授权。"); }
    finally { if (mAuthPollGeneration === generation) mAuthPollGeneration = null; }
  }

  async function mAuthDone(generation, purpose) {
    if (!mAuthCurrent(generation)) return;
    mAuthActive = false; clearInterval(mAuthTimer); mAuthTimer = null;
    discardLarkAuthWindow(mAuthPopup); mAuthPopup = null; clearMAuthLinks();
    if (purpose === "account") {
      $("#m-auth-status").textContent = "授权已完成，正在连接…";
      $("#m-auth-hint").textContent = "完成后会自动回到聊天。";
      try {
        const data = await api('/api/lark/account/connect', {method:'POST', body:JSON.stringify({session_id:mAuthSession,start_intro:true})});
        if (generation !== mAuthGeneration || (state.session?.id || null) !== mAuthSession) return;
        if (data?.ok !== true || data.enabled !== true || data.ready === false) throw Error([data?.error || '连接尚未完成', data?.hint].filter(Boolean).join(' · '));
        state.feishuAccount = data; window.XinjiFeishuAccountPicker.syncBadges(document, data);
        finishMobileAuthSurface({resume:false}); $("#m-auth").classList.add("is-hidden");
        finishConnection(data); toast('飞书已连接');
      } catch (error) {
        if (generation !== mAuthGeneration || (state.session?.id || null) !== mAuthSession) return;
        $("#m-auth-status").textContent = error.message + ' 请关闭后重新核对连接状态。';
        $("#m-auth-hint").textContent = '还没有确认连接成功。';
      }
      return;
    }
    const documentReady = purpose === "document";
    if (documentReady) larkConnectedThisPage = true;
    $("#m-auth-status").textContent = documentReady ? "已连接当前飞书 CLI，请选择文档。" : "搜索授权流程已完成，请重试搜索；如仍失败可粘贴文档链接。";
    $("#m-auth-hint").textContent = "还没有读取文档；选择后仍需预览和确认。";
    setTimeout(() => {
      if (generation !== mAuthGeneration || (state.session?.id || null) !== mAuthSession) return;
      $("#m-auth").classList.add("is-hidden");
      const resumed = typeof finishMobileAuthSurface === "function" && finishMobileAuthSurface({documentReady, accountReady:purpose === "account"});
      if (!resumed && !$("#m-onboard").classList.contains("is-hidden")) { showWz(2); loadRealSources(); }
    }, 800);
    toast(documentReady ? "已连接飞书，请选择文档" : "搜索授权流程已完成，请重试搜索");
  }

  function renderMemeText(text) {
    return window.XinjiMeme.render(text, memes, esc);
  }

  async function loadPluginsMobile() {
    try {
      const d = await api("/api/plugins");
      memes = (d.meme && d.meme.items) || [];
      if (state.session) renderMessages();
      $("#m-meme")?.classList.toggle("is-hidden", !memes.length);
      const grid = $("#m-meme-grid");
      if (grid) {
        grid.innerHTML = memes.map((m, i) => `<button class="meme-item" data-meme="${i}"><img src="${esc(m.url)}" alt="${esc(m.label)}" loading="lazy"><span>${esc(m.label)}</span></button>`).join("");
        grid.querySelectorAll("[data-meme]").forEach((b) => {
          b.onclick = () => { $("#m-meme-modal").classList.add("is-hidden"); send(`[表情: ${memes[Number(b.dataset.meme)].id}]`); };
        });
      }
    } catch (_) {}
  }

  async function loadCarryover() {
    const box = $("#m-carryover");
    if (!box || !state.session) return;
    const sid = state.session.id;
    if (localStorage.getItem("xinji_carry_dismiss_" + sid)) { box.classList.add("is-hidden"); return; }
    try {
      const d = await api(`/api/carryover?session_id=${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid) return;
      const items = d.memories || [], current = d.current_confirmed || [];
      if (!items.length) { box.classList.add("is-hidden"); return; }
      const content = $("#m-carryover-text");
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
      $("#m-carry-accept").onclick = async () => {
        const button = $("#m-carry-accept");
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
      $("#m-carry-dismiss").onclick = () => {
        localStorage.setItem("xinji_carry_dismiss_" + sid, "1");
        box.classList.add("is-hidden");
      };
    } catch (_) { if (state.session?.id === sid) box.classList.add("is-hidden"); }
  }

  function renderStarters() {
    const bar = $("#m-starters");
    if (!bar) return;
    const starters = state.context?.starters || [];
    const empty = state.messages.filter((m) => m.role === "user").length === 0;
    if (!starters.length || !empty) { bar.classList.add("is-hidden"); bar.innerHTML = ""; return; }
    bar.classList.remove("is-hidden");
    bar.innerHTML = starters.map((s) => `<button class="m-starter" data-starter="${esc(s)}">${esc(s)}</button>`).join("");
    bar.querySelectorAll("[data-starter]").forEach((b) => {
      b.onclick = () => { bar.classList.add("is-hidden"); send(b.dataset.starter); };
    });
  }

  function updateCount() {
    const count = $("#m-count");
    if (count) count.textContent = state.memories.filter((m) => m.status !== "deleted").length;
  }

  async function loadNextStep() {
    if (!state.session) return;
    const sid = state.session.id, generation = state.sourceGeneration || 0;
    try {
      const next = await api(`/api/next-step?session_id=${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid || (state.sourceGeneration || 0) !== generation) return;
      state.nextStep = next;
      renderNext();
    } catch (_) {}
  }

  function renderNext() {
    // Suggestions remain available in the Tasks tab without interrupting chat.
    $("#m-next").classList.add("is-hidden");
  }

  async function loadEngine() {
    try {
      const cfg = await api("/api/config");
      const e = $("#m-engine");
      if (e) e.textContent = "在线";
    } catch (_) {}
  }

  // ---------- sheets ----------
  let pairedDevicesPanel = null;
  function openSheet(kind, presetNext = "") {
    if (kind === "device") return;
    const legacyPersona = kind === "persona";
    if (legacyPersona) kind = "settings";
    pairedDevicesPanel?.dispose(); pairedDevicesPanel = null;
    globalThis.XinjiVoice?.stop?.();
    followups.stop();
    typeof mood !== "undefined" && mood?.stop();
    const sheet = $("#m-sheet");
    sheet._xinjiEpoch = (sheet._xinjiEpoch || 0) + 1;
    sheet._xinjiKind = kind;
    sheet.querySelector('[data-update-context]').textContent = kind === 'understand'
      ? '检查更新会核对记忆列表，保留聊天草稿；正在修改的记忆会先保留。'
      : '先保留当前页面；关闭后可读取新内容，正在填写的部分不会被更新替换。';
    sheet.classList.remove("is-hidden", "navigation-sheet");
    $("#m-sheet-title").textContent = { understand: "记忆", bookmark: "任务", tasks: "任务", today: "回响", settings: "设置", persona: "角色与设备", more: "更多" }[kind] || kind;
    if (kind === "understand") renderUnderstanding();
    if (kind === "bookmark" || kind === "tasks") renderBookmark(presetNext);
    if (kind === "today") renderTodayMobile();
    if (kind === "more") renderMore();
    if (kind === "settings") renderDesignSettingsMobile();
    if (legacyPersona) {
      $("#m-settings-persona").open = true;
      $("#m-settings-persona").scrollIntoView({block: "start"});
    }
  }

  async function renderTodayMobile() {
    const sid = state.session?.id;
    if (!sid) return;
    const sheet = $("#m-sheet"), epoch = sheet._xinjiEpoch, body = $("#m-sheet-body");
    const current = () => state.session?.id === sid && sheet._xinjiEpoch === epoch && sheet._xinjiKind === "today";
    body.innerHTML = `<p class="synthetic">正在整理今天…</p>`;
    try {
      const [sess, next, saved] = await Promise.all([
        api(`/api/session/${encodeURIComponent(sid)}`),
        api(`/api/next-step?session_id=${encodeURIComponent(sid)}`),
        api(`/api/actions?session_id=${encodeURIComponent(sid)}`),
      ]);
      if (!current()) return;
      if (sess.session?.id !== sid) throw Error("返回的对话不匹配，请重新打开 Today。");
      const bookmark = sess.bookmark, memories = (sess.memories || []).filter(item => item.status !== "deleted");
      const sources = mobileSources(sess.context, sess.session), actions = saved.actions || [];
      const carry = bookmark ? bookmark.next_step || bookmark.note : next.step || "我想从今天的一件小事说起。";
      const pending = actions.filter(action => ["previewed", "unknown", "executing"].includes(action.status)).length;
      body.innerHTML = `
        <div id="m-today-mood"></div><div id="m-today-followups"></div>
        <div class="m-today-card"><div class="k">${bookmark ? "上次停在这里" : "下一步 · 候选"}</div><b>${esc(bookmark ? bookmark.note : next.step || "先聊一件正在发生的事")}</b><p>${esc(bookmark ? bookmark.next_step || "可以接着说，也可以先放一放。" : next.rationale || "由你决定从哪里开始。")}</p><button type="button" class="btn ghost small" id="m-today-continue">把这条带回聊天</button></div>
        <div class="m-today-card"><div class="k">任务与草稿</div><b>${actions.length} 个已保存动作${pending ? ` · ${pending} 个待确认` : ""}</b><p>查看保存的内容，或自己写一条消息、提醒和日历安排。</p><button type="button" class="text-btn" id="m-today-tasks">打开任务</button></div>
        <div class="m-today-card"><div class="k">关于你的记忆</div><b>${memories.length} 条待核对或已确认的理解</b><p>不准确的地方，随时可以纠正或删除。</p><button type="button" class="text-btn" id="m-today-memories">核对记忆</button></div>
        <div class="m-today-card"><div class="k">这次对话的资料</div><b>${sources.length} 份已接入来源</b><p>${sources.length ? sources.map(source => esc(mobileSourceTitle(source)) + (source.stale ? "（暂停使用）" : "")).join(" · ") : state.feishuAccount?.enabled === true && state.feishuAccount.ready !== false ? "✓ 飞书已连接，聊天时会按需查阅。" : "还没有接入资料。可以先聊聊，需要时再连接。"}</p><button type="button" class="text-btn" id="m-today-sources">管理来源</button></div>`;
      followups.mount($("#m-today-followups"));
      typeof mood !== "undefined" && mood?.mount($("#m-today-mood"));
      $("#m-today-continue").onclick = () => {
        if (!current()) return;
        const input = $("#m-input");
        input.value = input.value.trim() ? `${input.value}\n${carry}` : carry;
        closeSheet();
        input.focus();
      };
      for (const [id, kind] of [["tasks", "tasks"], ["memories", "understand"], ["sources", "more"]]) {
        $("#m-today-" + id).onclick = () => { if (current()) openSheet(kind); };
      }
    } catch (error) {
      if (!current()) return;
      body.innerHTML = `<div id="m-today-mood"></div><div id="m-today-followups"></div><p class="synthetic">暂时无法整理 Today：${esc(error.message)}</p><button type="button" class="btn ghost wide" id="m-today-retry">重新读取</button>`;
      followups.mount($("#m-today-followups"));
      typeof mood !== "undefined" && mood?.mount($("#m-today-mood"));
      $("#m-today-retry").onclick = () => { if (current()) renderTodayMobile(); };
    }
  }

  async function renderPersonaMobile() {
    const sid = state.session?.id;
    if (!sid) return;
    const sheet = $("#m-sheet"), epoch = sheet._xinjiEpoch;
    const body = $("#m-sheet-body");
    body.innerHTML = `<p class="synthetic">正在读取角色与设备…</p>`;
    try {
      const sess = await api(`/api/session/${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid || sheet._xinjiEpoch !== epoch) return;
      const sources = mobileSources(sess.context, sess.session);
      body.innerHTML = `
        <div class="m-today-card"><div class="k">当前对话</div><b>${sources.length} 份来源 · ${(sess.memories || []).length} 条理解</b><p>${sources.length ? sources.slice(0, 3).map(source => esc(mobileSourceTitle(source))).join(" · ") : "可以先聊聊，也可以逐份连接资料。"}</p><button class="text-btn" data-sheet="more">管理来源</button></div>
        <div class="m-today-card"><div class="k">你的伙伴</div><b>回响 · AI 个人伙伴</b><p>可以慢慢介绍自己，也可以随时告诉我哪里理解错了。</p></div>
        <div class="m-today-card"><div class="k">脑电设备</div><b>请在设备所在电脑开启</b><p>当前读取只支持连接 MindLink 服务的本机；手机远程接入仍待联调。</p></div>
        <div class="m-today-card"><div class="k">Rokid 眼镜</div><b>规划中</b><p>将用于查看用户选择的简短提示；型号、连接方式和真机显示待联调。</p></div>
        <button class="btn ghost wide" id="m-connect-apps">连接应用</button>
        <div style="height:8px"></div>
        <button class="btn ghost wide" data-sheet="more">资料与数据</button>`;
      await loadMobilePersonas(body, sid, epoch);
      $("#m-connect-apps")?.addEventListener("click", () => {
        closeSheet();
        showMobileOnboarding();
      });
      body.querySelectorAll("[data-sheet]").forEach((b) => b.onclick = () => openSheet(b.dataset.sheet));
    } catch (e) { if (state.session?.id === sid && sheet._xinjiEpoch === epoch) body.innerHTML = `<p class="synthetic">${esc(e.message)}</p>`; }
  }

  function closeSheet() {
    pairedDevicesPanel?.dispose(); pairedDevicesPanel = null;
    followups.stop();
    typeof mood !== "undefined" && mood?.stop();
    const sheet = $("#m-sheet");
    sheet._xinjiEpoch = (sheet._xinjiEpoch || 0) + 1;
    sheet._xinjiKind = null;
    sheet.classList.add("is-hidden");
    $$('[data-mtab]').forEach(button => button.classList.toggle('active', button.dataset.mtab === 'chat'));
  }

  async function showMemoryContextNotice() {
    const sid = state.session?.id;
    if (!sid) return;
    const generation = state.sourceGeneration = (state.sourceGeneration || 0) + 1;
    const notice = $("#m-chat-error");
    state.sourceReviewNotice = "记忆已更改：相关来源和未确认派生内容暂不提供给模型，其他来源仍可使用。可逐条审阅和确认。";
    notice.textContent = state.sourceReviewNotice;
    notice.classList.remove("is-hidden");
    try {
      const data = await api(`/api/session/${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid || state.sourceGeneration !== generation || data?.session?.id !== sid) return;
      state.context = data.context || null;
      state.memories = data.memories || [];
      state.bookmark = data.bookmark || null;
      renderAll();
      renderStarters();
      const sheet = $("#m-sheet");
      if (sheet?._xinjiKind === "understand") renderUnderstanding();
      if (sheet?._xinjiKind === "more") renderMobileSourceList();
    } catch (error) {
      if (state.session?.id === sid && state.sourceGeneration === generation) {
        notice.textContent = "记忆修改已保存，但相关来源状态未能同步；请重新打开记忆或刷新核对。草稿和对话仍保留。";
      }
    }
  }

  function memGroups() {
    const active = state.memories.filter((m) => m.status !== "deleted");
    return {
      fact: active.filter((m) => m.kind === "fact"),
      inference: active.filter((m) => m.kind === "inference"),
      question: active.filter((m) => m.kind === "question"),
    };
  }

  function memCard(m, tag) {
    const attached = m.source_attachment_id ? mobileSources().find(source => source.id === m.source_attachment_id) : null;
    const provenance = attached ? `${m.source || attached.label || "来源"} · ${mobileSourceTitle(attached)}` : m.source || "来源待补";
    const uncertainSource = /撤回后来源待核对|来源待核对/.test([m.source, m.source_label].filter(Boolean).join(" "));
    const status = m.status === "auto" ? (["用户手动添加", "对话原话 · 用户选存"].includes(m.source) ? "你已添加" : "自动记录") : m.status === "confirmed" ? "已确认" : m.status === "candidate" ? "尚未核实" : "状态待核对";
    const origin = m.kind === "inference" ? "推测" : m.source === "用户手动添加" ? "你手动添加" : m.source_attachment_id ? "来自你选定的资料" : /用户|原话|user|聊天/.test(m.source || "") ? "你的原话" : "来源见下方记录";
    const use = uncertainSource ? "来源待核对，暂不用于回复。" : m.kind === "inference" ? "这是推测，不作为确定事实。" : m.status === "auto" ? (["用户手动添加", "对话原话 · 用户选存"].includes(m.source) ? "你主动记下，可作为相关对话的背景。" : "自动记下；关闭自动记录后暂停用于回复，可确认或删除。") : m.status === "confirmed" ? "可作为相关对话的背景。" : "尚未核实，不作为确定事实。";
    return `<div class="mem-item" data-id="${m.id}">
      <div class="mem-kind">${tag} · v${m.version} · ${esc(provenance)}</div>
      <div class="memory-origin ${m.kind === "inference" ? "is-inference" : ""}">${esc(origin)}</div><div class="mem-text">${esc(m.text)}</div><p class="memory-use">${esc(use)}</p><details class="memory-details"><summary>来源与使用方式</summary><p>说于：原话的具体时间未记录。<br>记下于：${esc(m.created_at ? String(m.created_at).replace("T", " ") : "未记录")}<br>使用：${esc(use)} 可随时纠正或忘掉。</p></details>
      <div class="mem-meta">
        <span>${esc(status)}</span>
        <span>
          ${m.status === "auto" && m.source === "对话原话 · 自动记录" ? `<button class="mini" data-act="confirm" data-id="${m.id}">确认记住</button>` : ""}<button class="mini" data-act="edit" data-id="${m.id}">改一改</button>
          <button class="mini" data-act="history" data-id="${m.id}">历史</button>
          <button class="mini" data-act="delete" data-id="${m.id}">忘掉这条</button>
        </span>
      </div>
    </div>`;
  }

  function renderUnderstanding() {
    const g = memGroups();
    const insights = state.context?.insights || [];
    const insightSource = insight => {
      const source = mobileSources().find(item => item.id === insight.source_id);
      return source ? ` · ${esc(mobileSourceTitle(source))}` : "";
    };
    $("#m-sheet-body").innerHTML = `
      <button type="button" class="btn ghost wide" id="m-add-memory" ${state.memorySaving ? 'disabled' : ''}>手动记下</button>
      ${insights.length ? `<div class="section-label">洞察</div>${insights.map((i, idx) =>
        `<div class="m-insight"><div class="t">${esc((i.type || "").toUpperCase())}${insightSource(i)}</div><b>${esc(i.title)}</b><p>${esc(i.text)}</p>
          ${mobileInsightUsable(i) ? `<div class="m-actions" style="margin-top:6px">
            <button class="mini-btn" data-m-insight="${idx}" data-m-source-id="${esc(mobileInsightSourceId(i) || "")}">变成下一步</button>
            <button class="mini-btn" data-m-action="reminder" data-m-idx="${idx}">提醒</button>
            <button class="mini-btn" data-m-action="calendar" data-m-idx="${idx}">日历</button>
            <button class="mini-btn" data-m-action="message" data-m-idx="${idx}">消息</button>
          </div>` : `<p class="synthetic">相关来源待核对，暂不生成下一步或动作。</p>`}</div>`).join("")}` : ""}
      ${g.fact.length ? `<div class="section-label">事实</div>${g.fact.map((m) => memCard(m, "事实")).join("")}` : ""}
      ${g.inference.length ? `<div class="section-label">推测</div>${g.inference.map((m) => memCard(m, "推测")).join("")}` : ""}
      ${g.question.length ? `<div class="section-label">问题</div>${g.question.map((m) => memCard(m, "问题")).join("")}` : ""}
      <p class="synthetic">纠正任意一条会让下一步随之变化，并保留版本与来源。</p>`;
    $('#m-add-memory').onclick=addMobileMemoryPrompt;
  }

  let mobileManualMemoryOperation=null;
  async function addMobileMemoryPrompt() {
    const sid=state.session?.id, sheet=$('#m-sheet'), epoch=sheet?._xinjiEpoch;
    const generation=state.sourceGeneration || 0;
    const current=()=>state.session?.id===sid && sheet?._xinjiEpoch===epoch && sheet?._xinjiKind==='understand' && (state.sourceGeneration || 0)===generation;
    if (!sid || !current() || state.memorySaving || mobileManualMemoryOperation) return;
    const operation={}; mobileManualMemoryOperation=operation;
    let created=false;
    try {
      const text=await window.XinjiDialogs.prompt({title:'记下一件事',message:'记下后，你可以随时修改或忘掉。',maxLength:2000,confirmLabel:'记下'});
      if (!text?.trim() || !current()) return;
      state.memorySaving=true;
      const memory=await api('/api/memory',{method:'POST',body:JSON.stringify({session_id:sid,kind:'fact',text:text.trim(),source:'用户手动添加',user_asserted:true})});
      if (!memory?.id || memory.session_id!==sid || memory.status!=='auto') throw Error('新增记忆回执未确认，请重新打开记忆核对后再决定是否重试。');
      created=true;
      if (!current()) return;
      const snapshot=await api('/api/memory?session_id='+encodeURIComponent(sid));
      if (!current()) return;
      if (!Array.isArray(snapshot.memories) || !snapshot.memories.some(item=>item.id===memory.id && item.status==='auto')) throw Error('新增回执已收到，但暂时未能核对列表，请稍后重新打开记忆。');
      state.memories=snapshot.memories; renderUnderstanding(); toast('已记下，你可以随时修改或忘掉。');
    } catch(error) {
      if (current()) toast(created ? '新增回执已收到，列表暂时未能核对。请重新打开记忆查看。' : error.message);
    } finally {
      if (mobileManualMemoryOperation===operation) { mobileManualMemoryOperation=null; state.memorySaving=false; }
      if (current()) $('#m-add-memory').disabled=false;
    }
  }

  async function onMemAction(ev) {
    const btn = ev.target.closest("[data-act]");
    if (!btn || btn.disabled) return;
    const id = btn.dataset.id, act = btn.dataset.act, sid = state.session?.id;
    const sheet = $("#m-sheet"), epoch = sheet._xinjiEpoch;
    const current = () => state.session?.id === sid;
    const visible = () => current() && sheet._xinjiEpoch === epoch && sheet._xinjiKind === "understand";
    const item = state.memories.find(memory => memory.id === id);
    if (!sid || !item || !visible()) return;
    const snapshot = {...item};
    const drafts = onMemAction.drafts || (onMemAction.drafts = new Map());
    btn.disabled = true;
    state.memorySaving = true;
    try {
      if (act === "history") {
        const card = btn.closest(".mem-item"), old = card.querySelector(".mem-history");
        if (old) { old.remove(); return; }
        const data = await api(`/api/memory/${encodeURIComponent(id)}/history`);
        if (!visible() || card.isConnected === false || !state.memories.some(memory => memory.id === id)) return;
        card.insertAdjacentHTML("beforeend", `<div class="mem-history">${(data.revisions || []).map(revision => `<div class="mem-rev"><span>v${revision.version}</span><span>${esc(revision.text)}</span><span>${esc((revision.created_at || "").slice(11, 19))}</span></div>`).join("")}</div>`);
        return;
      }
      if (act === "delete") {
        if (!await window.XinjiDialogs.confirm({title: "忘掉这条记忆", message: "将移除这条记忆，相关来源和未确认派生内容会暂停用于回复。已独立修改的副本仍需分别核对。", confirmLabel: "忘掉这条", danger: true}) || !visible()) return;
        await window.XinjiMemorySync.remove(api, snapshot);
        if (!current()) return;
        drafts.delete(id);
        state.memories = state.memories.filter(memory => memory.id !== id);
        showMemoryContextNotice();
      } else if (act === "confirm" || act === "edit") {
        const draft = drafts.get(id) || {text:item.text, version:item.version};
        if (act === "edit" && draft.conflict) {
          if (!draft.latest) { toast("这条记忆已变更或移除。未保存的修改仍保留，请重新读取后核对。"); return; }
          if (!await window.XinjiDialogs.confirm({title:"核对最新的记忆", message:`已在别处更新为 v${draft.latest.version}：${draft.latest.text}。你的修改仍会预填进输入框。核对后采用此版本，再决定是否保存。`, confirmLabel:"核对后继续修改"}) || !visible()) return;
          draft.version = draft.latest.version; draft.conflict = false;
        }
        const text = act === "edit" ? await window.XinjiDialogs.prompt({title: "改一改这条记忆", message: "纠正后会留下版本记录。", value: draft.text, maxLength: 2000}) : null;
        if (act === "edit" && (text === null || !visible())) return;
        if (act === "edit") { draft.text = text; drafts.set(id, draft); }
        const updated = await window.XinjiMemorySync.patch(api, act === "edit" ? {id,version:draft.version} : snapshot, act === "confirm" ? {status: "confirmed"} : {text});
        if (!current()) return;
        drafts.delete(id);
        const target = state.memories.find(memory => memory.id === id);
        if (target) Object.assign(target, updated);
        if (act === "edit") showMemoryContextNotice();
      } else return;
      renderAll();
      if (visible()) { renderUnderstanding(); toast(act === "confirm" ? "已确认，版本 +1" : "已更新；相关来源暂不参与模型回复，请核对。 "); }
      loadNextStep();
    } catch (error) {
      if (!current()) return;
      if (window.XinjiMemorySync.isConflict(error)) {
        let latest = null;
        try {
          const data = await api(`/api/memory?session_id=${encodeURIComponent(sid)}`);
          if (!current()) return;
          latest = (data.memories || []).find(memory => memory.id === id) || null;
          if (latest) Object.assign(item, latest);
        } catch (_) {}
        const draft = drafts.get(id);
        if (draft) { draft.conflict = true; draft.latest = latest; }
        if (visible()) {
          renderUnderstanding();
          toast(act === "edit" ? "这条记忆已在别处更新。修改草稿已保留，再点「改一改」核对后继续。" : "这条记忆已在别处更新。请先核对最新内容，再决定是否操作。");
        }
      } else if (visible()) toast(error.message + (drafts.has(id) ? " 修改草稿已保留，再点「改一改」继续。" : ""));
    }
    finally { btn.disabled = false; state.memorySaving = false; }
  }

  function renderBookmark(presetNext = "") {
    state.mobileBookmarkSourceId = null;
    state.mobileBookmarkSessionId = state.session?.id;
    const b = state.bookmark;
    const body = $("#m-sheet-body");
    body.innerHTML = `
      ${b ? `<div class="bm-card">
        <p class="bm-note">${esc(b.note)}</p>
        <div class="bm-row"><b>取舍：</b>${esc(b.choice || "—")}</div>
        <div class="bm-row"><b>下一步：</b>${esc(b.next_step || "—")}</div>
        <div class="bm-receipt"><span>${b.status === "committed" ? "已保存 " + esc(b.receipt || "") : "草稿"}</span>
        ${b.status === "committed" ? "" : `<button class="mini confirm" id="m-bm-commit">确认保存</button>`}</div>
      </div>` : ""}
      <div class="section-label">${b ? "再标记一个" : "标记此刻"}</div>
      <textarea id="m-bm-note" rows="2" placeholder="停在了哪里">${b ? "" : ""}</textarea>
      <div style="height:8px"></div>
      <input class="m-input" id="m-bm-choice" placeholder="当时的取舍" style="width:100%;border:1px solid var(--line);border-radius:12px;padding:10px 12px;background:rgba(255,255,255,0.6);font-size:14px" />
      <div style="height:8px"></div>
      <input class="m-input" id="m-bm-next" value="${esc(presetNext)}" placeholder="下一步（可改）" style="width:100%;border:1px solid var(--line);border-radius:12px;padding:10px 12px;background:rgba(255,255,255,0.6);font-size:14px" />
      <div style="height:10px"></div>
      <button class="btn primary wide" id="m-bm-save">先存为草稿</button>
      <div class="section-label">提醒、日历与消息草稿</div>
      <div class="m-task-create"><button type="button" class="btn ghost small" id="m-new-message">新建消息草稿</button><button type="button" class="btn ghost small" id="m-new-reminder">新建提醒</button><button type="button" class="btn ghost small" id="m-new-calendar">新建日历安排</button></div>
      <p class="note">先编辑并确认。默认只保存在本机；写入系统需要你另行勾选。消息草稿不会自动发送。</p>
      <div id="m-task-actions"><p class="synthetic">正在读取已保存的动作…</p></div>`;
    if ($("#m-bm-commit")) $("#m-bm-commit").onclick = commitBookmark;
    $("#m-bm-save").onclick = saveBookmark;
    const sid = state.session?.id, sheet = $("#m-sheet"), epoch = sheet._xinjiEpoch;
    for (const kind of ["message", "reminder", "calendar"]) $("#m-new-" + kind).onclick = () => {
      if (state.session?.id === sid && sheet._xinjiEpoch === epoch) openMobileAction(kind, null, {title: "", text: ""});
    };
    loadMobileTaskActions();
  }

  async function loadMobileTaskActions() {
    const el = $("#m-task-actions");
    if (!el || !state.session) return;
    const sid = state.session.id, sheet = $("#m-sheet"), epoch = sheet._xinjiEpoch;
    const current = () => state.session?.id === sid && sheet._xinjiEpoch === epoch && $("#m-task-actions") === el;
    try {
      const data = await api(`/api/actions?session_id=${encodeURIComponent(sid)}`);
      if (!current()) return;
      const acts = data.actions || [];
      el.innerHTML = acts.length ? window.XinjiActionCards.html(acts, {interactive: true}) : `<p class="synthetic">还没有动作。可以用上面的按钮写一条。</p>`;
      window.XinjiActionCards.bind(el, acts, {
        onContinue: action => { if (current()) openMobileSavedAction(action); },
        onCheck: action => { if (current()) checkMobileSavedAction(action); },
      });
    } catch (error) { if (current()) el.innerHTML = `<p class="synthetic">暂时无法读取动作：${esc(error.message)}</p><button type="button" class="btn ghost small" id="m-task-retry">重新读取</button>`;
      if (current()) $("#m-task-retry").onclick = () => { if (current()) loadMobileTaskActions(); };
    }
  }

  function openMobileSavedAction(action) {
    if (!state.session || action.status !== "previewed" || (action.session_id && action.session_id !== state.session.id)) return;
    openMobileAction(action.kind, null, {title: action.title, text: action.detail || ""});
    mobileAction.existingId = action.id;
    mobileAction.when = action.when_text || "";
    mobileAction.fromSaved = true;
    $("#m-action-name").readOnly = true;
    $("#m-action-message").readOnly = true;
    $("#m-action-when").value = action.when_text || "";
    $("#m-action-when").disabled = true;
    $("#m-action-detail").textContent = "继续确认这条已保存的预览；将使用原内容与同一条记录，不会重复新建。要修改内容，可取消后新建一条。";
    if (action.kind === "calendar" && !action.when_text) {
      $("#m-action-real").disabled = true;
      $("#m-action-detail").textContent += " 未设时间，只能保存在本机，当前不能写入系统日历。";
    }
  }

  async function checkMobileSavedAction(action) {
    if (!state.session || !["unknown", "executing"].includes(action.status) || (action.session_id && action.session_id !== state.session.id)) return;
    const sid = state.session.id, sheet = $("#m-sheet"), epoch = sheet._xinjiEpoch;
    try {
      const data = await api(`/api/actions?session_id=${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid || sheet._xinjiEpoch !== epoch) return;
      const latest = (data.actions || []).find(item => item.id === action.id);
      toast(!latest ? "没有找到这条本机记录，请刷新任务核对。" : ["unknown", "executing"].includes(latest.status) ? "本机仍未确认结果；请先到系统提醒事项或日历核对，当前不会再次写入。" : "已重新读取本机记录，请查看最新状态。");
      loadMobileTaskActions();
    } catch (error) { if (state.session?.id === sid && sheet._xinjiEpoch === epoch) toast(`暂时无法核对：${error.message}`); }
  }

  async function saveBookmark() {
    const sid = state.session?.id, sourceId = state.mobileBookmarkSourceId;
    if (!sid || state.mobileBookmarkSessionId !== sid) { toast("对话已切换，请重新打开任务。"); return; }
    if (state.revokingSource || state.attachingSource || (sourceId && !mobileSources().some(source => source.id === sourceId))) {
      toast("这份来源已变化，请重新核对洞察后再保存。"); return;
    }
    const note = $("#m-bm-note").value.trim();
    if (!note) { toast("先写一句：停在了哪里"); return; }
    const sheet = $("#m-sheet"), epoch = sheet._xinjiEpoch;
    try {
      const bookmark = await api("/api/bookmark", { method: "POST", body: JSON.stringify({
        session_id: sid, note, ...(sourceId ? {source_attachment_id: sourceId} : {}),
        choice: $("#m-bm-choice").value.trim(),
        next_step: $("#m-bm-next").value.trim(),
      }) });
      if (state.session?.id !== sid) return;
      state.bookmark = bookmark;
      if (sheet._xinjiEpoch === epoch && ["tasks", "bookmark"].includes(sheet._xinjiKind)) {
        toast("已存为草稿"); renderBookmark();
      }
    } catch (e) { if (state.session?.id === sid && sheet._xinjiEpoch === epoch) toast(e.message); }
  }

  async function commitBookmark() {
    const bookmark = state.bookmark, sid = state.session?.id;
    if (!bookmark || !sid) return;
    const sheet = $("#m-sheet"), epoch = sheet._xinjiEpoch;
    try {
      const saved = await api(`/api/bookmark/${bookmark.id}/commit`, {method: "POST"});
      if (state.session?.id !== sid || state.bookmark?.id !== bookmark.id) return;
      state.bookmark = saved;
      if (sheet._xinjiEpoch === epoch && ["tasks", "bookmark"].includes(sheet._xinjiKind)) { renderBookmark(); toast("已保存 · 回执生成"); }
    } catch (error) { if (state.session?.id === sid && sheet._xinjiEpoch === epoch) toast(error.message); }
  }

  function mobileSources(context = state.context, session = state.session) {
    if (Array.isArray(context?.sources)) return context.sources.filter(source => source && typeof source === "object");
    if (context && (context.connector_id || (context.items || []).length)) {
      return [{id: null, connector_id: context.connector_id, label: session?.source_label || "原有来源",
        items: context.items || [], insights: context.insights || [], starters: context.starters || [], stale: !!context.stale}];
    }
    if (session && !session.source_revoked && ["connector", "paste"].includes(session.mode)) {
      return [{id: null, label: session.source_label || "原有来源", items: [], insights: [], starters: []}];
    }
    return [];
  }

  function mobileSourceTitle(source) {
    return source.title || source.items?.[0]?.title || source.label || "已连接资料";
  }

  function mobileInsightSourceId(insight) {
    const sources = mobileSources();
    return insight.sourceId || insight.source_id || insight.source_attachment_id || (sources.length === 1 ? sources[0].id : null);
  }

  function mobileInsightUsable(insight) {
    const sources = mobileSources(), sourceId = mobileInsightSourceId(insight);
    const source = sourceId ? sources.find(item => item.id === sourceId) : sources.length === 1 ? sources[0] : null;
    return sourceId ? !!source && !source.stale : !state.context?.stale && sources.length <= 1 && !source?.stale;
  }

  function openMobileInsightBookmark(insight, expectedSourceId = null) {
    const sourceId = mobileInsightSourceId(insight);
    if (!mobileInsightUsable(insight) || (expectedSourceId && sourceId !== expectedSourceId)) {
      toast("这份洞察的来源已移除或变化，或仍待核对；请重新打开记忆核对。"); return;
    }
    openSheet("bookmark");
    state.mobileBookmarkSourceId = sourceId;
    state.mobileBookmarkSessionId = state.session?.id;
    $("#m-bm-note").value = insight.title;
    $("#m-bm-choice").value = "来自洞察";
    $("#m-bm-next").value = insight.text;
  }

  function renderMobileSourceList(context = state.context, session = state.session) {
    const box = $("#m-connected-sources");
    if (!box) return;
    const sid = session?.id;
    const sources = mobileSources(context, session);
    box.innerHTML = `<div class="section-label">当前对话的来源 · ${sources.length}</div>` +
      (sources.map(source => `<div class="m-today-card"><div class="k">${esc(source.label || source.connector_id || "来源")}${source.stale ? " · 待核对" : ""}</div>
        <b>${esc(mobileSourceTitle(source))}</b><p>${(source.items || []).length} 条快照${source.items?.[0]?.summary ? " · " + esc(source.items[0].summary.slice(0, 100)) : ""}</p>
        <button type="button" class="text-btn" data-msource-remove="${esc(source.id || "")}" ${state.revokingSource ? "disabled" : ""}>移除这份来源</button></div>`).join("") ||
        (state.feishuAccount?.enabled === true && state.feishuAccount.ready !== false ? `<p class="synthetic">✓ 飞书已连接，聊天时会按需查阅。</p>` : `<p class="synthetic">还没有接入来源；可以先聊聊，再按需要添加。</p>`)) +
      `<button type="button" class="btn ghost wide" id="m-add-source" ${state.revokingSource ? "disabled" : ""}>继续连接资料</button>` +
      (sources.length ? `<button type="button" class="text-btn" id="m-revoke-all" ${state.revokingSource ? "disabled" : ""}>移除全部 ${sources.length} 份来源</button>` : "") +
      `<p class="synthetic">每份来源可单独移除；会停止本对话使用相应资料。历史消息、手动记忆和第三方授权仍保留。</p>`;
    box.querySelectorAll("[data-msource-remove]").forEach(button => {
      button.onclick = () => { if (state.session?.id === sid) revokeMobileSelectedSource(button.dataset.msourceRemove || null); };
    });
    $("#m-add-source")?.addEventListener("click", () => { if (state.session?.id === sid) { closeSheet(); showMobileOnboarding(); } });
    const all = $("#m-revoke-all");
    if (all) all.onclick = () => { if (state.session?.id === sid) revokeMobileSource(); };
  }

  async function revokeMobileSource() {
    return revokeMobileSelectedSource(null);
  }

  let mobileSourceMutation = null;
  function mobileSourceBusy() {
    return !!(state.attachingSource || state.revokingSource || state.confirmingSource ||
      (typeof mActiveTurn !== "undefined" && mActiveTurn) ||
      (typeof mQueuedTurns !== "undefined" && mQueuedTurns.length) ||
      (typeof mTurnQueue !== "undefined" && mTurnQueue.length) ||
      (typeof mUncertainTurns !== "undefined" && mUncertainTurns.has(state.session?.id)));
  }

  async function revokeMobileSelectedSource(sourceId = null) {
    if (!state.session) return;
    if (mobileSourceMutation || mobileSourceBusy()) { toast("消息或来源仍在处理中，请稍后再移除。"); return; }
    const selected = sourceId ? mobileSources().find(source => source.id === sourceId) : null;
    if (sourceId && !selected) { toast("这份来源已变化，请重新打开数据设置核对。"); return; }
    const description = selected ? `「${mobileSourceTitle(selected)}」` : "本对话全部来源";
    const sheet = $("#m-sheet"), sheetEpoch = sheet?._xinjiEpoch;
    const approvalSid = state.session.id;
    state.confirmingSource = true;
    let approved = false;
    try { approved = await window.XinjiDialogs.confirm({title: "收回资料", message: `将移除${description}及其派生记忆；其他来源、手动记忆和历史消息会保留。已独立修改的副本及第三方授权仍保留。`, confirmLabel: "移除所选资料", danger: true}); }
    finally { state.confirmingSource = false; }
    if (!approved || state.session?.id !== approvalSid || mobileSourceMutation || mobileSourceBusy()) return;
    if (sourceId && !mobileSources().some(source => source.id === sourceId)) { toast("资料已变化，请重新核对。"); return; }
    const sid = state.session.id;
    const operation = {};
    window.XinjiCompanionBoundary?.invalidate();
    mobileSourceMutation = operation;
    state.revokingSource = true;
    const generation = state.sourceGeneration = (state.sourceGeneration || 0) + 1;
    if (typeof clearMobileSourceForm === "function") clearMobileSourceForm();
    let revoked = false;
    try {
      const r = await api("/api/source/revoke", {method: "POST", body: JSON.stringify({session_id: sid, ...(sourceId ? {source_id: sourceId} : {})})});
      if (!r.ok) throw new Error(r.reason || "无法撤回来源");
      revoked = true;
      const data = await api(`/api/session/${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid || state.sourceGeneration !== generation) return;
      if (data?.session?.id !== sid) throw new Error("撤回后的对话状态不匹配");
      state.session = data.session;
      if (typeof updatePersonaLabels === "function") updatePersonaLabels();
      state.memories = data.memories || [];
      state.bookmark = data.bookmark || null;
      state.context = data.context || null;
      state.nextStep = null;
      renderAll();
      renderStarters();
      loadNextStep();
      toast(`已移除${selected ? "这份来源，" : "全部来源，"}清理 ${r.cleaned || 0} 条派生记忆`);
      if (r.review_required) {
        const notice = $("#m-chat-error");
        state.sourceReviewNotice = `另有 ${r.review_required} 条来源待核对的记忆或关联副本仍保存在对应对话，已暂停用于模型和自动建议。请在记忆中逐条核对、确认或删除；历史消息、书签和第三方授权需另行处理。`;
        notice.textContent = state.sourceReviewNotice;
        notice.classList.remove("is-hidden");
      }
    } catch (e) {
      if (state.session?.id !== sid || state.sourceGeneration !== generation) return;
      const notice = $("#m-chat-error");
      notice.textContent = revoked
        ? "来源已撤回，但界面未能同步。请先复制尚未发送的内容，再刷新页面核对。"
        : "未能确认撤回结果。请先复制尚未发送的内容，再刷新页面核对。";
      notice.classList.remove("is-hidden");
      toast(notice.textContent);
    } finally {
      if (mobileSourceMutation === operation) {
        mobileSourceMutation = null;
        state.revokingSource = false;
        if (state.session?.id === sid && sheet?._xinjiEpoch === sheetEpoch && typeof renderMobileSourceList === "function") {
          renderMobileSourceList();
          const label = $("#m-data-source-label");
          if (label) label.textContent = `${mobileSources().length} 份来源`;
        }
      }
    }
  }

  async function renderMore() {
    const sid = state.session?.id;
    if (!sid) return;
    const sheet = $("#m-sheet"), epoch = sheet._xinjiEpoch, generation = state.sourceGeneration || 0;
    const body = $("#m-sheet-body");
    body.innerHTML = `<p class="synthetic">正在读取当前对话的数据…</p>`;
    let sess = null, acts = [], warning = "";
    const results = await Promise.allSettled([
      api(`/api/session/${encodeURIComponent(sid)}`),
      api(`/api/actions?session_id=${encodeURIComponent(sid)}`)
    ]);
    if (state.session?.id !== sid || sheet._xinjiEpoch !== epoch || (state.sourceGeneration || 0) !== generation) return;
    if (results[0].status === "fulfilled" && results[0].value?.session?.id === sid) sess = results[0].value;
    else warning = "当前来源状态未能同步。移除后会重新核对服务器状态；不会清空你的对话或草稿。";
    if (results[1].status === "fulfilled") acts = results[1].value.actions || [];
    if (sess) {
      state.session = sess.session;
      state.memories = sess.memories || [];
      state.bookmark = sess.bookmark || null;
      state.context = sess.context || null;
    }
    const mems = state.memories || [], ctx = state.context || {}, sources = mobileSources();
    body.innerHTML = `
      ${warning ? `<p class="synthetic" role="status">${esc(warning)}</p>` : ""}
      <div class="m-data">
        <div class="m-data-row"><span>本次来源</span><b id="m-data-source-label">${sources.length} 份来源</b></div>
        <div class="m-data-row"><span>读取 / 洞察</span><b>${(ctx.items || []).length} / ${(ctx.insights || []).length}</b></div>
        <div class="m-data-row"><span>记忆</span><b>${mems.length} 条</b></div>
        <div class="m-data-row"><span>动作</span><b>${acts.length} 条</b></div>
      </div>
      <div id="m-connected-sources"></div>
      <button type="button" class="btn ghost wide" id="m-manage-connect">连接新的资料</button><div style="height:10px"></div>
      <button class="btn ghost wide" id="m-export">导出本次数据</button>
      <p class="synthetic">这里一直保留着你和回响的对话。资料可逐份移除，记忆可核对或删除。</p>`;
    renderMobileSourceList();
    $("#m-manage-connect").onclick = () => { if (state.session?.id === sid && sheet._xinjiEpoch === epoch) { closeSheet(); showMobileOnboarding(); } };
    $("#m-export").onclick = async () => {
      const d = await api(`/api/export?session_id=${encodeURIComponent(sid)}`);
      if (state.session?.id !== sid) return;
      const blob = new Blob([JSON.stringify(d, null, 2)], {type: "application/json"});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `xinji-data-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    };
  }

  async function openMobileHistory(targetSid) {
    if (!targetSid || !state.session) return;
    if (mobileDeletingHistory.has(targetSid)) { toast("这次历史对话正在删除，请稍后核对。"); return; }
    if (mobileSourceBusy()) { toast("消息或来源仍在处理中，请先完成核对再切换对话。"); return; }
    const originSid = state.session.id, sheet = $("#m-sheet"), sheetEpoch = sheet._xinjiEpoch;
    const requestId = state.mobileHistoryRequest = (state.mobileHistoryRequest || 0) + 1;
    clearMobileSourceForm();
    try {
      const data = await api(`/api/session/${encodeURIComponent(targetSid)}`);
      if (state.mobileHistoryRequest !== requestId || state.session?.id !== originSid || sheet._xinjiEpoch !== sheetEpoch) return;
      if (data?.session?.id !== targetSid) throw Error("返回的对话不匹配");
      enterSessionData(data);
      closeSheet();
    } catch (error) {
      if (state.mobileHistoryRequest === requestId && state.session?.id === originSid && sheet._xinjiEpoch === sheetEpoch) toast(`无法恢复对话：${error.message}`);
    }
  }

  const mobileDeletingHistory = new Set();
  async function deleteMobileHistory(targetSid, button) {
    if (!targetSid || mobileDeletingHistory.has(targetSid)) return;
    if (mobileSourceBusy()) { toast("消息或来源仍在处理中，请稍后删除。"); return; }
    if (!confirm("删除这次对话？消息、记忆、历史、书签、动作与审计都会移除。")) return;
    const originSid = state.session?.id, sheet = $("#m-sheet"), sheetEpoch = sheet._xinjiEpoch;
    state.mobileHistoryRequest = (state.mobileHistoryRequest || 0) + 1;
    mobileDeletingHistory.add(targetSid);
    if (button) button.disabled = true;
    try {
      await api(`/api/session/${encodeURIComponent(targetSid)}`, {method: "DELETE"});
      typeof mood !== "undefined" && mood?.clearSession(targetSid);
      if (state.mobileDrafts) delete state.mobileDrafts[targetSid];
      if (state.session?.id === targetSid) {
        localStorage.removeItem("xinji_session");
        location.reload();
      } else if (state.session?.id === originSid && sheet._xinjiEpoch === sheetEpoch) {
        toast("已删除历史对话");
        await renderMore();
      }
    } catch (error) {
      if (state.session?.id === originSid && sheet._xinjiEpoch === sheetEpoch) toast("未能确认删除结果，请重新打开历史核对。");
    } finally { mobileDeletingHistory.delete(targetSid); }
  }

  // ---------- chat ----------
  let recog = null, recogListening = false;
  let memes = [];
  let mTurnQueue = [], mTurnTimer = null, mQueuedTurns = [], mActiveTurn = null;
  let mChatBlocked = false, mLocalTurnId = 0;
  let mChatStorageBlocked = false;
  const mUncertainTurns = new Map();
  const mChatLedger = window.XinjiChatTransport.createLedger('h5');
  const mChatTransport = window.XinjiChatTransport.create(api, {ledger:mChatLedger});
  const mDisplayedTurns = new Map();

  function cancelPending() {
    if (state.delivery?.pending()) { void state.delivery?.stop(); return; }
    if (!mActiveTurn?.transport) return;
    mChatTransport.cancel(mActiveTurn.transport);
    $("#m-stop")?.classList.add("is-hidden");
    toast("正在停止这次回复，已发送的话会保留。模型请求可能仍在完成。");
  }

  async function recoverMobileChat() {
    const turn=mUncertainTurns.get(state.session?.id);
    if (!turn || state.session?.id!==turn.sessionId) return;
    const button=$("#m-chat-recover"); button.disabled=true;
    try {
      const result=await mChatTransport.recover(turn.transport);
      if(state.session?.id!==turn.sessionId) return;
      state.messages=[...result.messages.flatMap(m=>mDisplayedTurns.get(m.id)||[m]),...mPendingMessages(turn.sessionId)];
      state.memories=result.memories;
      mUncertainTurns.delete(turn.sessionId); mChatBlocked=mUncertainTurns.size>0;
      button.classList.add("is-hidden"); $("#m-chat-error").classList.add("is-hidden");
      renderAll(); dispatchSend();
    } catch(error) {
      if(error.uncertain && ['process_interrupted','execution_uncertain'].includes(error.code)) {
        const snapshot=await api('/api/session/'+encodeURIComponent(turn.sessionId));
        if(state.session?.id!==turn.sessionId) return;
        state.messages=[...snapshot.messages,...mPendingMessages(turn.sessionId)]; state.memories=snapshot.memories;
        const restored=[turn.transport.text,...mPendingMessages(turn.sessionId).map(p=>p.text),$("#m-input").value].filter(Boolean).join("\n");
        mChatLedger.returnDraft(turn.sessionId,restored,turn.transport.request_id);
        mQueuedTurns=mQueuedTurns.filter(item=>item.sessionId!==turn.sessionId);
        mTurnQueue=mTurnQueue.filter(item=>item.sessionId!==turn.sessionId);
        $("#m-input").value=restored; window.XinjiComposerDraft?.save();
        mUncertainTurns.delete(turn.sessionId); mChatBlocked=mUncertainTurns.size>0; button.classList.add("is-hidden"); renderAll();
        $("#m-chat-error").textContent="上次回复结果未确认，已重新读取记录。原文放回输入框，请核对是否已保存再决定发送；没有自动重发。";
        $("#m-chat-error").classList.remove('is-hidden');
        dispatchSend();
      } else toast(error.message);
    } finally { button.disabled=false; }
  }

  function setupVoice() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const btn = $("#m-mic");
    if (!SR) { btn.classList.add("is-hidden"); return; }
    recog = new SR();
    recog.lang = "zh-CN";
    recog.interimResults = true;
    recog.continuous = false;
    recog.onresult = (e) => {
      let text = "";
      for (let i = e.resultIndex; i < e.results.length; i++) text += e.results[i][0].transcript;
      $("#m-input").value = text.trim();
    };
    recog.onstart = () => {
      recogListening = true; window.NianxiangSound?.setRecording(true); btn.classList.add("listening"); btn.textContent = "在听…";
    };
    recog.onend = () => {
      recogListening = false; window.NianxiangSound?.setRecording(false); btn.classList.remove("listening"); btn.textContent = "语音";
      const t = $("#m-input").value.trim();
      if (t) send(t);
    };
    recog.onerror = () => { recogListening = false; window.NianxiangSound?.setRecording(false); btn.classList.remove("listening"); btn.textContent = "语音"; toast("语音识别失败，可改用文字"); };
    btn.onclick = () => { if (recogListening) recog.stop(); else { try { recog.start(); } catch (_) {} } };
  }

  function mPendingMessages(sessionId) {
    return [...mQueuedTurns.flatMap((turn) => turn.sessionId === sessionId ? turn.parts : []),
      ...mTurnQueue.filter((part) => part.sessionId === sessionId)];
  }

  function restoreMobileChatLedger() {
    if (!state.session) return;
    try {
      const saved=mChatLedger.restore(state.session.id, $('#m-input').value);
      $('#m-input').value=saved.draft;
      window.XinjiComposerDraft?.save();
      for (const record of saved.pending) {
        mUncertainTurns.set(record.session_id,{sessionId:record.session_id,parts:record.parts,transport:record});
      }
      mChatBlocked=mUncertainTurns.size>0;
      if (saved.pending.length || saved.restored) {
        $('#m-chat-error').textContent=saved.pending.length
          ? '上次发送状态待核对；原请求已保存在本机。点击「核对发送状态」只读取结果，不会重新发送。'
          : '刚才尚未发出的内容已放回输入框，由你决定是否发送。';
        $('#m-chat-error').classList.remove('is-hidden');
        $('#m-chat-recover')?.classList.toggle('is-hidden',!saved.pending.length);
      }
    } catch(error) { mChatStorageBlocked=true; toast(error.message); }
  }

  function keepMobileChatDraft() {
    window.XinjiComposerDraft?.save();
    if (state.session) try { mChatLedger.saveDraft(state.session.id,$('#m-input').value); } catch(_) { /* Sending fails closed. */ }
  }

  function mIsStandaloneCommand(text) {
    const s = text.trim();
    return s.includes("记住") || ["继续", "继续吧", "安静", "安静一会儿", "停下", "不用了", "别说了"].includes(s)
      || ["继续上次", "回到上次", "上次的书签", "回到书签", "别安排", "不用提醒"].some((word) => s.includes(word));
  }

  function send(text) {
    const clean = text.trim();
    if (!clean || !state.session) return;
    if (mChatStorageBlocked) { toast('本机发送记录未能保存。请先复制输入内容，检查存储后重新打开页面。'); return; }
    if (state.attachingSource || state.revokingSource) { toast("正在更新来源，请稍后发送。"); return; }
    if (mUncertainTurns.has(state.session.id)) { $("#m-chat-recover").classList.remove("is-hidden"); toast("这次发送状态待核对，请点击「核对发送状态」。"); return; }
    window.XinjiCompanionBoundary?.invalidate();
    if (state.delivery?.pending()) void state.delivery?.stop();
    const part = { id: `local-${++mLocalTurnId}`, role: "user", text: clean, sessionId: state.session.id };
    part.id='local-'+mChatTransport.requestId();
    if(window.XinjiContactContract?.supported(state.companionBoundary?.capabilities())) part.time_zone=window.XinjiContactContract.timeZone();
    try { mChatLedger.enqueue(part); }
    catch(error) { toast(error.message); return; }
    if (mActiveTurn?.sessionId === part.sessionId && mActiveTurn.transport) mChatTransport.cancel(mActiveTurn.transport);
    mTurnQueue.push(part);
    window.NianxiangSound?.play("send");
    state.messages.push(part);
    renderMessages(true);
    $("#m-input").value = "";
    window.XinjiComposerDraft?.save();
    $("#m-input").style.height = "auto";
    clearTimeout(mTurnTimer);
    mTurnTimer = setTimeout(() => {
      for (const part of mTurnQueue) {
        const last = mQueuedTurns[mQueuedTurns.length - 1];
        const standalone = mIsStandaloneCommand(part.text);
        if (last && last.sessionId === part.sessionId && !last.started && !last.standalone && !standalone && last.timeZone === part.time_zone) last.parts.push(part);
        else mQueuedTurns.push({ sessionId: part.sessionId, parts: [part], standalone, timeZone:part.time_zone });
      }
      mTurnQueue = [];
      mTurnTimer = null;
      dispatchSend();
    }, 850);
  }

  async function dispatchSend() {
    if (mActiveTurn || !mQueuedTurns.length) return;
    const next=mQueuedTurns.findIndex(turn=>!mUncertainTurns.has(turn.sessionId));
    if(next<0) return;
    const turn=mQueuedTurns.splice(next,1)[0];
    turn.started = true;
    mActiveTurn = turn;
    globalThis.XinjiMobilePresence?.("thinking");
    const sameSession = () => state.session?.id === turn.sessionId;
    const previousAssistantIds = new Set(state.messages.filter(message => message.role === "assistant").map(message => message.id));
    if (sameSession()) $("#m-stop")?.classList.remove("is-hidden");
    try {
      turn.transport ||= {session_id:turn.sessionId, text:turn.parts.map(p=>p.text).join("\n"), memory_proposals:false, ...(typeof turn.timeZone === "string" ? {time_zone:turn.timeZone} : {})};
      const d = await mChatTransport.send(turn.transport, message => {
        if (sameSession()) { $("#m-chat-error").textContent=message; $("#m-chat-error").classList.remove("is-hidden"); }
      },turn.parts);
      if (sameSession()) $("#m-chat-recover")?.classList.add("is-hidden");
      const userMessage = d.messages.find((m) => m.id === d.user_message_id);
      if (userMessage && turn.parts.length > 1) mDisplayedTurns.set(userMessage.id, turn.parts);
      if (sameSession()) {
        // Delayed delivery is announced by chat-delivery; immediate replies are announced after rendering,
        // so the sound controller can see whether this reply will be read aloud.
        const completedReply = !d.cancelled && !d.error && [...d.messages].reverse().find(message => message.role === "assistant" && !message.delivery_pending && !previousAssistantIds.has(message.id));
        state.messages = [...d.messages.flatMap((m) => mDisplayedTurns.get(m.id) || [m]), ...mPendingMessages(turn.sessionId)];
        state.memories = d.memories;
        renderAll();
        if (completedReply) window.NianxiangSound?.play("receive", {messageId: completedReply.id});
        loadNextStep();
      }
    } catch (e) {
      if (e.notSent && sameSession()) {
        window.NianxiangSound?.play("gentleError");
        const waiting = [...turn.parts, ...mPendingMessages(turn.sessionId)];
        const ids = new Set(waiting.map((part) => part.id));
        mQueuedTurns = mQueuedTurns.filter((item) => item.sessionId !== turn.sessionId);
        mTurnQueue = mTurnQueue.filter((item) => item.sessionId !== turn.sessionId);
        state.messages = state.messages.filter((item) => !ids.has(item.id));
        const input = $("#m-input");
        input.value = [...waiting.map((part) => part.text), input.value.trim()].filter(Boolean).join("\n");
        try { mChatLedger.returnDraft(turn.sessionId,input.value,turn.transport?.request_id); }
        catch(_) { mChatStorageBlocked=true; }
        window.XinjiComposerDraft?.save();
        renderMessages();
        $("#m-chat-error").textContent = `${e.message}。本条未发送，内容已放回输入框。请先复制保存，再检查服务或本机存储。`;
        $("#m-chat-error").classList.remove("is-hidden");
        toast("本条未发送，内容已放回输入框。");
      } else {
        mChatBlocked = true;
        mUncertainTurns.set(turn.sessionId, turn);
        if (sameSession()) { $("#m-chat-error").textContent="发送结果尚未确认，原请求和待发内容已保存在本机。核对后可继续。"; $("#m-chat-error").classList.remove("is-hidden"); $("#m-chat-recover")?.classList.remove("is-hidden"); }
        if (sameSession()) toast("发送结果尚未确认，请点击「核对发送状态」。");
      }
    } finally {
      mActiveTurn = null;
      if (sameSession()) void state.companionBoundary?.refresh();
      globalThis.XinjiMobilePresence?.("quiet");
      if (sameSession()) state.delivery?.schedule();
      dispatchSend();
    }
  }

  // ---------- boot ----------
  function bind() {
    mountMobileCompanions();
    $$("[data-m-entry]").forEach(button => button.addEventListener("click", () => openMobileEntry(button.dataset.mEntry, button)));
    $$("[data-m-rokid-close]").forEach(button => button.addEventListener("click", closeMobileRokid));
    $("#m-rokid-outline")?.addEventListener("cancel", event => { event.preventDefault(); closeMobileRokid(); });
    window.addEventListener("pagehide", clearMobileSourceForm);
    window.addEventListener("storage", renderMobilePendingNotice);
    renderMobilePendingNotice();
    $("#m-source-uncertain-history")?.addEventListener("click", () => openSheet("more"));
    $("#m-source-uncertain-dismiss")?.addEventListener("click", dismissMobilePendingNotice);
    $("#m-back-1")?.addEventListener("click", () => showWz(1));
    $("#m-onboarding-return")?.addEventListener("click", () => closeMobileWizard());
    $("#m-skip")?.addEventListener("click", () => closeMobileWizard());
    $("#m-open-connect")?.addEventListener("click", showMobileOnboarding);
    $("#m-composer-connect")?.addEventListener("click", showMobileOnboarding);
    $("#m-skip-connect")?.addEventListener("click", () => $("#m-chat-empty")?.classList.add("is-hidden"));
    $("#m-chat-empty")?.querySelectorAll("[data-prompt]").forEach((b) => b.onclick = () => window.XinjiCompanionChoices.put($("#m-input"), b.dataset.prompt));
    $("#m-back-2").onclick = showMobileOnboarding;
    $("#m-read-btn").onclick = () => readMobileConfirmedSource();
    $("#m-wz-start").onclick = () => startMobileReal();
    $("#m-wz-edit").onclick = () => startMobileReal(true);
    setupVoice();
    loadPluginsMobile();
    $("#m-meme")?.addEventListener("click", () => $("#m-meme-modal").classList.remove("is-hidden"));
    $("#m-meme-close")?.addEventListener("click", () => $("#m-meme-modal").classList.add("is-hidden"));
    $$("[data-mtab]").forEach((b) => {
      b.onclick = () => {
        $$("[data-mtab]").forEach((x) => x.classList.toggle("active", x === b));
        if (b.dataset.mtab === "chat") { closeSheet(); return; }
        openSheet(b.dataset.mtab);
        $("#m-sheet").classList.add("navigation-sheet");
      };
    });
    $("#m-stop")?.addEventListener("click", cancelPending);
    $("#m-chat-recover")?.addEventListener("click", () => recoverMobileChat().catch(e=>toast(e.message)));
    $("#m-action-cancel").onclick = closeMobileAction;
    $("#m-action-confirm").onclick = confirmMobileAction;
    $("#m-composer").addEventListener("submit", (e) => { e.preventDefault(); send($("#m-input").value); });
    $("#m-input").addEventListener("input", (e) => {
      e.target.style.height = "auto";
      e.target.style.height = Math.min(120, e.target.scrollHeight) + "px";
    });
    $$(".quick").forEach((b) => (b.onclick = () => openSheet(b.dataset.sheet)));
    $$("[data-close]").forEach((b) => (b.onclick = closeSheet));
    document.addEventListener("click", onMemAction);
    $("#m-auth-cancel")?.addEventListener("click", closeLarkAuthMobile);
    document.addEventListener("click", (ev) => {
      const a = ev.target.closest("[data-m-action]");
      if (a) { openMobileAction(a.dataset.mAction, Number(a.dataset.mIdx)); return; }
      const b = ev.target.closest("[data-m-insight]");
      if (!b) return;
      const ins = (state.context?.insights || [])[Number(b.dataset.mInsight)];
      if (!ins) return;
      openMobileInsightBookmark(ins, b.dataset.mSourceId || null);
    });
  }

  function showRestoreFailure() {
    const box = document.createElement("section");
    box.className = "restore-error";
    box.setAttribute("role", "alert");
    box.innerHTML = '<h2>暂时没能连上回响</h2><p>聊天记录仍保存在本机。请检查服务连接后重试。</p><button class="btn primary" type="button">重试</button>';
    box.querySelector("button").onclick = () => location.reload();
    document.body.appendChild(box);
  }

  async function restore() {
    try {
      const data = await api("/api/conversation");
      if (!data?.session?.id) throw Error("对话暂时未能读取");
      enterSessionData(data);
      return true;
    } catch (error) {
      showRestoreFailure();
      return false;
    }
  }

  async function showMobileOnboarding() {
    clearMobileSourceForm();
    mobileOpeningEntry++;
    wz.directEntry = false;
    openMobileWizard();
    wz.realSource = null;
    wz.pendingSource = null;
    showWz(2);
    $("#m-wz2-sub").textContent = "飞书可连接账号，聊天时按问题自动查阅。其他资料由你选择并确认，可同时接入多个来源并逐份移除；刚才聊过的话会一直保留。";
    $("#m-skip").textContent = state.session ? "返回当前对话" : "先直接聊聊";
    await loadRealSources();
  }

  function renderDesignSettingsMobile() {
    const body = $("#m-sheet-body");
    body.innerHTML = `<div class="design-shortcuts"><button type="button" class="btn ghost" id="m-settings-connect">连接应用</button><button type="button" class="btn ghost" id="m-settings-tasks">任务与草稿</button><button type="button" class="btn ghost" id="m-settings-data">资料与记录</button></div><div id="m-design-preferences"></div><div id="m-auto-memory-settings"></div><div id="m-sound-settings"></div><details class="m-today-card" id="m-settings-persona"><summary>伙伴角色</summary><p>虚构角色不写入你的事实；切换伙伴不会影响已确认的记忆。</p><button type="button" class="btn ghost small" id="m-settings-choose-persona">选择聊天伙伴</button></details><details class="m-today-card" id="m-settings-devices"><summary>设备</summary><div id="m-paired-devices"></div><div class="m-today-card"><div class="k">脑电设备</div><b>请在设备所在电脑开启</b><p>当前读取只支持连接 MindLink 服务的本机；手机远程接入仍待联调。</p></div><div class="m-today-card"><div class="k">Rokid 眼镜</div><b>规划中</b><p>将用于查看用户选择的简短提示；型号、连接方式和真机显示待联调。</p></div></details>`;
    window.XinjiDesign.mountSettings($("#m-design-preferences"));
    window.XinjiAutoMemorySettings?.mount($("#m-auto-memory-settings"), {api, getSessionId: () => state.session?.id});
    window.NianxiangSound?.mount($("#m-sound-settings"));
    const settingsEpoch = $("#m-sheet")._xinjiEpoch;
    pairedDevicesPanel = window.XinjiPairedDevices?.mount($("#m-paired-devices"), {api, getSessionId:() => state.session?.id, visible:() => $("#m-sheet")._xinjiKind === "settings" && $("#m-sheet")._xinjiEpoch === settingsEpoch});
    $("#m-settings-connect").onclick = showMobileOnboarding;
    $("#m-settings-tasks").onclick = () => openSheet("tasks");
    $("#m-settings-choose-persona").onclick = () => {
      closeSheet();
      const heading = document.querySelector(".conversation-persona h2");
      heading?.focus();
      heading?.click();
    };
    $("#m-settings-data").onclick = () => openSheet("more");
  }

  function setupMobileDesign() {
    if (!window.XinjiDesign) return;
    if (/Android/i.test(navigator.userAgent)) document.documentElement.dataset.platform = "android";
    $$("[data-design-light]").forEach(element => element.innerHTML = window.XinjiDesign.lightMarkup);
    window.XinjiMobileWorkspace = window.XinjiDesign.createWorkspace({getState: () => state, backgrounds: [$("#m-app"), $("#m-sheet")], fallbackFocus: () => $("#m-input"), onJump: item => {
      if (item.type === "memory") openSheet("understand"); else closeSheet();
      const root = item.type === "memory" ? $("#m-sheet-body") : $("#m-messages");
      const match = [...root.querySelectorAll(item.type === "memory" ? "[data-id]" : "[data-message-id]")].find(element => (element.dataset.id || element.dataset.messageId) === item.id);
      if (match) { match.setAttribute("tabindex", "-1"); match.focus({preventScroll:true}); match.scrollIntoView({block:"center",behavior:"auto"}); }
    }});
    window.XinjiMobileWorkspace.mountTopics($("#m-design-topics"));
    document.addEventListener("xinji-topic-change", () => window.XinjiMobileWorkspace.filterMessages($("#m-messages")));
    $("#m-design-search").onclick = () => { globalThis.XinjiVoice?.stop?.(); window.XinjiMobileWorkspace.openSearch(); };
    $("#m-design-settings").onclick = () => openSheet("settings");
    window.XinjiMobilePresence = status => { document.documentElement.dataset.presenceState = status; const label = $("#m-design-state"); if (label) label.textContent = {thinking:"正在生成回复",input:"在听你输入",quiet:"安静陪着"}[status] || "安静陪着"; };
    $("#m-input").addEventListener("input", () => window.XinjiMobilePresence($("#m-input").value ? "input" : "quiet"));
    const alignHeader = () => document.documentElement.style.setProperty("--design-header-bottom", `${$(".m-top").getBoundingClientRect().bottom + 8}px`);
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(alignHeader).observe($(".m-top"));
    document.documentElement.dataset.presenceState = "quiet";
  }

  async function boot() {
    bind();
    setupMobileDesign();
    window.XinjiComposerDraft = window.XinjiForegroundSync.draft($("#m-input"), "h5");
    const params = new URLSearchParams(location.search);
    const ready = await restore();
    if (ready) { restoreMobileChatLedger(); connectionIntro.resume(); }
    $('#m-input').addEventListener('input',keepMobileChatDraft);
    window.addEventListener('pagehide',() => {keepMobileChatDraft(); connectionIntro.stop();});
    document.addEventListener('visibilitychange',()=>{ if(document.hidden) keepMobileChatDraft(); });
    if (ready && params.has("onboarding")) await showMobileOnboarding();
    let reviewedSheet = null;
    const sheetMayRefresh = () => {
      const sheet = $('#m-sheet');
      return sheet?.classList.contains('is-hidden') || (reviewedSheet && reviewedSheet.id === state.session?.id &&
        reviewedSheet.epoch === sheet?._xinjiEpoch && sheet?._xinjiKind === 'understand');
    };
    const canRefresh = () => !!state.session && !document.hidden && !mActiveTurn && !state.delivery?.pending() && !mTurnQueue.length && !mQueuedTurns.length && !mChatBlocked && !contentMutationCount && !state.attachingSource && !state.revokingSource && !state.confirmingSource && !state.memorySaving && !mobileManualMemoryOperation && !(onMemAction.drafts?.size) && followups.canRefresh() && mood?.canRefresh() !== false && state.companionBoundary?.canRefresh() !== false && sheetMayRefresh() && !document.querySelector('dialog[open], [aria-modal="true"]:not(.is-hidden)');
    const refreshReviewedMemory = () => {
      const sheet = $('#m-sheet');
      if (!reviewedSheet || reviewedSheet.id !== state.session?.id || reviewedSheet.epoch !== sheet?._xinjiEpoch || sheet?._xinjiKind !== 'understand') return;
      const body = $('#m-sheet-body'), scroll = body.scrollTop;
      renderUnderstanding(); body.scrollTop = scroll;
    };
    let legacyReadFailed = false;
    const legacyRefresh = window.XinjiForegroundSync.create({canRefresh,version:()=>`${state.sourceGeneration}:${contentMutationEpoch}`,read:()=>api('/api/conversation'),onFailure:()=>{legacyReadFailed=true;showUpdate('offline');},apply:data=>{
      if(data.session?.id!==state.session?.id)return;
      state.session=data.session;state.messages=data.messages;state.memories=data.memories;state.bookmark=data.bookmark;state.context=data.context||null;
      renderAll();renderStarters();
      refreshReviewedMemory();
    }});
    let updates;
    let manualCheck = null;
    const checkUpdates = () => {
      if (manualCheck) return manualCheck;
      const sheet = $('#m-sheet');
      const review = !sheet.classList.contains('is-hidden') && sheet._xinjiKind === 'understand'
        ? {id:state.session?.id, epoch:sheet._xinjiEpoch} : null;
      reviewedSheet = review;
      manualCheck = (async () => {
        try {
          if (updates?.state().supported === false) {
            legacyReadFailed = false;
            const refreshed = await legacyRefresh();
            if (refreshed) showUpdate('updated');
            else if (!legacyReadFailed) showUpdate('pending');
            return refreshed;
          }
          return await updates?.checkNow();
        } finally { if (reviewedSheet === review) reviewedSheet = null; manualCheck = null; }
      })();
      return manualCheck;
    };
    const showUpdate=window.XinjiContentUpdates.mountStatuses(document.querySelectorAll('[data-content-update]'),checkUpdates);
    updates=window.XinjiContentUpdates.create({api,identity:()=>state.session?.id,
      revision:()=>`${state.sourceGeneration}:${contentMutationEpoch}:${$('#m-sheet')?._xinjiEpoch}`,canApply:canRefresh,
      read:(_changes,get)=>window.XinjiContentUpdates.snapshot(state.session.id,get,{today:true}),
      apply:snapshot=>{
        const data=snapshot.conversation;if(data.session?.id!==state.session?.id||!canRefresh())return false;
        state.sourceGeneration=(state.sourceGeneration||0)+1;
        state.delivery?.invalidateReads();
        state.nextStep=snapshot.next;
        state.session=data.session;state.messages=data.messages;state.memories=data.memories;state.bookmark=data.bookmark;state.context=data.context||null;
        renderMessages();renderStarters();renderNext();
        state.companionBoundary?.acceptSnapshot(snapshot.boundary);
        refreshReviewedMemory();
        return true;
      },onState:showUpdate});
    updates.start();
    window.addEventListener('focus',()=>updates.visibilityChanged());
    document.addEventListener('visibilitychange',()=>updates.visibilityChanged());
    window.addEventListener('pagehide',()=>updates.stop());
    window.addEventListener('pageshow',event=>{if(event.persisted)updates.start();});
  }

  boot();
})();

