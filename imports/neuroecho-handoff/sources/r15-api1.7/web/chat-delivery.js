/* Timed messages are decided and persisted by the server, never by animation. */
(function(root) {
  'use strict';
  function create({state, api, render, stopButton, busy, onError}) {
    let timer = null, generation = 0, polling = false;
    function pending() { return state.messages.some(m => m.role === 'assistant' && m.delivery_pending); }
    function schedule() {
      clearTimeout(timer);
      const waiting = state.messages.filter(m => m.role === 'assistant' && m.delivery_pending);
      if (stopButton) stopButton.classList.toggle('is-hidden', !waiting.length && !busy());
      if (!waiting.length || !state.session) return;
      const delay = Math.min(...waiting.map(m => Number(m.delivery_next_ms) || 800));
      timer = setTimeout(refresh, Math.max(100, Math.min(2000, delay)));
    }
    async function refresh() {
      if (polling || !state.session) return;
      const sid = state.session.id, sequence = generation;
      polling = true;
      try {
        const snapshot = await api('/api/session/' + encodeURIComponent(sid));
        if (sequence !== generation || state.session?.id !== sid) return;
        const remote = new Map((snapshot.messages || []).map(m => [m.id, m]));
        state.messages = state.messages.map(m => remote.get(m.id) || m);
        render();
      } catch (_) {
        if (sequence === generation) { onError?.(); timer = setTimeout(refresh, 2000); }
      } finally { polling = false; }
    }
    async function stop() {
      if (!pending() || !state.session) return;
      const sid = state.session.id;
      const message = [...state.messages].reverse().find(m => m.role === 'assistant' && m.delivery_pending);
      if (!message?.id) return;
      ++generation; clearTimeout(timer);
      try {
        const capabilities = await api('/api/capabilities');
        if (capabilities?.features?.chat_delivery_targeted_stop !== true) throw new Error('当前服务尚不支持按消息停止，请先更新本机服务。');
        const result = await api('/api/session/' + encodeURIComponent(sid) + '/delivery/stop', {method:'POST',body:JSON.stringify({message_id:message.id})});
        if (result?.stopped !== true || result.message_id !== message.id) onError?.(new Error('这段回复未被停止，正在重新核对消息。'));
        if (state.session?.id === sid) { polling = false; await refresh(); }
      } catch (error) { onError?.(error); schedule(); }
    }
    function invalidateReads() { ++generation; clearTimeout(timer); }
    return {schedule, stop, pending, invalidateReads};
  }
  root.XinjiChatDelivery = {create};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.XinjiChatDelivery;
})(typeof window !== 'undefined' ? window : globalThis);
