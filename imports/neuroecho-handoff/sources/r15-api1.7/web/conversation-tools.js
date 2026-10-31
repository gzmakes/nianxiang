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
  // 背景音乐：ambient-music.js 用 WebAudio 现场合成，没有音频文件；按钮只负责开关和显示状态。
  const musicButton = host.querySelector('[data-tool=music]');
  function syncMusic() {
    const playing = !!window.XinjiAmbientMusic?.playing?.();
    musicButton.setAttribute('aria-pressed', String(playing));
    const label = musicButton.querySelector('[data-tool-music-label]');
    if (label) label.textContent = playing ? '暂停音乐' : '播放音乐';
    musicButton.title = playing ? '暂停音乐' : '播放音乐';
  }
  if (musicButton) {
    musicButton.onclick = async () => { await window.XinjiAmbientMusic?.toggle?.(); syncMusic(); };
    document.addEventListener('xinji-ambient-music', syncMusic);
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
