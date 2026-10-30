/* Stable request IDs allow the local app to reconcile response loss safely. */
(() => {
  function chatBody(turn) {
    const value={session_id:turn.session_id,text:turn.text,memory_proposals:!!turn.memory_proposals,request_id:turn.request_id};
    if(Object.hasOwn(turn,'time_zone')) {
      if(typeof turn.time_zone!=='string'||!turn.time_zone)throw new Error('发送时区不完整，原请求保留，请核对。');
      value.time_zone=turn.time_zone;
    }
    return value;
  }
  // One local, plaintext recovery ledger per renderer surface. It is not a
  // cross-device sync service. Queued text and claimed requests are separate:
  // opening the app may restore a draft, but must never submit it.
  function createLedger(surface, providedStorage) {
    const key = 'xinji_chat_ledger_v1_' + surface;
    const clone = value => JSON.parse(JSON.stringify(value));
    const failure = () => Object.assign(new Error('无法保存本机发送记录。请先复制待发内容并检查浏览器存储，再发送。'), {localPersistence:true});
    function storage() { return providedStorage || globalThis.localStorage; }
    function read() {
      try {
        const raw = storage().getItem(key);
        if (!raw) return {version:1, queued:[], pending:[], drafts:{}};
        const value = JSON.parse(raw);
        if (value.version !== 1 || !Array.isArray(value.queued) || !Array.isArray(value.pending) || !value.drafts || typeof value.drafts !== 'object') throw failure();
        if (value.queued.some(p => !p.id || !p.sessionId || typeof p.text !== 'string') ||
            value.pending.some(p => !p.request_id || !p.session_id || typeof p.text !== 'string' || !Array.isArray(p.parts))) throw failure();
        return value;
      } catch (_) { throw failure(); }
    }
    function write(value) {
      try { storage().setItem(key, JSON.stringify(value)); }
      catch (_) { throw failure(); }
    }
    const payload = chatBody;
    function restore(sessionId, fallbackDraft = '') {
      const value = read(), waiting = value.queued.filter(p => p.sessionId === sessionId);
      const draft = Object.hasOwn(value.drafts, sessionId) ? value.drafts[sessionId] : fallbackDraft;
      const text = [...waiting.map(p => p.text), draft].filter(Boolean).join('\n');
      value.drafts[sessionId] = text;
      value.queued = value.queued.filter(p => p.sessionId !== sessionId);
      // Persist the restored draft and consume the queue in the same write, so
      // closing between these steps cannot lose or duplicate the queued text.
      write(value);
      return {draft:text, pending:clone(value.pending.filter(p => p.session_id === sessionId)), restored:waiting.length};
    }
    return {
      snapshot: () => clone(read()), restore,
      saveDraft(sessionId, text) { const value=read(); value.drafts[sessionId]=text; write(value); },
      enqueue(part) {
        const value=read(); value.queued.push(clone(part)); value.drafts[part.sessionId]=''; write(value);
      },
      begin(turn, parts = []) {
        const value=read(), existing=value.pending.find(p => p.request_id === turn.request_id);
        if (existing && JSON.stringify(payload(existing)) !== JSON.stringify(payload(turn))) throw failure();
        if (value.pending.some(p => p.session_id === turn.session_id && p.request_id !== turn.request_id)) {
          const error=failure(); error.message='还有一次发送尚未核对，请先重新打开页面核对发送状态。'; throw error;
        }
        const ids=new Set(parts.map(p => p.id));
        value.queued=value.queued.filter(p => !ids.has(p.id));
        if (!existing) value.pending.push({...payload(turn), parts:clone(parts), cancelWanted:!!turn.cancelWanted});
        write(value);
      },
      cancelWanted(turn) {
        const value=read(), pending=value.pending.find(p => p.request_id === turn.request_id);
        if (pending) { pending.cancelWanted=true; write(value); }
      },
      settle(turn) {
        const value=read(); value.pending=value.pending.filter(p => p.request_id !== turn.request_id); write(value);
      },
      returnDraft(sessionId, text, requestId = null) {
        const value=read(); value.drafts[sessionId]=text;
        value.queued=value.queued.filter(p => p.sessionId !== sessionId);
        if (requestId) value.pending=value.pending.filter(p => p.request_id !== requestId);
        write(value);
      },
    };
  }

  function create(api, options = {}) {
    const pause = options.pause || (ms => new Promise(resolve => setTimeout(resolve, ms)));
    const attempts = options.attempts || 15;
    const active = new Map();
    const base = turn => '/api/chat/turn/' + encodeURIComponent(turn.request_id);
    const requestId = () => (globalThis.crypto?.randomUUID?.() || 'turn-' + Date.now() + '-' + Math.random().toString(36).slice(2));
    async function cancel(turn) {
      turn.cancelWanted = true;
      try { options.ledger?.cancelWanted(turn); } catch (_) { /* The original pending record remains queryable. */ }
      try {
        const record = await api(base(turn) + '/cancel', {method:'POST', body:JSON.stringify({session_id:turn.session_id})});
        return record;
      } catch (_) { return null; }
    }
    function unwrap(record) {
      if (record.result) return record.result;
      const error = new Error(record.status === 'unknown'
        ? '连接中断，服务端无法确定这次回复是否完成。请核对当前对话后继续。'
        : '未能确认发送状态，请检查连接后再核对。');
      error.uncertain = true;
      error.code = record.error_code;
      if (record.error_code === 'budget_exceeded') error.status = 429;
      throw error;
    }
    function isBusyNotAccepted(turn, record) {
      return !!record && !record.result && record.status === 'unknown' &&
        record.error_code === 'conversation_busy_not_accepted' &&
        record.request_id === turn.request_id && record.session_id === turn.session_id;
    }
    function busyError() {
      return Object.assign(new Error('回响正在处理上一条，这条尚未发送'),
        {notSent:true, busyNotAccepted:true});
    }
    async function recover(turn, onStatus = () => {}, settle = true) {
      onStatus('连接中断，正在核对保存状态…');
      for (let i = 0; i < attempts; i++) {
        try {
          const record = await api(base(turn) + '?session_id=' + encodeURIComponent(turn.session_id));
          // A stop request never authorizes settling a different turn. Only a
          // GET receipt for the exact session and request can finish recovery.
          if (turn.cancelWanted && (record?.request_id !== turn.request_id || record?.session_id !== turn.session_id)) {
            const error = new Error('停止后的状态无法核对到原请求，请稍后重试。');
            error.uncertain = true;
            throw error;
          }
          if (isBusyNotAccepted(turn, record)) throw busyError();
          if (record.result) {
            const result=unwrap(record);
            if (settle) options.ledger?.settle(turn);
            if (turn.cancelWanted && !result.cancelled && result.action !== 'safety') onStatus('服务端已完成这次回复；停止未生效。');
            return result;
          }
          if (record.status === 'unknown') return unwrap(record);
          onStatus(record.cancel_requested ? '正在停止旧回复…' : '正在等待服务端完成，可继续补充…');
        } catch (error) {
          if (error.uncertain || error.notSent || error.status === 429 || error.localPersistence) throw error;
          // A 404 does not prove the initial request will never arrive. Keep
          // the same ID and let an explicit retry reconcile it later.
        }
        await pause(1000);
      }
      return unwrap({status:'unconfirmed'});
    }
    async function send(turn, onStatus = () => {}, parts = []) {
      turn.request_id ||= requestId();
      // This write must succeed before the first network call and before the
      // renderer may regard the text as submitted.
      try { options.ledger?.begin(turn, parts); }
      catch (error) { error.notSent=true; throw error; }
      active.set(turn.request_id, turn);
      try {
        let result;
        try {
          result = await api('/api/chat', {method:'POST', body:JSON.stringify(chatBody(turn))});
        } catch (error) {
          if (error.status === 409 && isBusyNotAccepted(turn, error.payload)) throw busyError();
          if ([400,422,429].includes(error.status)) error.notSent = true;
          if (error.status && error.status < 500) throw error;
          result = await recover(turn, onStatus, false);
        }
        if (!Array.isArray(result.messages)) result = result.result || await recover(turn, onStatus, false);
        if (turn.cancelWanted && !result.cancelled && result.action !== 'safety') {
          const cancelled = await cancel(turn);
          if (cancelled?.result) result = cancelled.result;
          else {
            const error = new Error('停止结果尚未确认，请核对发送状态。');
            error.uncertain = true;
            throw error;
          }
        }
        options.ledger?.settle(turn);
        return result;
      } finally { active.delete(turn.request_id); }
    }
    return {send, cancel, recover, requestId};
  }
  globalThis.XinjiChatTransport = {create, createLedger};
})();
