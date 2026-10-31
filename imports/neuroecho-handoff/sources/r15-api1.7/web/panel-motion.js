/* 右侧面板的点击反馈（2026-10-31，产品要求）：页签下有一条会滑动的白色底、按钮点击处有一圈涟漪。
   只是视觉反馈，不改任何状态；开了「减少动态」或系统偏好减少动态时不做。 */
(() => {
  const root = document.documentElement;
  const reducedMotion = () => root.dataset.reduceMotion === 'true' || (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);

  // 页签滑块：跟着 .tab.active 走；布局变了（字号、面板宽）也跟着对齐。
  let indicator = null, tabs = null;
  function placeIndicator() {
    if (!tabs || !indicator) return;
    const active = tabs.querySelector('.tab.active');
    if (!active) { indicator.style.opacity = '0'; return; }
    const box = tabs.getBoundingClientRect(), target = active.getBoundingClientRect();
    indicator.style.opacity = '1';
    indicator.style.transform = `translateX(${Math.round(target.left - box.left)}px)`;
    indicator.style.width = `${Math.round(target.width)}px`;
    indicator.style.height = `${Math.round(target.height)}px`;
    indicator.style.top = `${Math.round(target.top - box.top)}px`;
  }
  function mountIndicator() {
    tabs = document.querySelector('#app .context .tabs');
    if (!tabs || indicator) return;
    indicator = document.createElement('span');
    indicator.className = 'tab-indicator'; indicator.setAttribute('aria-hidden', 'true');
    tabs.prepend(indicator);
    tabs.classList.add('has-indicator');
    placeIndicator();
    new MutationObserver(placeIndicator).observe(tabs, { attributes: true, subtree: true, attributeFilter: ['class'] });
    if (typeof ResizeObserver === 'function') new ResizeObserver(placeIndicator).observe(tabs);
    window.addEventListener('resize', placeIndicator);
    if (document.fonts?.ready) document.fonts.ready.then(placeIndicator);
  }

  // 涟漪：从按下的位置向外扩一圈，0.5 秒后自己消失。
  document.addEventListener('pointerdown', event => {
    if (reducedMotion() || event.button !== 0) return;
    const button = event.target.closest('#app .context button, #app .context .btn, #app .context summary');
    if (!button || button.disabled || button.classList.contains('tab')) return;
    const rect = button.getBoundingClientRect(), size = Math.max(rect.width, rect.height) * 2;
    const ripple = document.createElement('span');
    ripple.className = 'click-ripple'; ripple.setAttribute('aria-hidden', 'true');
    ripple.style.cssText = `width:${size}px;height:${size}px;left:${event.clientX - rect.left - size / 2}px;top:${event.clientY - rect.top - size / 2}px`;
    button.classList.add('has-ripple');
    button.appendChild(ripple);
    setTimeout(() => ripple.remove(), 550);
  }, { passive: true });

  // 面板切入：只在页签刚切换时给内容一次淡入，之后刷新进来的内容不再闪。
  function watchPanels() {
    const panels = document.querySelectorAll('#app .context .tab-panel');
    const timers = new WeakMap();
    for (const panel of panels) {
      let wasHidden = panel.classList.contains('is-hidden');
      new MutationObserver(() => {
        const hidden = panel.classList.contains('is-hidden');
        if (wasHidden && !hidden && !reducedMotion()) {
          panel.classList.add('is-entering');
          clearTimeout(timers.get(panel));
          timers.set(panel, setTimeout(() => panel.classList.remove('is-entering'), 600));
        }
        wasHidden = hidden;
      }).observe(panel, { attributes: true, attributeFilter: ['class'] });
    }
  }
  function start() { mountIndicator(); watchPanels(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
