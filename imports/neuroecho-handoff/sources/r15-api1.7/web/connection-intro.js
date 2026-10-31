/* A connection's first conversation is written by the server, never invented here. */
(() => {
  function create({api, host, getSessionId, canApply, revision, apply}) {
    const key = 'nianxiang_connection_intro_';
    const jobs = new Map();
    let timer = null, stopped = false, reading = false;
    const terminal = status => ['completed', 'failed', 'superseded', 'interrupted'].includes(status);
    const valid = job => job && typeof job.id === 'string' && typeof job.session_id === 'string' &&
      typeof job.source_id === 'string' && ['running','completed','failed','superseded','interrupted'].includes(job.status);
    function remember() {
      try {
        const sid = getSessionId();
        if (!sid) return;
        const ids = [...jobs.values()].filter(job => job.session_id === sid && !job.settled).map(job => job.id);
        if (ids.length) localStorage.setItem(key + sid, JSON.stringify(ids));
        else localStorage.removeItem(key + sid);
      } catch (_) {}
    }
    function render() {
      if (!host) return;
      const pending = [...jobs.values()].filter(job => job.session_id === getSessionId());
      host.replaceChildren();
      host.classList.toggle('is-hidden', pending.length === 0);
      for (const job of pending) {
        const line = document.createElement('p');
        line.className = 'connection-intro-line';
        line.setAttribute('role', 'status');
        line.textContent = job.offline ? '连接已完成，正在核对洞察回复；你可以继续聊。'
          : job.status === 'interrupted' ? '连接已完成，这次整理中断了。可以继续问我。'
          : job.status === 'failed' ? (job.error || '连接已完成，这次整理暂未完成。')
          : job.settled ? (job.error || '连接已完成，暂时无法核对这次整理。可以继续聊。')
          : '已连接，我在看看这次接入的资料… 你可以接着说。';
        host.appendChild(line);
      }
    }
    function schedule(delay = 1100) {
      clearTimeout(timer);
      if (!stopped && [...jobs.values()].some(job => !job.settled)) timer = setTimeout(poll, delay);
    }
    async function poll() {
      if (stopped || reading) return;
      reading = true;
      try {
        for (const [id, before] of jobs) {
          if (before.session_id !== getSessionId()) { jobs.delete(id); continue; }
          if (before.settled) continue;
          try {
            const job = await api(`/api/connections/intro/${encodeURIComponent(id)}?session_id=${encodeURIComponent(before.session_id)}`);
            if (!valid(job) || job.id !== id || job.session_id !== before.session_id) throw Error('未取得有效的整理状态');
            if (!jobs.has(id) || getSessionId() !== job.session_id) continue;
            jobs.set(id, job);
            if (terminal(job.status)) {
              if (job.message_id) {
                if (!canApply()) continue;
                const version = revision();
                const snapshot = await api('/api/conversation');
                if (stopped || !jobs.has(id) || !canApply() || revision() !== version ||
                    getSessionId() !== job.session_id || snapshot?.session?.id !== job.session_id) continue;
                // A simultaneous response must not make a completed job disappear.
                if (!(snapshot.messages || []).some(message => message.id === job.message_id)) continue;
                apply(snapshot);
              }
              if (job.status === 'failed' && !job.message_id || job.status === 'interrupted') {
                job.error = job.error || '这次整理没有完成，你可以继续聊。';
                jobs.set(id, {...job,settled:true});
                // Keep an honest non-blocking status, without replaying the job.
                continue;
              }
              jobs.delete(id);
            }
          } catch (error) {
            if (jobs.has(id)) jobs.set(id, error.status === 404
              ? {...before,settled:true,error:'连接已完成，这次整理记录暂不可用。可以继续问我。'}
              : {...before,offline:true});
          }
        }
        remember(); render();
      } finally { reading = false; schedule(); }
    }
    function start(job) {
      if (job?.id === null && job.status === 'failed' && job.session_id === getSessionId()) {
        jobs.set('creation-error:' + (job.source_id || 'connection'), {...job,settled:true,error:job.error || '连接已完成，这次整理暂未开始。可以继续聊。'});
        remember(); render(); return true;
      }
      if (!valid(job) || job.session_id !== getSessionId()) return false;
      if (!jobs.has(job.id)) jobs.set(job.id, job);
      stopped = false; remember(); render(); schedule(0); return true;
    }
    function resume() {
      stopped = false;
      try {
        const sid = getSessionId(), ids = JSON.parse(localStorage.getItem(key + sid) || '[]');
        if (Array.isArray(ids)) for (const id of ids.slice(0, 12)) {
          if (typeof id === 'string') jobs.set(id, {id,session_id:sid,source_id:'connection',status:'running'});
        }
      } catch (_) {}
      render(); schedule(0);
    }
    return {start, resume, poll, stop() {stopped = true; clearTimeout(timer);}, size: () => jobs.size};
  }
  function connected(context, id) {
    const list = Array.isArray(context?.sources) ? context.sources : context?.connector_id ? [context] : [];
    return list.some(source => source.connector_id === id && source.stale !== true);
  }
  function syncBadges(root, context) {
    root.querySelectorAll('[data-connection-source]').forEach(node => {
      const yes = connected(context, node.dataset.connectionSource);
      node.textContent = yes ? '✓ 已连接' : node.dataset.connectionIdle || '待连接';
      node.classList.toggle('is-connected', yes);
    });
    root.querySelectorAll('[data-connection-control]').forEach(node => {
      const yes = connected(context, node.dataset.connectionControl);
      node.textContent = yes ? '管理' : node.dataset.connectionIdle || '连接';
    });
  }
  window.XinjiConnectionIntro = {create, connected, syncBadges};
})();
