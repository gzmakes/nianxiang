/* 对话栏右侧入口（2026-10-31，产品要求）：搜索 / 记录心情 / 展开面板，替代原来这条线上的陪伴开关。
   三个按钮只转发到已有的入口：搜索弹层、右侧面板开关、面板「回响」页里的心情记录卡；不新增状态。 */
(() => {
  const root = document.documentElement;
  const host = document.querySelector('#app [data-conversation-tools]');
  if (!host) return;
  const $ = selector => document.querySelector(selector);
  const reducedMotion = () => root.dataset.reduceMotion === 'true' || (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  const panelOpen = () => root.dataset.panelCollapsed !== 'true';
  const panelButton = host.querySelector('[data-tool=panel]');
  // 胶囊只显示图标：悬停提示沿用各按钮的 aria-label。
  for (const button of host.querySelectorAll('[data-tool]')) if (!button.title) button.title = button.getAttribute('aria-label') || '';

  function syncPanel() {
    const open = panelOpen();
    panelButton.setAttribute('aria-expanded', String(open));
    const label = panelButton.querySelector('[data-tool-panel-label]');
    if (label) label.textContent = open ? '收起面板' : '展开面板';
    panelButton.title = open ? '收起面板' : '展开面板';
  }
  new MutationObserver(syncPanel).observe(root, { attributes: true, attributeFilter: ['data-panel-collapsed'] });
  syncPanel();

  function waitFor(find, limit = 1500) {
    return new Promise(resolve => {
      const start = performance.now();
      (function tick() {
        const found = find();
        if (found) return resolve(found);
        if (performance.now() - start > limit) return resolve(null);
        requestAnimationFrame(tick);
      })();
    });
  }

  host.querySelector('[data-tool=search]').onclick = () => $('#design-search-btn')?.click();
  // 首页和设置共用音效包的播放状态；暂时阻塞不改变用户的开关选择。
  const musicButton = host.querySelector('[data-tool=music]');
  const musicNotice = document.createElement('div');
  musicNotice.className = 'toast';
  musicNotice.setAttribute('role', 'status');
  musicNotice.setAttribute('aria-live', 'polite');
  document.body.appendChild(musicNotice);
  let noticeTimer, lastMusicError = '';
  function showMusicNotice(message) {
    musicNotice.textContent = message;
    musicNotice.classList.add('show');
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => musicNotice.classList.remove('show'), 4500);
  }
  function syncMusic(event) {
    const state = event?.detail || window.NianxiangSound?.getState?.();
    const enabled = !!(state?.active ?? state?.music);
    musicButton.setAttribute('aria-pressed', String(enabled));
    const label = musicButton.querySelector('[data-tool-music-label]');
    if (label) label.textContent = enabled ? '暂停音乐' : '播放音乐';
    musicButton.title = enabled ? '暂停音乐' : '播放音乐';
    if (state?.error && state.error !== lastMusicError) showMusicNotice(state.error);
    lastMusicError = state?.error || '';
  }
  if (musicButton) {
    musicButton.onclick = () => {
      if (!window.NianxiangSound?.toggleMusic) {
        showMusicNotice('音乐暂时不可用，请刷新页面后重试。');
        return;
      }
      try {
        const state = window.NianxiangSound.toggleMusic();
        syncMusic({detail: state});
        if (state?.active && state.blocked) showMusicNotice('当前声音已暂时暂停，结束语音或不打扰后会继续。');
      } catch (_) { showMusicNotice('暂时无法播放，请检查设备声音后重试。'); }
    };
    window.addEventListener('nianxiang-sound-change', syncMusic);
    syncMusic();
  }
  panelButton.onclick = () => $('#design-panel-toggle')?.click();
  host.querySelector('[data-tool=mood]').onclick = async () => {
    if (!panelOpen()) $('#design-panel-toggle')?.click();
    const tab = $('#design-context .tab[data-tab=today]');
    if (tab && !tab.classList.contains('active')) tab.click();
    const open = await waitFor(() => $('#today-mood [data-mood-open]'));
    if (!open) return;
    const panel = $('#today-mood [data-mood-panel]');
    if (panel?.hidden && !open.disabled) open.click();
    $('#today-mood .mood-card')?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
    open.focus?.({ preventScroll: true });
  };
})();
