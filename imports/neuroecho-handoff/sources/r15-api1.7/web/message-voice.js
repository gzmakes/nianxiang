/* 回复旁的语音图标：把「生成语音」收成气泡旁的一个图标。
   没生成时点一下生成（生成好后自动播放一次）；生成后点一下播放 / 暂停；播放中图标有声波动画。
   2026-10-31 产品要求：回响每条新回复自动生成并播放语音，点图标才暂停；设置里有「自动朗读回复」开关（默认开），
   先不打扰期间、页面不在前台时不自动播。生成、存放和许可仍由 voice-reply.js 负责，这里只换呈现和播放控制。 */
(() => {
  const LABELS = {idle: '生成这条回复的语音', busy: '正在生成语音', ready: '播放语音', playing: '暂停语音'};
  const PREF = 'xinji_voice_autoplay_v1';
  const wantPlay = new Set();
  const slotFor = button => button.closest('.msg')?.querySelector(`[data-voice-clip-slot="${CSS.escape(button.dataset.voiceClip)}"]`);
  const messageId = button => button.closest('.msg')?.dataset.messageId;
  const read = (key, fallback) => { try { const value = JSON.parse(localStorage.getItem(key)); return value ?? fallback; } catch (_) { return fallback; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} };
  const autoplay = () => read(PREF, true) !== false;
  const paused = () => { const resume = document.querySelector('[data-companion-boundary] [data-b-resume]'); return !!resume && !resume.hidden; };

  function sync(button) {
    const text = button.textContent.trim(), audio = slotFor(button)?.querySelector('audio');
    let state = /正在生成/.test(text) ? 'busy' : audio ? (audio.paused ? 'ready' : 'playing') : text === '生成语音' ? 'idle' : 'error';
    button.dataset.voiceState = state;
    const label = LABELS[state] || text;
    if (button.getAttribute('aria-label') !== label) { button.setAttribute('aria-label', label); button.title = label; }
    if (audio && !audio._echoVoiceBound) {
      audio._echoVoiceBound = true;
      for (const type of ['play', 'pause', 'ended']) audio.addEventListener(type, () => sync(button));
    }
    const id = messageId(button);
    if (audio && id && wantPlay.has(id)) { wantPlay.delete(id); audio.play().catch(() => {}); }
  }

  function watch(button) {
    if (button._echoVoiceWatched) return sync(button);
    button._echoVoiceWatched = true;
    const observer = new MutationObserver(() => sync(button));
    observer.observe(button, {childList: true, characterData: true, subtree: true});
    const slot = slotFor(button);
    if (slot) observer.observe(slot, {childList: true});
    sync(button);
  }

  // 已有语音时，点击只播放 / 暂停，不再走重新生成。
  document.addEventListener('click', event => {
    const button = event.target.closest?.('#app #messages [data-voice-clip], #m-app #m-messages [data-voice-clip]');
    if (!button) return;
    const audio = slotFor(button)?.querySelector('audio');
    if (!audio) { const id = messageId(button); if (id) wantPlay.add(id); return; }
    event.preventDefault(); event.stopImmediatePropagation();
    if (audio.paused) audio.play().catch(() => {}); else audio.pause();
  }, true);

  // 新回复自动生成并播放：首次载入的历史只作已读；只对服务已确认、带语音图标的回复生效。
  const seen = new Set();
  let initialized = false;
  function autoplayScan(messages) {
    let sawReal = false;
    for (const msg of messages.querySelectorAll(':scope > .msg[data-message-id]')) {
      const id = msg.dataset.messageId;
      if (!id || id === 'thinking' || id.startsWith('local-')) continue;
      sawReal = true;
      if (seen.has(id) || !msg.classList.contains('assistant')) continue;
      const button = msg.querySelector('[data-voice-clip]');
      if (!button || button.hidden) continue;
      seen.add(id);
      if (!initialized || !autoplay() || paused() || document.hidden) continue;
      if (button.dataset.voiceState === 'idle' || button.textContent.trim() === '生成语音') { wantPlay.add(id); button.click(); }
    }
    if (sawReal) initialized = true;
  }

  function mountPreference() {
    const panel = document.querySelector('#tab-design, #m-design-preferences');
    if (!panel || panel.querySelector('.voice-autoplay-pref')) return;
    const label = document.createElement('label');
    label.className = 'emoji-pref voice-autoplay-pref';
    label.innerHTML = '<input type="checkbox"> <span><b>自动朗读回复</b><small>回响每条新回复生成后自动播放一次，点气泡旁的图标暂停。先不打扰期间不播。</small></span>';
    const input = label.querySelector('input');
    input.checked = autoplay();
    input.onchange = () => write(PREF, input.checked);
    panel.appendChild(label);
  }

  function start() {
    const messages = document.querySelector('#app #messages, #m-app #m-messages');
    if (!messages || typeof MutationObserver === 'undefined') return;
    const scan = () => { messages.querySelectorAll('[data-voice-clip]').forEach(watch); autoplayScan(messages); };
    new MutationObserver(scan).observe(messages, {childList: true});
    scan();
    mountPreference();
    new MutationObserver(mountPreference).observe(document.body, {childList: true, subtree: true});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
