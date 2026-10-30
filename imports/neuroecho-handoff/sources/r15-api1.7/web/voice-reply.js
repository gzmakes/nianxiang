/* User-initiated speech for an existing assistant reply. No audio is saved. */
(function (global) {
  'use strict';
  const copy = (key, fallback) => global.EchoShared?.copy?.[key] ?? fallback;
  let active = null, currentSession = null, clipSupported = false, capabilityEpoch = 0;
  let readable = new Map();
  const clips = new Map(), inflight = new Set(), clipControls = new Map();
  const keyFor = (sid, id) => `${sid}\u0000${id}`;
  const visible = () => !global.document?.hidden;
  function readText(message) {
    if (!message || message.role !== 'assistant' || message.delivery_pending) return '';
    if (Array.isArray(message.bubbles) && message.bubbles.length)
      return message.bubbles.every(part => typeof part === 'string') ? message.bubbles.join('\n\n') : '';
    return typeof message.text === 'string' ? message.text : '';
  }
  function current(sessionId, id, text) {
    return !!sessionId && sessionId === currentSession && readable.has(id) && readable.get(id) === text && visible();
  }
  function reset(item) {
    if (!item?.button) return;
    item.button.textContent = copy('voice.read', '朗读');
    item.button.setAttribute('aria-label', '朗读这条回复');
    item.button.setAttribute('aria-pressed', 'false');
    item.button.setAttribute('aria-busy', 'false');
    item.button.setAttribute('title', copy('voice.disclosure', '由设备语音朗读，不会自动播放或创建语音文件。'));
  }
  function clearWatchdog(item) { if (item?.timer != null) { global.clearTimeout?.(item.timer); item.timer = null; } }
  function stop() {
    const old = active; active = null; clearWatchdog(old);
    if (old && global.speechSynthesis) { try { global.speechSynthesis.cancel(); } catch (_) {} }
    reset(old);
  }
  function pauseClip(item, clear = false) {
    if (!item?.player) return;
    try { item.player.pause(); if (clear) { item.player.removeAttribute('src'); item.player.load?.(); } } catch (_) {}
  }
  function stopAll() { stop(); for (const item of clips.values()) pauseClip(item); }
  function spokenText(value) {
    return String(value || '').replace(/\[表情[:：]\s*[^\]\r\n]+\]/g, '')
      .replace(/\[([^\]]+)\]\(https?:\/\/[^)]+\)/g, '$1').replace(/[*_`#]/g, '').trim();
  }
  function bindMessage(id, text, button, sessionId) {
    reset({button});
    if (active && active.id === id && active.sessionId === sessionId && active.text === text) {
      active.button = button;
      button.textContent = copy('voice.stop', '停止朗读');
      button.setAttribute('aria-label', '停止朗读这条回复');
      button.setAttribute('aria-pressed', 'true');
      button.setAttribute('aria-busy', String(active.preparing));
      if (active.preparing) button.setAttribute('title', copy('voice.preparing', '正在准备朗读…'));
    }
  }
  function unavailable(button) {
    reset({button}); button.textContent = '暂不能朗读';
    button.setAttribute('aria-label', copy('voice.unavailable', '本机语音暂不可用，可以继续看文字。'));
    button.setAttribute('title', copy('voice.unavailable', '本机语音暂不可用，可以继续看文字。'));
  }
  function playMessage(id, text, button, sessionId) {
    if (!id || !button || !current(sessionId, id, text)) return false;
    if (active && active.id === id && active.sessionId === sessionId && active.text === text) { stop(); return true; }
    stopAll();
    const body = spokenText(text);
    if (!body || !global.speechSynthesis || typeof global.SpeechSynthesisUtterance !== 'function') { unavailable(button); return false; }
    let chinese;
    try {
      const voices = global.speechSynthesis.getVoices?.() || [];
      // localService=false denotes a remote service. Never fall back to it.
      const local = voices.filter(voice => voice.localService === true);
      chinese = local.find(v => /^zh[-_]CN$/i.test(v.lang)) || local.find(v => /^zh/i.test(v.lang));
    } catch (_) {}
    if (!chinese) { unavailable(button); return false; } // an empty/late voice list needs another explicit click
    const utterance = new global.SpeechSynthesisUtterance(body);
    utterance.lang = chinese.lang; utterance.voice = chinese; utterance.rate = 0.96;
    const item = {sessionId, id, text, button, utterance, preparing: true, timer: null}; active = item;
    bindMessage(id, text, button, sessionId);
    function watchdog(milliseconds) {
      clearWatchdog(item);
      if (typeof global.setTimeout !== 'function') return;
      item.timer = global.setTimeout(() => {
        if (active !== item) return;
        stop(); unavailable(item.button);
      }, milliseconds);
    }
    utterance.onstart = () => {
      if (active !== item) return;
      item.preparing = false; bindMessage(id, text, item.button, sessionId);
      watchdog(Math.min(600000, Math.max(20000, body.length * 500 + 10000)));
    };
    utterance.onend = () => { if (active === item) { active = null; clearWatchdog(item); reset(item); } };
    utterance.onerror = () => { if (active !== item) return; active = null; clearWatchdog(item); unavailable(item.button); };
    watchdog(10000);
    try { global.speechSynthesis.speak(utterance); return true; }
    catch (_) { utterance.onerror(); return false; }
  }
  function clipEligible(message) { return !!readText(message) && spokenText(message.text) === spokenText(readText(message)); }
  function bindClipControl(button, eligible = true) {
    if (!button) return;
    for (const previous of clipControls.keys()) if (previous.isConnected === false) clipControls.delete(previous);
    clipControls.set(button, eligible); button.hidden = !clipSupported || !eligible;
  }
  async function configure({api}) {
    const ticket = ++capabilityEpoch; clipSupported = false;
    for (const button of clipControls.keys()) button.hidden = true;
    try { const cap = await api('/api/capabilities'); if (ticket !== capabilityEpoch) return;
      clipSupported = cap?.features?.voice_clip_from_assistant_message === true;
    } catch (_) { if (ticket !== capabilityEpoch) return; }
    for (const [button, eligible] of clipControls) button.hidden = !clipSupported || !eligible;
  }
  function attachClip(sessionId, id, text, container) {
    const item = clips.get(keyFor(sessionId, id));
    if (!item || item.text !== text || !container) return false;
    pauseClip(item, true);
    const player = global.document.createElement('audio');
    item.player = player;
    player.onplay = () => { stop(); for (const other of clips.values()) if (other !== item) pauseClip(other); if (!visible()) pauseClip(item); };
    player.controls = true;
    player.style.maxWidth = '100%';
    player.preload = 'metadata';
    player.src = item.url;
    player.setAttribute('aria-label', '播放这条回复的本机语音');
    container.replaceChildren(player);
    return true;
  }
  function pruneClips(sessionId, messages) {
    currentSession = sessionId || null;
    readable = new Map((messages || []).filter(m => m.role === 'assistant' && !m.delivery_pending).map(m => [m.id, readText(m)]));
    if (active && !current(active.sessionId, active.id, active.text)) stop();
    const allowed = new Map((messages || []).filter(clipEligible)
      .map(m => [keyFor(sessionId, m.id), m.text]));
    for (const [key, item] of clips) {
      if (allowed.get(key) !== item.text) { pauseClip(item, true); global.URL.revokeObjectURL(item.url); clips.delete(key); }
    }
  }
  async function makeClip({sessionId, id, text, button, container, isCurrent, onReady}) {
    if (!clipSupported || !sessionId || !id || !button || !container || typeof isCurrent !== 'function' || !isCurrent() || sessionId !== currentSession || !readable.has(id) || spokenText(text) !== spokenText(readable.get(id))) return false;
    if (attachClip(sessionId, id, text, container)) return true;
    const key = keyFor(sessionId, id);
    if (inflight.has(key)) return false;
    inflight.add(key); button.disabled = true; button.textContent = '正在生成语音…';
    try {
      const response = await global.fetch('/api/voice/clip', {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({session_id:sessionId, message_id:id})});
      if (!response.ok) {
        let message = '语音生成失败，可使用朗读';
        try { const body = await response.json(); if (typeof body.detail === 'string') message = body.detail; } catch (_) {}
        throw new Error(message);
      }
      const blob = await response.blob();
      if (!isCurrent() || !blob.size || !/^audio\/wav(?:;|$)/i.test(response.headers.get('content-type') || '')) return false;
      const url = global.URL.createObjectURL(blob);
      clips.set(key, {url, text});
      attachClip(sessionId, id, text, container);
      button.textContent = '语音已生成';
      if (typeof onReady === 'function') onReady();
      return true;
    } catch (error) {
      if (isCurrent()) button.textContent = error.message || '语音生成失败，可使用朗读';
      return false;
    } finally { inflight.delete(key); button.disabled = false; }
  }
  global.document?.addEventListener?.('visibilitychange', () => { if (!visible()) stopAll(); });
  global.addEventListener?.('pagehide', stopAll);
  global.document?.addEventListener?.('xinji-topic-change', stopAll);
  global.XinjiVoice = { playMessage, bindMessage, readText, stop: stopAll, configure, bindClipControl, clipEligible, makeClip, attachClip, pruneClips };
})(window);
