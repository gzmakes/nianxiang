/* New replies are announced explicitly by the chat transport, never by a history redraw. */
(() => {
  'use strict';
  const PREF = 'xinji_voice_autoplay_v1';
  const intents = new Map(), announced = new Set(), queue = [];
  let current = null, currentRequest = null;
  const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (_) { return fallback; } };
  const autoplay = () => read(PREF, true) !== false;
  const paused = () => { const resume = document.querySelector('[data-companion-boundary] [data-b-resume]'); return !!resume && !resume.hidden; };
  const canAutoPlay = () => autoplay() && !paused() && !document.hidden && !window.NianxiangSound?.isBlocked?.();
  const messageId = button => button.closest('.msg')?.dataset.messageId;
  const slotFor = button => button.closest('.msg')?.querySelector('[data-voice-clip-slot]');
  const readFor = button => button.closest('.msg')?.querySelector('[data-voice-message]');
  const audioFor = button => slotFor(button)?.querySelector('audio');
  function findMessage(id) {
    return [...document.querySelectorAll('#messages .msg.assistant[data-message-id], #m-messages .msg.assistant[data-message-id]')]
      .find(msg => msg.dataset.messageId === id);
  }
  function finish(id) {
    if (current !== id) return;
    current = null; currentRequest = null;
    intents.delete(id);
    queueMicrotask(pump);
  }
  function sync(button) {
    if (button.hidden) { button.dataset.localVoice = 'true'; button.hidden = false; }
    const text = button.textContent.trim(), audio = audioFor(button), native = readFor(button);
    const id = messageId(button);
    const local = button.dataset.localVoice === 'true';
    let state = local ? (/暂不能/.test(native?.textContent || '') ? 'error' : native?.getAttribute('aria-pressed') === 'true' ? (native.getAttribute('aria-busy') === 'true' ? 'busy' : 'playing') : 'ready')
      : /正在生成/.test(text) ? 'busy' : audio ? (audio.paused ? 'ready' : 'playing') : text === '生成语音' ? 'idle' : 'error';
    const labels = {idle:'生成这条回复的语音', busy:'正在准备语音', ready:'播放语音', playing:'停止语音', error:'语音不可用，请点击重试'};
    button.dataset.voiceState = state;
    button.setAttribute('aria-label', labels[state]); button.title = labels[state];
    if (audio && !audio._echoVoiceBound) {
      audio._echoVoiceBound = true;
      for (const type of ['play', 'pause', 'ended', 'error']) audio.addEventListener(type, () => {
        const visible = findMessage(id)?.querySelector('[data-voice-clip]');
        if (visible) sync(visible);
        if (type !== 'play') finish(id);
      });
    }
    if (audio && id && intents.has(id)) {
      const intent = intents.get(id); intents.delete(id);
      if (intent === 'auto' && !canAutoPlay()) { finish(id); return; }
      const failed = () => {
        const visible = findMessage(id)?.querySelector('[data-voice-clip]');
        if (visible) { visible.title = '浏览器未自动播放，点此播放'; visible.setAttribute('aria-label', visible.title); }
        finish(id);
      };
      try { const result = audio.play(); if (result?.catch) result.catch(failed); } catch (_) { failed(); }
    } else if (state === 'error' && current === id && intents.get(id) === 'auto') {
      // Some messages cannot be turned into WAV (e.g. a long reply); use only
      // the visible text with the device speech engine instead.
      intents.delete(id); button.dataset.localVoice = 'true'; native?.click(); sync(button);
      if (native?.getAttribute('aria-pressed') !== 'true') finish(id);
    } else if (local && current === id && (state === 'ready' || state === 'error')) finish(id);
  }
  function watch(button) {
    if (button._echoVoiceWatched) return sync(button);
    button._echoVoiceWatched = true;
    // A hidden clip means this device/source cannot generate a WAV. Keep a
    // visible control for the existing local speech-synthesis fallback.
    if (button.hidden) { button.dataset.localVoice = 'true'; button.hidden = false; }
    const observer = new MutationObserver(() => sync(button));
    observer.observe(button, {attributes:true, attributeFilter:['hidden'], childList:true, characterData:true, subtree:true});
    const slot = slotFor(button), native = readFor(button);
    if (slot) observer.observe(slot, {childList:true});
    if (native) observer.observe(native, {attributes:true, attributeFilter:['aria-pressed','aria-busy'], childList:true, characterData:true, subtree:true});
    sync(button);
  }
  function pump() {
    if (current) return;
    while (queue.length) {
      const id = queue.shift(), msg = findMessage(id), button = msg?.querySelector('[data-voice-clip]');
      if (!button || !canAutoPlay()) continue;
      watch(button); current = id; currentRequest = {}; button._echoAutoRequest = currentRequest;
      if (button.dataset.localVoice === 'true') {
        const native = readFor(button); native?.click(); sync(button);
        if (native?.getAttribute('aria-pressed') !== 'true') finish(id);
      } else {
        intents.set(id, 'auto');
        if (audioFor(button)) sync(button); else button.click();
      }
      break;
    }
  }
  function announce(id) {
    id = String(id || '');
    if (!id || announced.has(id)) return;
    announced.add(id);
    if (!canAutoPlay()) return;
    queue.push(id); pump();
  }
  document.addEventListener('click', event => {
    const button = event.target.closest?.('#app #messages [data-voice-clip], #m-app #m-messages [data-voice-clip]');
    if (!button) return;
    if (button.dataset.localVoice === 'true') {
      event.preventDefault(); event.stopImmediatePropagation(); readFor(button)?.click(); sync(button); return;
    }
    const audio = audioFor(button);
    if (!audio) { const id = messageId(button); if (id && !intents.has(id)) intents.set(id, 'manual'); return; }
    event.preventDefault(); event.stopImmediatePropagation();
    if (audio.paused) audio.play().catch(() => { button.title = '无法播放，请检查设备声音'; }); else audio.pause();
  }, true);
  function mountPreference() {
    const panel = document.querySelector('#tab-design, #m-design-preferences');
    if (!panel || panel.querySelector('.voice-autoplay-pref')) return;
    const label = document.createElement('label'); label.className = 'emoji-pref voice-autoplay-pref';
    label.innerHTML = '<input type="checkbox"> <span><b>自动朗读回复</b><small>新回复自动播放，点气泡旁的图标停止；先不打扰期间不播。</small></span>';
    const input = label.querySelector('input'); input.checked = autoplay();
    input.onchange = () => { try { localStorage.setItem(PREF, JSON.stringify(input.checked)); } catch (_) {} if (!input.checked) { cancel(); window.XinjiVoice?.stop?.(); } };
    panel.appendChild(label);
  }
  function start() {
    const messages = document.querySelector('#app #messages, #m-app #m-messages');
    if (!messages || typeof MutationObserver === 'undefined') return;
    const scan = () => messages.querySelectorAll('[data-voice-clip]').forEach(watch);
    new MutationObserver(scan).observe(messages, {childList:true}); scan(); mountPreference();
    new MutationObserver(mountPreference).observe(document.body, {childList:true, subtree:true});
  }
  function cancel() { queue.length = 0; intents.clear(); current = null; currentRequest = null; }
  document.addEventListener('visibilitychange', () => { if (document.hidden) cancel(); });
  window.XinjiMessageVoice = {announce, cancel, clipFailed(id, button) {
    if (current !== id || !currentRequest || button?._echoAutoRequest !== currentRequest) return;
    if (findMessage(id) && canAutoPlay()) sync(button);
    if (current === id && intents.has(id)) finish(id);
  }};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
