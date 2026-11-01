/* Account access is opt-in. Opening this view only reads the current setting. */
(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  function documentURL(value) {
    if (typeof value !== 'string' || value.length > 4096 || value.trim() !== value) return null;
    try {
      const url = new URL(value);
      const host = url.hostname.toLowerCase();
      return url.protocol === 'https:' && !url.username && !url.password && (!url.port || url.port === '443') &&
        /^(?:[a-z0-9-]+\.)*(?:feishu\.cn|larksuite\.com)$/.test(host) &&
        /^\/(?:docx|docs|wiki)\/[A-Za-z0-9_-]+(?:\/)?$/.test(url.pathname) ? url.href : null;
    } catch (_) { return null; }
  }
  function isMemoryCitation(item) {
    return item && !item.kind && typeof item.id === 'string' && item.id.length > 0 &&
      Number.isSafeInteger(item.version) && item.version > 0;
  }
  function statusLabel(data) {
    return data?.enabled === true ? data.ready === false ? '连接需核对' : '✓ 已连接' : '待连接';
  }
  function syncBadges(root, data) {
    root.querySelectorAll('[data-feishu-account-status]').forEach(node => { node.textContent = statusLabel(data); node.classList?.toggle('is-connected', data?.enabled === true && data.ready !== false); });
    root.querySelectorAll('[data-feishu-account-control]').forEach(node => { node.textContent = data?.enabled === true ? '管理连接' : '连接'; });
  }
  function renderCitations(message, {includeMemories = true} = {}) {
    if (message?.role !== 'assistant' || message.delivery_pending || !Array.isArray(message.citations)) return '';
    return message.citations.map(item => {
      if (item?.kind === 'feishu_document') {
        const url = documentURL(item.url);
        return url ? `<a class="cite" href="${escape(url)}" target="_blank" rel="noopener noreferrer" title="打开本次实际查阅的飞书文档">查阅 · ${escape(item.title || '飞书文档')}</a>` : '';
      }
      return includeMemories && isMemoryCitation(item)
        ? `<button class="cite" data-mem="${escape(item.id)}" title="${escape(item.text)}">依据 · v${item.version} · ${escape(String(item.text || '').slice(0, 10))}…</button>` : '';
    }).join('');
  }

  function mount(container, {api, ensureSession, getSessionId, isCurrent, onAuthorize, onSingleDocument, onManageSources, onStateChange, onConnected, onReturn}) {
    container.innerHTML = `<div class="connection-card">
      <div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">${window.XinjiDeviceConnections?.sourceIcon("feishu", "飞") || "飞"}</span><h3>连接飞书</h3></div>
      <p class="connection-scope">只读你有权访问的文档，首次最多查看最近 7 天的 3 篇，之后按问题查阅；相关片段可能发送给当前模型。</p>
      <p class="connection-status feishu-account-status" role="status" aria-live="polite">正在核对连接状态…</p>
      <div class="lark-actions"><button type="button" class="btn primary small feishu-account-connect" disabled>授权</button>
      <button type="button" class="btn primary small feishu-account-authorize is-hidden">授权</button>
      <button type="button" class="btn primary small feishu-account-disconnect is-hidden">取消授权</button>
      <button type="button" class="btn ghost small feishu-account-refresh is-hidden">重试</button></div>
      <p class="connection-scope feishu-account-disconnect-note is-hidden">停止本对话自动查阅，已保存资料保留；飞书授权需在飞书中撤销。</p>
      </div>`;
    const $ = selector => container.querySelector(selector);
    const status = $('.feishu-account-status'), connect = $('.feishu-account-connect'), disconnect = $('.feishu-account-disconnect');
    const authorize = $('.feishu-account-authorize'), refresh = $('.feishu-account-refresh'), disconnectNote = $('.feishu-account-disconnect-note');
    let epoch = 0, busy = false, sessionId = null, verified = false, disposed = false;
    const current = version => !disposed && version === epoch && container.isConnected && isCurrent() && (!sessionId || getSessionId() === sessionId);
    const show = (element, visible) => element.classList.toggle('is-hidden', !visible);
    function apply(data) {
      if (typeof data?.enabled !== 'boolean') throw Error('未取得有效连接状态，请重新核对。');
      const connected = data.enabled && data.ready !== false;
      verified = true;
      status.classList.toggle('is-connected', connected);
      status.textContent = connected ? '✓ 已连接' : data.enabled
        ? '连接需核对，请重新授权。' : '授权后，就可以一起聊聊。';
      if (!connected && (data.error || data.hint)) status.textContent += ' ' + [data.error, data.hint].filter(Boolean).join(' · ');
      connect.textContent = '授权';
      connect.disabled = connected;
      show(connect, !connected); show(disconnect, data.enabled); show(disconnectNote, data.enabled);
      show(refresh, false); show(authorize, false);
      onStateChange?.(data);
    }
    async function identify(version) {
      const id = getSessionId() || await ensureSession();
      if (!current(version)) return null;
      if (typeof id !== 'string' || !id) throw Error('暂时无法读取当前对话，请刷新后重试。');
      sessionId = id;
      return id;
    }
    async function load() {
      if (busy || !current(epoch)) return;
      busy = true; const version = ++epoch; verified = false; status.classList.remove('is-connected'); connect.disabled = true; refresh.disabled = true;
      show(authorize, false); show(refresh, false); status.textContent = '正在核对连接状态…';
      try {
        const id = await identify(version); if (!id) return;
        const data = await api(`/api/lark/account?session_id=${encodeURIComponent(id)}`);
        if (current(version)) apply(data);
      } catch (error) { if (current(version)) { status.textContent = `连接状态尚未确认：${error.message}`; show(refresh, true); } }
      finally { if (current(version)) { busy = false; refresh.disabled = false; } }
    }
    async function change(enable) {
      if (busy || !current(epoch) || (enable && connect.disabled)) return;
      busy = true; const version = ++epoch; connect.disabled = true; disconnect.disabled = true; refresh.disabled = true; show(authorize, false);
      status.textContent = enable ? '正在核验真实搜索与文档读取权限…' : '正在断开自动检索…';
      try {
        const id = await identify(version); if (!id) return;
        const data = await api('/api/lark/account/' + (enable ? 'connect' : 'disconnect'), {method:'POST', body:JSON.stringify({session_id:id, ...(enable ? {start_intro:true} : {})})});
        if (!current(version)) return;
        if (data?.ok !== true) {
          if (enable && data?.permission_issue !== 'user_grant') globalThis.NianxiangSound?.play('gentleError');
          verified = false;
          status.textContent = [data?.error || '连接未完成', data?.hint].filter(Boolean).join(' · ');
          connect.disabled = false;
          if (data?.permission_issue === 'user_grant') {
            // The first explicit authorization click covers the official grant and verified enablement.
            busy = false; onAuthorize();
          }
          return;
        }
        if (data.enabled !== enable) throw Error('返回的连接设置不匹配');
        apply(data);
        if (enable) onConnected?.(data);
        else status.textContent = '已停止本对话自动查阅；已保存资料保留。飞书授权需在飞书中撤销。';
      } catch (error) {
        if (current(version)) { verified = false; status.textContent = `操作结果尚未确认：${error.message} 请重试检查状态。`; show(refresh, true); }
      } finally { if (current(version)) { busy = false; disconnect.disabled = false; refresh.disabled = false; } }
    }
    connect.onclick = () => change(true); disconnect.onclick = () => change(false); refresh.onclick = load;
    authorize.onclick = () => { if (!busy && current(epoch) && !authorize.classList.contains('is-hidden')) onAuthorize(); };
    void load();
    return {refresh: load, isVerified: () => verified, dispose: () => { disposed = true; epoch++; }};
  }
  window.XinjiFeishuAccountPicker = {mount, renderCitations, documentURL, isMemoryCitation, statusLabel, syncBadges};
})();
