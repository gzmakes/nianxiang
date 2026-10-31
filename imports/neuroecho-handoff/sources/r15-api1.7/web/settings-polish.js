/* 设置页补充（2026-10-31，产品要求）：
   1) 「伙伴角色」里直接列出 念响 / 小鲸鱼 两个选项（当前的打勾），点了就切换（走 persona-switch.js 的 switchTo）；
   2) 「自动记录记忆」：勾选框挪到最上面，两段说明压成一句短话；样式在 design-system.css。
   这两块都是别的模块渲染的 DOM：挂上后补一次，重新渲染时再补一次；每一步都是幂等的，不会和观察器打转。 */
(() => {
  const personas = () => window.XinjiSpaces?.PERSONAS || { nianxiang: { name: '念响' }, whale: { name: '小鲸鱼' } };
  // 勾选在上，说明只留一句（约 20 字）。
  const SHORT = '开启后自动把原话记到本地，可随时修改或删除。';

  function personaOptions() {
    const details = document.querySelector('#app #settings-persona');
    if (!details) return;
    let list = details.querySelector('.settings-persona-options');
    if (!list) {
      list = document.createElement('div');
      list.className = 'settings-persona-options'; list.setAttribute('role', 'radiogroup'); list.setAttribute('aria-label', '聊天伙伴');
      list.innerHTML = Object.entries(personas()).map(([key, item]) =>
        `<button type="button" role="radio" aria-checked="false" data-settings-persona="${key}"><span class="persona-dot" data-persona-dot="${key}" aria-hidden="true"></span><span>${item.name}</span></button>`).join('');
      (details.querySelector('.note') || details.querySelector('summary')).insertAdjacentElement('afterend', list);
      list.addEventListener('click', event => {
        const button = event.target.closest('[data-settings-persona]');
        if (!button || !window.XinjiSpaces) return;
        const mode = window.XinjiSpaces.current().split(':')[1];
        window.XinjiSpaces.switchTo(`${button.dataset.settingsPersona}:${mode}`);
      });
    }
    const current = window.XinjiSpaces?.current?.().split(':')[0] || document.documentElement.dataset.persona;
    for (const button of list.querySelectorAll('[data-settings-persona]')) {
      const checked = String(button.dataset.settingsPersona === current);
      if (button.getAttribute('aria-checked') !== checked) button.setAttribute('aria-checked', checked);
    }
  }

  function shortenAutoMemory() {
    const details = document.querySelector('#app #auto-memory-settings details');
    if (!details) return;
    const notes = details.querySelectorAll(':scope > p.note');
    if (notes.length > 1) for (const note of [...notes].slice(1)) note.remove();
    if (notes[0] && notes[0].textContent !== SHORT) notes[0].textContent = SHORT;
    const summary = details.querySelector(':scope > summary'), label = details.querySelector(':scope > label');
    if (summary && label && summary.nextElementSibling !== label) summary.insertAdjacentElement('afterend', label);
  }

  function run() { personaOptions(); shortenAutoMemory(); }
  function start() {
    const tab = document.querySelector('#app #tab-design');
    if (!tab) return;
    new MutationObserver(run).observe(tab, { childList: true, subtree: true });
    new MutationObserver(personaOptions).observe(document.documentElement, { attributes: true, attributeFilter: ['data-persona'] });
    run();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
