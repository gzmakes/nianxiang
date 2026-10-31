/* The preference belongs to the active conversation and is enforced by the server. */
(() => {
  'use strict';
  function mount(host, {api, getSessionId}) {
    if (!host) return;
    const sid = getSessionId();
    host.innerHTML = `<details class="settings-section" open><summary>自动记录记忆</summary><p class="note">默认关闭。开启后，本对话中符合规则的原话会自动保存到本地记忆，相关内容可能随对话发送给当前模型服务（可能在云端）。识别可能出错，请随时查看、修改或删除。</p><p class="note">关闭后停止新增自动记录，之前未确认的自动记录不会作为记忆用于回复；原对话仍保留。手动记住和已确认的记忆不受影响。</p><label><input type="checkbox" data-auto-memory disabled> 在本对话开启自动记录</label><p role="status" data-auto-memory-status></p></details>`;
    const toggle = host.querySelector('[data-auto-memory]');
    const status = host.querySelector('[data-auto-memory-status]');
    if (!sid) { status.textContent = '开始对话后可设置。'; return; }
    const url = `/api/session/${encodeURIComponent(sid)}/auto-memory`;
    const live = () => host.isConnected && getSessionId() === sid;
    (async () => {
      try {
        const data = await api(url);
        if (!live()) return;
        toggle.checked = data.enabled === true; toggle.disabled = false;
        status.textContent = toggle.checked ? '已开启' : '已关闭';
      } catch (_) { if (live()) status.textContent = '无法读取设置，请重新打开后重试。'; }
    })();
    toggle.addEventListener('change', async () => {
      const target = toggle.checked;
      toggle.disabled = true; status.textContent = '正在保存…';
      try {
        const data = await api(url, {method:'PUT', body:JSON.stringify({enabled:target})});
        if (!live()) return;
        toggle.checked = data.enabled === true;
        status.textContent = toggle.checked ? '已开启' : '已关闭';
      } catch (_) {
        if (!live()) return;
        toggle.checked = !target;
        status.textContent = '未能确认保存，请重新打开设置核对。';
      } finally { if (live()) toggle.disabled = false; }
    });
  }
  window.XinjiAutoMemorySettings = {mount};
})();
