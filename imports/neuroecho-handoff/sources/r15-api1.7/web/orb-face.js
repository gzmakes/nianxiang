/* 光球表情（2026-10-31，产品要求）：光球有两只眼睛，表情随你最近一条消息里的情绪关键词变化。
   关键词与 emoji 回应共用同一套（emoji-reactions.js 的 XinjiEmojiRules），只在本机判断，不发送、不写入记忆，
   也不替你判断情绪——只是「我收到了」的一个眼神。表情保持约 12 秒后回到平时；思考 / 出错 / 先不打扰由对话状态决定，优先于表情。 */
(() => {
  const root = document.documentElement;
  const FACE = { '🫂': 'sad', '🌙': 'sleepy', '🌱': 'stuck', '☕': 'happy', '✨': 'happy', '💪': 'cheer', '👍': 'happy', '👀': 'curious' };
  const HOLD = 12000;
  let timer = null;

  function setFace(face, hold = HOLD) {
    clearTimeout(timer);
    if (!face || face === 'neutral') { delete root.dataset.presenceFace; return; }
    root.dataset.presenceFace = face;
    timer = setTimeout(() => { if (root.dataset.presenceFace === face) delete root.dataset.presenceFace; }, hold);
  }

  function faceFor(text) {
    const rules = window.XinjiEmojiRules;
    const value = String(text || '').trim();
    if (!value || !rules) return null;
    if (rules.SERIOUS.test(value)) return 'calm';
    for (const [emoji, pattern] of rules.RULES) if (pattern.test(value)) return FACE[emoji] || null;
    return value.length >= 20 ? 'curious' : null;
  }

  const messageText = msg => [...msg.querySelectorAll(':scope > .bubble')].map(bubble => {
    const copy = bubble.cloneNode(true); copy.querySelectorAll('.emoji-badge').forEach(node => node.remove()); return copy.textContent;
  }).join('\n').trim();

  // 你的新消息才换表情：刚发出的 local- 那条立刻换；服务确认后换成真实 id 的同一条不重复；首次载入的历史只作已读。
  const seen = new Set(), facedLocal = [];
  let initialized = false;
  function scan(messages) {
    let sawReal = false;
    for (const msg of messages.querySelectorAll(':scope > .msg[data-message-id]')) {
      const id = msg.dataset.messageId;
      if (!id || id === 'thinking') continue;
      const local = id.startsWith('local-');
      if (!local) sawReal = true;
      if (seen.has(id) || !msg.classList.contains('user')) continue;
      seen.add(id);
      if (!initialized) continue;
      const text = messageText(msg);
      if (local) { facedLocal.push(text); if (facedLocal.length > 20) facedLocal.shift(); }
      else { const index = facedLocal.indexOf(text); if (index >= 0) { facedLocal.splice(index, 1); continue; } }
      const face = faceFor(text);
      if (face) setFace(face);
    }
    if (sawReal) initialized = true;
  }

  function start() {
    const messages = document.querySelector('#app #messages');
    if (!messages) return;
    scan(messages);
    new MutationObserver(() => scan(messages)).observe(messages, { childList: true });
    // 你给回响贴了 emoji：它眯眼笑一下。
    document.addEventListener('click', event => {
      const button = event.target.closest('.emoji-bar [data-emoji]');
      if (button && button.getAttribute('aria-pressed') !== 'true') setFace('happy', 4000);
    }, true);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.XinjiOrbFace = { setFace, faceFor };
})();
