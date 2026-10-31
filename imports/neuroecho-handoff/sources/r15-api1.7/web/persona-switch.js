/* 人格切换：服务端同步当前人格，本地只保留人格选择与兼容迁移数据。 */
(() => {
  const root = document.documentElement;
  const PERSONAS = {
    nianxiang: { name: '念响', hello: '属于你的一小段空白' },
    whale: { name: '小鲸鱼', hello: '小鲸鱼在这儿' },
  };
  const DEFAULT = 'nianxiang';
  const STORE = 'xinji_space_v1';
  let syncToken = 0;

  function normalizePersona(value) {
    if (typeof value !== 'string') return null;
    // Older releases stored values such as `nianxiang:companion`.
    const id = value.split(':', 1)[0];
    return PERSONAS[id] ? id : null;
  }

  function read() {
    try {
      const value = JSON.parse(localStorage.getItem(STORE));
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch (_) {
      return {};
    }
  }

  function write(value) {
    try { localStorage.setItem(STORE, JSON.stringify(value)); } catch (_) {}
  }

  const saved = read();
  let current = normalizePersona(saved.current) || DEFAULT;
  // Keep the old per-message view map readable, but remove the retired mode
  // suffix (`nianxiang:companion` -> `nianxiang`). Unknown values are dropped.
  const views = {};
  if (saved.views && typeof saved.views === 'object' && !Array.isArray(saved.views)) {
    for (const [id, value] of Object.entries(saved.views)) {
      const persona = normalizePersona(value);
      if (id && persona) views[id] = persona;
    }
  }

  const persist = () => {
    const keys = Object.keys(views);
    if (keys.length > 4000) {
      for (const key of keys.slice(0, keys.length - 4000)) delete views[key];
    }
    write({ ...saved, current, views });
  };

  // Rewrite legacy `persona:mode` values once on load. This is intentionally
  // limited to the switcher's own key and leaves unrelated local settings
  // untouched.
  persist();

  async function syncSession(nextPersona) {
    const token = ++syncToken;
    const sid = localStorage.getItem('xinji_session');
    if (!sid) return token === syncToken;
    try {
      const response = await fetch(`/api/session/${encodeURIComponent(sid)}/persona`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona_id: nextPersona }),
      });
      // Older services may not have the endpoint. The local switch remains
      // usable, while the app shows a non-blocking connection notice.
      if (response.status === 404 || response.status === 405) {
        throw new Error('服务还没更新到支持人格同步，这次先只在本机切换');
      }
      if (!response.ok) throw new Error('当前人格还没有同步到服务端，这次先只在本机切换');
      return token === syncToken;
    } catch (error) {
      document.dispatchEvent(new CustomEvent('xinji-space-sync-error', { detail: { error } }));
      return false;
    }
  }

  async function hydrateFromServer() {
    let sid = localStorage.getItem('xinji_session');
    try {
      // app.js restores the canonical conversation asynchronously. If this
      // script starts first, bootstrap from the same endpoint instead of
      // leaving the switcher pointed at stale local state.
      const response = sid
        ? await fetch(`/api/session/${encodeURIComponent(sid)}`)
        : await fetch('/api/conversation');
      if (!response.ok) return;
      const data = await response.json();
      sid = data?.session?.id || sid;
      if (sid) localStorage.setItem('xinji_session', sid);
      const serverPersona = normalizePersona(data?.session?.persona_id);
      if (serverPersona) {
        current = serverPersona;
        persist();
        root.dataset.persona = serverPersona;
      }
    } catch (_) {
      // The main app shows its normal connection error if the session is unavailable.
    }
  }

  root.dataset.persona = current;

  let menu = null;
  function renderHeading() {
    const heading = document.querySelector('.conversation-persona h2');
    if (!heading) return;
    heading.textContent = PERSONAS[current].name;
    heading.classList.add('persona-name');
    if (!heading.hasAttribute('tabindex')) {
      heading.setAttribute('tabindex', '0');
      heading.setAttribute('role', 'button');
      heading.setAttribute('aria-haspopup', 'menu');
      heading.setAttribute('title', '切换人格');
    }
    heading.setAttribute('aria-expanded', String(!!menu && !menu.hidden));
    const hello = document.querySelector('.chat-hello');
    if (hello) hello.textContent = PERSONAS[current].hello;
    for (const button of document.querySelectorAll('.persona-menu [data-space-persona]')) {
      button.setAttribute('aria-checked', String(button.dataset.spacePersona === current));
    }
  }

  async function switchTo(nextPersona) {
    nextPersona = normalizePersona(nextPersona);
    if (!nextPersona || nextPersona === current) return;
    // Waiting for the last request prevents an older click from overwriting a
    // newer choice. A failed sync still leaves the local UI usable.
    const token = syncToken + 1;
    await syncSession(nextPersona);
    if (token !== syncToken) return;
    current = nextPersona;
    persist();
    root.dataset.persona = current;
    closeMenu();
    renderHeading();
    document.querySelector('#app #composer textarea, #m-app #m-input')?.focus();
  }

  function closeMenu() {
    if (menu) menu.hidden = true;
    renderHeading();
  }

  function openMenu() {
    if (!menu) return;
    menu.hidden = false;
    renderHeading();
    menu.querySelector('[aria-checked="true"]')?.focus();
  }

  function mountMenu() {
    const container = document.querySelector('.conversation-persona');
    const heading = container?.querySelector('h2');
    if (!container || !heading || menu) return;
    menu = document.createElement('div');
    menu.className = 'persona-menu';
    menu.hidden = true;
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', '选择人格');
    menu.innerHTML = Object.entries(PERSONAS)
      .map(([key, item]) => `<button type="button" role="menuitemradio" data-space-persona="${key}" aria-checked="false"><span class="persona-dot" data-persona-dot="${key}" aria-hidden="true"></span><span>${item.name}</span></button>`)
      .join('');
    heading.insertAdjacentElement('afterend', menu);
    menu.addEventListener('click', event => {
      const button = event.target.closest('[data-space-persona]');
      if (button) switchTo(button.dataset.spacePersona);
    });
    const toggle = () => (menu.hidden ? openMenu() : closeMenu());
    heading.addEventListener('click', toggle);
    heading.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggle();
      }
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && menu && !menu.hidden) {
        event.stopPropagation();
        closeMenu();
        heading.focus();
      }
    }, true);
    document.addEventListener('pointerdown', event => {
      if (menu && !menu.hidden && !menu.contains(event.target) && event.target !== heading) closeMenu();
    });
  }

  async function start() {
    await hydrateFromServer();
    mountMenu();
    renderHeading();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  // Keep the public name for older integrations. `current()` now returns an
  // ID only; mode-specific values are accepted only during local migration.
  window.XinjiSpaces = { current: () => current, switchTo, PERSONAS };
})();
