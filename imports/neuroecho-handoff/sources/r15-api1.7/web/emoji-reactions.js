/* emoji 回应（念念 design.md v0.2 §7.10）：固定 8 个，一条消息最多 1 个，只表达「我收到了、我在」。
   两个方向：回响在你的消息上贴角标（按关键词规则，本地判断）；你悬停回响的气泡，点笑脸给它贴一个。
   仅本设备视图：存在 localStorage，不发送给模型、不写入记忆，也不替你判断情绪。 */
(() => {
  const EMOJI = [['🫂', '抱抱'], ['✨', '真好'], ['🌙', '歇会'], ['👀', '在看'], ['💪', '加油'], ['☕', '歇一下'], ['🌱', '慢慢来'], ['👍', '收到']];
  const NAME = Object.fromEntries(EMOJI);
  const STORE = 'xinji_emoji_reactions_v1', PREF = 'xinji_emoji_enabled_v1', LIMIT = 500;
  const SERIOUS = /亏|生病|病了|去世|离世|失去|住院|医院|葬礼/;
  const RULES = [
    ['🫂', /累|难过|委屈|难受|伤心|崩溃|好烦|心烦|想哭|压力好大/],
    ['🌙', /晚了|要睡|去睡|睡觉|困了|好困|晚安|别提醒/],
    ['🌱', /卡住|卡在|没进展|没头绪|搞不定|写不出/],
    ['☕', /饿|想吃|想喝|吃饭|咖啡|奶茶/],
    ['✨', /做完|完成了|交了|搞定|成了|过了|成功/],
    ['💪', /准备开始|要开始|开始了|准备好了/],
    ['👍', /^(好|好的|好啊|谢谢|谢啦|嗯+|收到|行|可以|ok)[。！!~～]*$/i],
  ];
  const read = (key, fallback) => { try { const value = JSON.parse(localStorage.getItem(key)); return value ?? fallback; } catch (_) { return fallback; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} };
  let reactions = read(STORE, {});
  if (!reactions || typeof reactions !== 'object' || Array.isArray(reactions)) reactions = {};
  const enabled = () => read(PREF, true) !== false;
  const root = document.documentElement;
  const reducedMotion = () => root.dataset.reduceMotion === 'true' || (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  const quiet = () => { const resume = document.querySelector('[data-companion-boundary] [data-b-resume]'); return !!resume && !resume.hidden; };
  const realId = id => id && id !== 'thinking' && !String(id).startsWith('local-');
  // Web 是 #app #messages，H5（m.html）是 #m-app #m-messages；两页共用这一个模块。
  const messagesRoot = () => document.querySelector('#app #messages, #m-app #m-messages');

  function pick(text) {
    const value = String(text || '').trim();
    if (!value) return null;
    const serious = SERIOUS.test(value);
    for (const [emoji, pattern] of RULES) {
      if (!pattern.test(value)) continue;
      if (serious && (emoji === '✨' || emoji === '💪')) continue;
      return emoji;
    }
    return !serious && value.length >= 20 ? '👀' : null;
  }
  // 光球表情（orb-face.js）共用同一套关键词，避免两份规则各改各的。
  window.XinjiEmojiRules = { RULES, SERIOUS, pick };

  function persist() {
    const keys = Object.keys(reactions);
    if (keys.length > LIMIT) for (const key of keys.slice(0, keys.length - LIMIT)) delete reactions[key];
    write(STORE, reactions);
  }

  function badgeFor(msg, emoji) {
    const bubbles = msg.querySelectorAll(':scope > .bubble');
    const bubble = bubbles[bubbles.length - 1];
    if (!bubble) return null;
    let badge = bubble.querySelector(':scope > .emoji-badge');
    if (!emoji) { badge?.remove(); msg.classList.remove('has-emoji'); return null; }
    if (!badge) { badge = document.createElement('span'); badge.className = 'emoji-badge'; badge.setAttribute('role', 'img'); bubble.appendChild(badge); }
    badge.textContent = emoji;
    badge.setAttribute('aria-label', (msg.classList.contains('user') ? '回响回应：' : '你的回应：') + NAME[emoji]);
    msg.classList.add('has-emoji');
    return badge;
  }

  function celebrate(badge, emoji) {
    if (!badge || reducedMotion()) return;
    badge.classList.remove('is-new'); void badge.offsetWidth; badge.classList.add('is-new');
    const float = document.createElement('span');
    float.className = 'emoji-float'; float.textContent = emoji; float.setAttribute('aria-hidden', 'true');
    badge.appendChild(float);
    setTimeout(() => float.remove(), 1200);
  }

  function glow(emoji) {
    const previous = root.dataset.presenceState;
    root.dataset.presenceState = 'thinking';
    setTimeout(() => { if (root.dataset.presenceState === 'thinking') root.dataset.presenceState = previous || 'quiet'; }, 1200);
    const face = document.querySelector('.conversation-persona .persona-face');
    if (!face || reducedMotion()) return;
    const bubble = document.createElement('span');
    bubble.className = 'emoji-orb'; bubble.textContent = emoji; bubble.setAttribute('aria-hidden', 'true');
    face.appendChild(bubble);
    setTimeout(() => bubble.remove(), 1400);
  }

  // 回应条：悬停回响的气泡出现笑脸按钮，点开 8 个 emoji；再点同一个取消，点别的替换。
  const bar = document.createElement('div');
  bar.className = 'emoji-bar'; bar.hidden = true; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', '选择一个 emoji 回应');
  bar.innerHTML = EMOJI.map(([emoji, name]) => `<button type="button" data-emoji="${emoji}" aria-label="${name}" title="${name}">${emoji}</button>`).join('');
  let barTarget = null, barOpener = null;
  function closeBar(restoreFocus) {
    if (bar.hidden) return;
    bar.hidden = true;
    if (restoreFocus) barOpener?.focus();
    barTarget = barOpener = null;
  }
  function openBar(msg, opener) {
    const bubble = msg.querySelector(':scope > .bubble');
    if (!bubble) return;
    barTarget = msg.dataset.messageId; barOpener = opener;
    bar.hidden = false;
    for (const button of bar.querySelectorAll('button')) button.setAttribute('aria-pressed', String(reactions[barTarget] === button.dataset.emoji));
    const rect = bubble.getBoundingClientRect(), width = bar.offsetWidth, height = bar.offsetHeight;
    const left = Math.min(Math.max(16, rect.left), window.innerWidth - width - 16);
    const top = rect.top - height - 8 >= 8 ? rect.top - height - 8 : rect.bottom + 8;
    bar.style.left = `${Math.round(left)}px`; bar.style.top = `${Math.round(top)}px`;
    bar.querySelector('button')?.focus();
  }
  bar.addEventListener('click', event => {
    const button = event.target.closest('[data-emoji]');
    if (!button || !barTarget) return;
    const emoji = button.dataset.emoji, id = barTarget;
    const msg = messagesRoot()?.querySelector(`[data-message-id="${CSS.escape(id)}"]`);
    if (reactions[id] === emoji) delete reactions[id]; else reactions[id] = emoji;
    persist();
    closeBar(true);
    if (!msg) return;
    const badge = badgeFor(msg, reactions[id]);
    if (reactions[id]) { celebrate(badge, emoji); glow(emoji); }
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !bar.hidden) { event.stopPropagation(); closeBar(true); } }, true);
  document.addEventListener('pointerdown', event => { if (!bar.hidden && !bar.contains(event.target) && !event.target.closest('.emoji-react-btn')) closeBar(false); });
  window.addEventListener('resize', () => closeBar(false));

  const seen = new Set(), pendingLocal = new Map(), localQueue = [], localToReal = new Map();
  let initialized = false, sinceLastBadge = 2;
  const byId = id => id && messagesRoot()?.querySelector(`[data-message-id="${CSS.escape(id)}"]`);
  const messageText = msg => [...msg.querySelectorAll(':scope > .bubble')].map(bubble => {
    const copy = bubble.cloneNode(true); copy.querySelectorAll('.emoji-badge').forEach(node => node.remove()); return copy.textContent;
  }).join('\n').trim();
  // 你的新消息：连续 3 条里最多贴 1 次；先不打扰或关掉开关时不贴。
  function decide(text) {
    sinceLastBadge += 1;
    if (!enabled() || quiet() || sinceLastBadge < 3) return null;
    const emoji = pick(text);
    if (emoji) sinceLastBadge = 0;
    return emoji;
  }
  function announce(id, emoji) {
    requestAnimationFrame(() => {
      const current = byId(id) || byId(localToReal.get(id));
      if (current) celebrate(badgeFor(current, emoji), emoji);
      glow(emoji);
    });
  }
  function decorate(messages) {
    let sawHistory = false;
    for (const msg of messages.querySelectorAll(':scope > .msg[data-message-id]')) {
      const id = msg.dataset.messageId;
      if (!id || id === 'thinking') continue;
      if (!realId(id)) {
        // 刚发出、还没被服务确认的那条：此刻就贴，赶在回复之前。
        if (!msg.classList.contains('user')) continue;
        if (pendingLocal.has(id)) { badgeFor(msg, pendingLocal.get(id)); continue; }
        if (seen.has(id) || !initialized) continue;
        seen.add(id);
        const text = messageText(msg), emoji = decide(text);
        localQueue.push({id, text, emoji});
        if (localQueue.length > 20) localQueue.shift();
        if (emoji) { pendingLocal.set(id, emoji); announce(id, emoji); }
        continue;
      }
      sawHistory = true;
      if (msg.classList.contains('assistant') && !msg.querySelector(':scope > .emoji-react-btn')) {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'emoji-react-btn'; button.setAttribute('aria-label', '给这条回复一个 emoji 回应'); button.title = 'emoji 回应';
        button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M8.5 14c.9 1.3 2.1 2 3.5 2s2.6-.7 3.5-2"/><path d="M9.5 10h.01M14.5 10h.01"/></svg>';
        button.onclick = () => (bar.hidden || barTarget !== id ? openBar(msg, button) : closeBar(true));
        msg.appendChild(button);
      }
      if (reactions[id]) badgeFor(msg, reactions[id]);
      if (seen.has(id)) continue;
      seen.add(id);
      if (!initialized || !msg.classList.contains('user')) continue;
      // 服务确认后的同一条消息：沿用发出时贴的角标，不重复计数、不重播动画。
      const text = messageText(msg), index = localQueue.findIndex(item => item.text === text);
      if (index >= 0) {
        const [local] = localQueue.splice(index, 1);
        pendingLocal.delete(local.id); localToReal.set(local.id, id);
        if (local.emoji && !reactions[id]) { reactions[id] = local.emoji; persist(); badgeFor(msg, local.emoji); }
        continue;
      }
      // 别的设备发来的消息：确认到达时再贴。
      if (reactions[id]) continue;
      const emoji = decide(text);
      if (!emoji) continue;
      reactions[id] = emoji; persist(); announce(id, emoji);
    }
    // 第一次载入的历史消息只作已读，不补贴角标。
    if (sawHistory) initialized = true;
  }

  function mountPreference() {
    const panel = document.querySelector('#tab-design, #m-design-preferences');
    if (!panel || panel.querySelector('.emoji-pref')) return;
    const label = document.createElement('label');
    label.className = 'emoji-pref';
    label.innerHTML = '<input type="checkbox"> <span><b>用 emoji 回应</b><small>回响偶尔在你的消息上贴一个 emoji，只表示「收到了」。仅存在这台设备上。</small></span>';
    const input = label.querySelector('input');
    input.checked = enabled();
    input.onchange = () => write(PREF, input.checked);
    panel.appendChild(label);
  }

  function start() {
    const messages = messagesRoot();
    if (!messages) return;
    document.body.appendChild(bar);
    mountPreference();
    // H5 的设置是按需渲染进弹层的，所以开关要在面板出现时再挂一次。
    new MutationObserver(mountPreference).observe(document.body, {childList: true, subtree: true});
    decorate(messages);
    if (typeof MutationObserver !== 'undefined') new MutationObserver(() => decorate(messages)).observe(messages, {childList: true});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.XinjiEmojiReactions = {pick, list: EMOJI.map(([emoji]) => emoji)};
})();
