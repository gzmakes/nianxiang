/* 回复旁的语音图标：把「生成语音」收成气泡旁的一个图标。
   没生成时点一下生成（生成好后自动播放一次）；生成后点一下播放 / 暂停；播放中图标有声波动画。
   生成、存放和许可仍由 voice-reply.js 负责，这里只换呈现和点击后的播放控制。 */
(() => {
  const LABELS = {idle: '生成这条回复的语音', busy: '正在生成语音', ready: '播放语音', playing: '暂停语音'};
  const wantPlay = new Set();
  const slotFor = button => button.closest('.msg')?.querySelector(`[data-voice-clip-slot="${CSS.escape(button.dataset.voiceClip)}"]`);
  const messageId = button => button.closest('.msg')?.dataset.messageId;

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
    const button = event.target.closest?.('#app #messages [data-voice-clip]');
    if (!button) return;
    const audio = slotFor(button)?.querySelector('audio');
    if (!audio) { const id = messageId(button); if (id) wantPlay.add(id); return; }
    event.preventDefault(); event.stopImmediatePropagation();
    if (audio.paused) audio.play().catch(() => {}); else audio.pause();
  }, true);

  function start() {
    const messages = document.querySelector('#app #messages');
    if (!messages || typeof MutationObserver === 'undefined') return;
    const scan = () => messages.querySelectorAll('[data-voice-clip]').forEach(watch);
    new MutationObserver(scan).observe(messages, {childList: true});
    scan();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
