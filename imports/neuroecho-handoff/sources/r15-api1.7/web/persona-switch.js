/* 人格与模式切换（2026-10-31，产品要求，先做能切换的版本）：
   两个人格（念响 / 小鲸鱼）× 两种模式（陪伴 / 工作）= 四个「空间」。切到另一个空间，看到的就是一个新的对话框。
   实现方式和话题视图一样：R15 服务端只有一条持久对话（canonical conversation，H5、配对设备、更新流都绑在它上面），
   所以空间是本设备的视图——每条消息记下它属于哪个空间（localStorage），当前空间只显示自己的消息，新消息自动归入当前空间。
   记忆、来源、模型对四个空间是共用的；服务端也还不知道人格（没有不同的提示词）。要做成真正独立的对话，需要服务端加「多对话」。 */
(() => {
  const root = document.documentElement;
  const PERSONAS = { nianxiang: { name: '念响', hello: '属于你的一小段空白' }, whale: { name: '小鲸鱼', hello: '小鲸鱼在这儿' } };
  const MODES = { companion: '陪伴', work: '工作' };
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
  function switchTo(space) {
    if (space === current) return;
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

  function start() {
    const messages = document.querySelector('#app #messages, #m-app #m-messages');
    const ws = workspace();
    if (!messages || !ws?.topics) { delete root.dataset.spaceArming; return; }
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
