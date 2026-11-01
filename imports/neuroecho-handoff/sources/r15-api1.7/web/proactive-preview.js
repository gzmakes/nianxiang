(function () {
  'use strict';

  const mounted = new WeakMap();
  function mount(root) {
    if (!root) return null;
    if (mounted.has(root)) return mounted.get(root);
    root.dataset.previewMounted = 'true';
    const area = root.querySelector('[data-preview-card]');
    let ownsGuide = false;
    function close() {
      if (ownsGuide) window.NianxiangSound?.stopGuide();
      ownsGuide = false;
      area.hidden = true;
      root.hidden = true;
      area.replaceChildren();
    }
    function syncGuide() {
      if (area.hidden) return;
      const state = window.NianxiangSound?.getState();
      const status = area.querySelector('[data-guide-status]');
      const start = area.querySelector('[data-guide-start]');
      const pause = area.querySelector('[data-guide-pause]');
      const end = area.querySelector('[data-guide-end]');
      if (!status || !start || !pause || !end) return;
      const active = !!(ownsGuide && state?.guiding);
      start.hidden = active && !state.guidePaused;
      start.textContent = active && state.guidePaused ? '继续呼吸' : '一起呼吸';
      pause.hidden = !active || state.guidePaused;
      end.hidden = !active;
      status.textContent = !active ? '' : state.error || (state.guidePaused ? '已暂停，准备好再继续。' : state.blocked ? '声音暂时无法播放，结束安静模式或回到页面后继续。' : state.guideMuted ? '引导已静音，按舒服的节奏来。' : '按舒服的节奏来，随时可以暂停。');
    }
    function show(payload) {
      if (!payload || typeof payload.title !== 'string' || typeof payload.message !== 'string' ||
          !payload.title.trim() || !payload.message.trim() || payload.title.length > 160 || payload.message.length > 2000) return false;
      if (ownsGuide) window.NianxiangSound?.stopGuide();
      ownsGuide = false;
      root.hidden = false;
      area.hidden = false;
      area.className = 'preview-card preview-card--proactive';
      area.innerHTML = '<div class="preview-card-top"><span class="preview-card-kicker"><span aria-hidden="true">✦</span> 主动提醒</span><button type="button" class="preview-card-close" aria-label="关闭提醒">×</button></div>' +
        '<h3 data-reminder-title></h3><p data-reminder-message></p>' +
        '<div class="preview-options" role="group" aria-label="选择回应">' +
        '<button type="button" class="preview-option" data-guide-start>一起呼吸</button>' +
        '<button type="button" class="preview-option" data-guide-pause hidden>暂停</button>' +
        '<button type="button" class="preview-option" data-guide-end hidden>结束</button>' +
        '<button type="button" class="preview-option" data-guide-dismiss>先不用</button></div>' +
        '<p class="preview-guide-status" data-guide-status role="status" aria-live="polite"></p>';
      area.querySelector('[data-reminder-title]').textContent = payload.title.trim();
      area.querySelector('[data-reminder-message]').textContent = payload.message.trim();
      if (payload.allowBreathing !== true) {
        area.querySelector('[data-guide-start]').hidden = true;
        area.querySelector('[data-guide-pause]').hidden = true;
        area.querySelector('[data-guide-end]').hidden = true;
      }
      area.querySelector('.preview-card-close').addEventListener('click', close);
      area.querySelector('[data-guide-dismiss]').addEventListener('click', close);
      area.querySelector('[data-guide-start]').addEventListener('click', function () {
        if (!window.NianxiangSound?.startGuide) {
          area.querySelector('[data-guide-status]').textContent = '呼吸引导暂时不可用，请稍后再试。';
          return;
        }
        ownsGuide = true;
        window.NianxiangSound.startGuide();
        syncGuide();
      });
      area.querySelector('[data-guide-pause]').addEventListener('click', function () { window.NianxiangSound?.pauseGuide(); syncGuide(); });
      area.querySelector('[data-guide-end]').addEventListener('click', function () { window.NianxiangSound?.stopGuide(); ownsGuide = false; syncGuide(); });
      if (payload.allowBreathing === true) syncGuide();
      return true;
    }
    window.addEventListener('nianxiang-sound-change', function () {
      if (!area.querySelector('[data-guide-start]')?.hidden || ownsGuide) syncGuide();
    });
    const controller = {show, close};
    mounted.set(root, controller);
    return controller;
  }
  function start() { document.querySelectorAll('[data-proactive-preview]').forEach(mount); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
  window.XinjiProactivePreview = { mount: mount };
}());
