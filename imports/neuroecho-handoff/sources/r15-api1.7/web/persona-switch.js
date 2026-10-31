/* 人格与模式切换：切换会话时同步到服务端，后续模型调用使用对应人格卡与模式提示词；浏览器本地仅保留当前空间和消息筛选视图。 */
(() => {
  const root = document.documentElement;
  const PERSONAS = { nianxiang: { name: '念响', hello: '属于你的一小段空白' }, whale: { name: '小鲸鱼', hello: '小鲸鱼在这儿' } };
  const MODES = { companion: '陪伴', work: '工作' };
  let syncToken = 0;
  async function syncSession(space) {
    const sid = localStorage.getItem('xinji_session');
    if (!sid) return true;
    const token = ++syncToken;
    const [nextPersona, nextMode] = space.split(':');
    const previous = current;
    const [previousPersona, previousMode] = previous.split(':');
    const put = (path, body) => fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    try {
      const personaResult = await put(`/api/session/${encodeURIComponent(sid)}/persona`, { persona_id: nextPersona });
      if (!personaResult.ok) throw new Error('当前人格还没有同步到服务端');
      const modeResult = await put(`/api/session/${encodeURIComponent(sid)}/mode`, { interaction_mode: nextMode });
      if (!modeResult.ok) {
        // Keep the session coherent when the second write is rejected. This is
        // best effort; the original error remains the user-visible failure.
        await put(`/api/session/${encodeURIComponent(sid)}/persona`, { persona_id: previousPersona }).catch(() => {});
        throw new Error('当前陪伴方式还没有同步到服务端');
      }
      return token === syncToken;
    } catch (error) {
      document.dispatchEvent(new CustomEvent('xinji-space-sync-error', { detail: { error } }));
      return false;
    }
  }
  const DEFAULT = 'nianxiang:companion';
  const STORE = 'xinji_space_v1';
  const read = () => { try { const value = JSON.parse(localStorage.getItem(STORE)); return value && typeof value === 'object' ? value : {}; } catch (_) { return {}; } };
  const write = value => { try { localStorage.setItem(STORE, JSON.stringify(value)); } catch (_) {} };
  const saved = read();
  let current = typeof saved.current === 'string' && saved.current.includes(':') && PERSONAS[saved.current.split(':')[0]] && MODES[saved.current.split(':')[1]] ? saved.current : DEFAULT;
  const views = saved.views && typeof saved.views === 'object' && !Array.isArray(saved.views) ? saved.views : {};
  const persist = () => { const keys = Object.keys(views); if (keys.length > 4000) for (const key of keys.slice(0, keys.length - 4000)) delete views[key]; write({ current, views }); };
  const persona = () => current.split(':')[0], mode = () => current.split(':')[1];
  const label = space => `${PERSONAS[space.split(':')[0]].name}·${MODES[space.split(':')[1]]}`;
  const realId = id => id && id !== 'thinking' && !String(id).startsWith('local-');

  async function hydrateFromServer() {
    let sid = localStorage.getItem('xinji_session');
    try {
      // app.js restores the canonical conversation asynchronously. If this
      // script starts first, bootstrap from the same endpoint instead of
      // leaving the switcher pointed at stale local state.
      let response;
      if (sid) response = await fetch(`/api/session/${encodeURIComponent(sid)}`);
      else response = await fetch('/api/conversation');
      if (!response.ok) return;
      const data = await response.json();
      sid = data?.session?.id || sid;
      if (sid) localStorage.setItem('xinji_session', sid);
      const serverPersona = data?.session?.persona_id;
      const serverMode = data?.session?.interaction_mode;
      if (PERSONAS[serverPersona] && MODES[serverMode]) {
        current = `${serverPersona}:${serverMode}`;
        persist();
        root.dataset.persona = serverPersona;
      }
    } catch (_) {
      // The main app will show its normal connection error if the session is unavailable.
    }
  }

  root.dataset.persona = persona();
  root.dataset.spaceArming = 'true';

  // 把话题筛选接管成空间筛选：未记录的历史消息算默认空间；新来的消息算当前空间并记下来。
  let armed = false;
  function spaceOf(id) {
    if (!realId(id)) return current;
    if (views[id]) return views[id];
    if (!armed) return DEFAULT;
    views[id] = current; persist();
    return current;
  }
  function matches(id, filter) {
    if (filter === '全部') return true;
    return label(spaceOf(id)) === filter;
  }

  function workspace() { return window.XinjiWorkspace || window.XinjiMobileWorkspace; }
  function applyFilter() { workspace()?.setTopic(label(current)); }

  // 顶部：人格名胶囊可点，弹出两个人格；话题行换成 陪伴 / 工作。
  let menu = null;
  function renderHeading() {
    const heading = document.querySelector('.conversation-persona h2');
    if (!heading) return;
    heading.textContent = PERSONAS[persona()].name;
    heading.classList.add('persona-name');
    if (!heading.hasAttribute('tabindex')) { heading.setAttribute('tabindex', '0'); heading.setAttribute('role', 'button'); heading.setAttribute('aria-haspopup', 'menu'); heading.setAttribute('title', '切换人格'); }
    heading.setAttribute('aria-expanded', String(!!menu && !menu.hidden));
    const hello = document.querySelector('.chat-hello');
    if (hello) hello.textContent = PERSONAS[persona()].hello;
    for (const button of document.querySelectorAll('.space-modes [data-space-mode]')) {
      const active = button.dataset.spaceMode === mode();
      button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
    }
    for (const button of document.querySelectorAll('.persona-menu [data-space-persona]')) button.setAttribute('aria-checked', String(button.dataset.spacePersona === persona()));
  }
  async function switchTo(space) {
    if (space === current) return;
    if (!(await syncSession(space))) return;
    current = space; persist();
    root.dataset.persona = persona();
    closeMenu();
    renderHeading();
    applyFilter();
    // 手机上不自动聚焦，免得每次切换都弹键盘。
    document.querySelector('#app #composer textarea')?.focus();
  }
  function closeMenu() { if (menu) menu.hidden = true; renderHeading(); }
  function openMenu() { if (!menu) return; menu.hidden = false; renderHeading(); menu.querySelector('[aria-checked="true"]')?.focus(); }
  function mountMenu() {
    const persona_ = document.querySelector('.conversation-persona');
    const heading = persona_?.querySelector('h2');
    if (!persona_ || !heading || menu) return;
    menu = document.createElement('div');
    menu.className = 'persona-menu'; menu.hidden = true; menu.setAttribute('role', 'menu'); menu.setAttribute('aria-label', '选择人格');
    menu.innerHTML = Object.entries(PERSONAS).map(([key, item]) => `<button type="button" role="menuitemradio" data-space-persona="${key}" aria-checked="false"><span class="persona-dot" data-persona-dot="${key}" aria-hidden="true"></span><span>${item.name}</span></button>`).join('');
    heading.insertAdjacentElement('afterend', menu);
    menu.addEventListener('click', event => { const button = event.target.closest('[data-space-persona]'); if (button) switchTo(`${button.dataset.spacePersona}:${mode()}`); });
    const toggle = () => (menu.hidden ? openMenu() : closeMenu());
    heading.addEventListener('click', toggle);
    heading.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && menu && !menu.hidden) { event.stopPropagation(); closeMenu(); heading.focus(); } }, true);
    document.addEventListener('pointerdown', event => { if (menu && !menu.hidden && !menu.contains(event.target) && event.target !== heading) closeMenu(); });
  }
  function mountModes() {
    const topics = document.querySelector('#app #design-topics, #m-app #m-design-topics');
    if (!topics || document.querySelector('.space-modes')) return;
    const modes = document.createElement('div');
    modes.className = 'topic-tabs space-modes'; modes.setAttribute('aria-label', '对话模式');
    modes.innerHTML = Object.entries(MODES).map(([key, name]) => `<button type="button" class="topic-chip" data-space-mode="${key}" aria-pressed="false">${name}</button>`).join('');
    topics.insertAdjacentElement('beforebegin', modes);
    modes.addEventListener('click', event => { const button = event.target.closest('[data-space-mode]'); if (button) switchTo(`${persona()}:${button.dataset.spaceMode}`); });
  }

  // 当前空间没有消息时的提示（整条对话不为空，所以 app 自己的空状态不会出现）。
  function renderEmpty(messages) {
    let note = messages.querySelector(':scope > .space-empty');
    if (!note) { note = document.createElement('div'); note.className = 'space-empty'; messages.prepend(note); }
    const visible = [...messages.querySelectorAll(':scope > .msg[data-message-id]')].some(msg => !msg.classList.contains('is-topic-hidden'));
    const hidden = visible || !armed, text = `${PERSONAS[persona()].name}在这儿。这是「${MODES[mode()]}」的新对话，想说什么就从这里开始。`;
    // 只在真的变了时才写，否则这里的改动又会触发下面的 MutationObserver，形成死循环。
    if (note.hidden !== hidden) note.hidden = hidden;
    if (note.textContent !== text) note.textContent = text;
  }

  async function start() {
    const messages = document.querySelector('#app #messages, #m-app #m-messages');
    const ws = workspace();
    if (!messages || !ws?.topics) { delete root.dataset.spaceArming; return; }
    await hydrateFromServer();
    ws.topics.matches = matches;
    mountMenu(); mountModes(); renderHeading();
    // 第一次渲染出来的都是历史：没记录的归默认空间；之后到的才归当前空间。整条对话还是空的就直接开始。
    function arm() {
      if (armed) return;
      for (const msg of messages.querySelectorAll(':scope > .msg[data-message-id]')) { const id = msg.dataset.messageId; if (realId(id) && !views[id]) views[id] = DEFAULT; }
      persist(); armed = true; delete root.dataset.spaceArming;
      applyFilter(); renderEmpty(messages);
    }
    const observer = new MutationObserver(records => {
      if (records.every(record => record.target.closest?.('.space-empty') || record.target.parentElement?.closest('.space-empty'))) return;
      if (!armed && messages.querySelector(':scope > .msg[data-message-id]')) arm();
      renderEmpty(messages);
    });
    const started = Date.now();
    const poll = setInterval(() => {
      const app = document.querySelector('#app, #m-app'), empty = document.querySelector('#chat-empty, #m-chat-empty');
      if (armed || (app && !app.classList.contains('is-hidden') && ((empty && !empty.classList.contains('is-hidden')) || messages.querySelector(':scope > .msg[data-message-id]'))) || Date.now() - started > 8000) { clearInterval(poll); arm(); }
    }, 250);
    observer.observe(messages, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
    document.addEventListener('xinji-topic-change', () => renderEmpty(messages));
    if (messages.querySelector(':scope > .msg[data-message-id]')) observer.takeRecords(), renderEmpty(messages);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.XinjiSpaces = { current: () => current, switchTo, PERSONAS, MODES };
})();
