/* Local CLI login panel. Login never imports data or starts a chat. */
(() => {
  const hosts = {github: ['github.com'], notion: ['notion.so', 'www.notion.so', 'notion.com', 'www.notion.com'], gmail: ['accounts.google.com']};
  function safeUrl(provider, value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password &&
        (!url.port || url.port === '443') && hosts[provider]?.includes(url.hostname) ? value : '';
    } catch (_) { return ''; }
  }
  function mount(host, provider) {
    if (!host || !hosts[provider]) return;
    const panel = document.createElement('div');
    panel.className = 'connector-login-panel';
    panel.innerHTML = '<button type="button" class="btn ghost small">连接账号</button><p class="note" role="status" aria-live="polite"></p><a class="is-hidden" target="_blank" rel="noopener noreferrer">打开官方登录页面</a><p class="note is-hidden"></p><p class="note">登录在运行念响服务的这台电脑上完成；关闭窗口不会撤销已发起的授权。登录后仍需选择资料、预览并确认接入。</p>';
    host.append(panel);
    const button = panel.querySelector('button'), status = panel.querySelector('[role=status]');
    const link = panel.querySelector('a'), code = link.nextElementSibling;
    let generation = 0;
    const current = id => id === generation && panel.isConnected && !panel.closest('.is-hidden');
    async function request(path, method = 'GET') {
      const response = await fetch(path, {method, credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) throw Error('连接服务暂不可用，请重试。');
      return response.json();
    }
    function show(data) {
      status.textContent = data.message || '正在准备连接…';
      const url = safeUrl(provider, data.url);
      link.classList.toggle('is-hidden', !url);
      if (url) link.href = url; else link.removeAttribute('href');
      code.classList.toggle('is-hidden', !data.code);
      code.textContent = data.code ? `请在 GitHub 输入一次性设备码：${data.code}` : '';
    }
    button.onclick = async () => {
      const id = ++generation;
      button.disabled = true;
      link.classList.add('is-hidden'); code.classList.add('is-hidden');
      status.textContent = '正在准备连接…';
      const deadline = Date.now() + 610000;
      try {
        let data = await request(`/api/connector-auth/${provider}/start`, 'POST');
        while (current(id)) {
          show(data);
          if (!['starting', 'pending'].includes(data.status)) break;
          if (Date.now() > deadline) throw Error('本次等待已结束，请重新连接。');
          await new Promise(resolve => setTimeout(resolve, 1500));
          if (!current(id)) return;
          data = await request(`/api/connector-auth/${provider}/status`);
        }
      } catch (error) { if (current(id)) status.textContent = error.message; }
      finally { if (panel.isConnected && generation === id) button.disabled = false; }
    };
    return panel;
  }
  globalThis.XinjiConnectorAuth = {mount, safeUrl};
})();
