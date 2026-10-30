/* Additive local-service contracts. No background writes or automatic retries. */
(() => {
  const contracts = new WeakMap();
  async function requireVersion(api, operation) {
    let request = contracts.get(api);
    if (!request) {
      request = api('/api/capabilities');
      contracts.set(api, request);
      request.catch(() => contracts.delete(api));
    }
    const metadata = await request;
    if (metadata?.features?.[`memory_expected_version_${operation}`] !== true) {
      const error = new Error('当前服务尚不支持记忆版本核对。草稿已保留，请更新本机服务后再保存。');
      error.code = 'memory_version_unsupported';
      throw error;
    }
  }
  function versionOf(memory) {
    if (!Number.isInteger(memory?.version) || memory.version < 1) throw new Error('尚未读到这条记忆的版本，请重新读取后再修改。');
    return memory.version;
  }
  window.XinjiMemorySync = {
    async patch(api, memory, patch) {
      const expected_version = versionOf(memory);
      await requireVersion(api, 'patch');
      return api(`/api/memory/${encodeURIComponent(memory.id)}`, {method:'PATCH', body:JSON.stringify({...patch, expected_version})});
    },
    async remove(api, memory) {
      const version = versionOf(memory);
      await requireVersion(api, 'delete');
      return api(`/api/memory/${encodeURIComponent(memory.id)}?expected_version=${version}`, {method:'DELETE'});
    },
    isConflict(error) { return error?.status === 409 && error?.code === 'memory_version_conflict'; },
  };

  // The cursor is a read acknowledgement, not a write receipt. It lives only
  // in this page and is committed after a stable, identity-matching snapshot.
  const changeDomains = new Set(['conversation','messages','memories','sources','moods','followups','boundary','actions','turns']);
  function validChanges(value, conversation) {
    return value && typeof value.service_instance_id === 'string' && value.service_instance_id.length > 0 &&
      value.conversation_id === conversation && typeof value.cursor === 'string' && value.cursor.length > 0 && value.cursor.length <= 2048 &&
      typeof value.reset_required === 'boolean' && Array.isArray(value.domains) &&
      value.domains.every(domain => changeDomains.has(domain)) && new Set(value.domains).size === value.domains.length &&
      (value.reset_required || value.domains.length === 0 || value.domains.length <= changeDomains.size);
  }
  window.XinjiContentUpdates = {
    validChanges,
    create({api, identity, revision, canApply, visible = () => !document.hidden, read, apply, onState = () => {},
      intervalMs = 15000, deadlineMs = 12000, setTimer = setTimeout, clearTimer = clearTimeout, clock = Date.now}) {
      let cursor = null, instance = null, owner = null, running = false, stopped = true, timer = null,
        active = null, attempt = 0, failures = 0, last = -Infinity, supported = null;
      const emit = kind => onState(kind);
      const same = (id, gen) => !stopped && attempt === gen && identity() === id && visible();
      function schedule(delay) { clearTimer(timer); timer = null; if (!stopped && visible()) timer = setTimer(() => { timer = null; void check(); }, delay); }
      async function check() {
        if (stopped || running || !visible() || clock() - last < 1500) return false;
        const id = identity(); if (!id) return false;
        if (id !== owner) { owner = id; cursor = null; instance = null; supported = null; failures = 0; }
        running = true; last = clock(); const gen = ++attempt, localRevision = revision();
        const control = new AbortController(); active = control;
        let rejectDeadline;
        const expired = new Promise((_, reject) => { rejectDeadline = reject; });
        const deadline = setTimer(() => { control.abort(); rejectDeadline(Error('update_read_timeout')); }, deadlineMs);
        const get = (path) => Promise.race([api(path, {signal:control.signal, cache:'no-store'}), expired]);
        try {
          if (supported === null) {
            const capabilities = await get('/api/capabilities');
            if (!same(id, gen)) return false;
            supported = capabilities?.features?.conversation_change_cursor === true;
          }
          if (!supported) { emit('unsupported'); return false; }
          const path = '/api/conversation/changes' + (cursor ? '?after=' + encodeURIComponent(cursor) : '');
          const changes = await get(path);
          if (!same(id, gen)) return false;
          if (!validChanges(changes, id)) throw Error('invalid_changes_receipt');
          // A live service identity changing is quarantined, never auto-migrated.
          if (instance && changes.service_instance_id !== instance) { emit('identity'); return false; }
          if (!changes.reset_required && !changes.domains.length) { cursor = changes.cursor; instance = changes.service_instance_id; failures = 0; emit('idle'); return true; }
          if (!canApply() || revision() !== localRevision) { emit('pending'); return false; }
          const snapshot = await Promise.race([read(changes, get), expired]);
          if (!same(id, gen) || !canApply() || revision() !== localRevision) { if (same(id, gen)) emit('pending'); return false; }
          const afterRead = await get('/api/conversation/changes?after=' + encodeURIComponent(changes.cursor));
          if (!same(id, gen)) return false;
          if (!validChanges(afterRead, id) || afterRead.service_instance_id !== changes.service_instance_id) throw Error('invalid_changes_receipt');
          if (afterRead.reset_required || afterRead.domains.length || afterRead.cursor !== changes.cursor || !canApply() || revision() !== localRevision) { emit('pending'); return false; }
          // apply is synchronous: all validation happens before this publication.
          if (apply(snapshot, changes) === false) { emit('pending'); return false; }
          cursor = changes.cursor; instance = changes.service_instance_id; failures = 0; emit('updated'); return true;
        } catch (error) {
          if (same(id, gen)) { failures++; emit('offline'); }
          return false;
        } finally {
          clearTimer(deadline);
          // A stopped attempt may finish after a newer start. It cannot own or
          // release that new attempt's controller or scheduling slot.
          if (active === control) { active = null; running = false; schedule(gen !== attempt ? 0 : Math.min(120000, intervalMs * 2 ** Math.min(failures, 3))); }
        }
      }
      function suspend() { attempt++; clearTimer(timer); timer = null; if (active) active.abort(); }
      return {
        start() { stopped = false; last = -Infinity; void check(); },
        stop() { stopped = true; suspend(); },
        visibilityChanged() { suspend(); if (!stopped && visible()) { last = -Infinity; void check(); } },
        check,
        // Cursor is deliberately not persisted across service/page lifecycles.
        state() { return {cursor, instance, running, supported}; },
      };
    },
    async snapshot(id, get, {today = false} = {}) {
      const q = '?session_id=' + encodeURIComponent(id);
      const [conversation,moods,followups,boundary,actions,next] = await Promise.all([
        get('/api/conversation'), get('/api/moods' + q), get('/api/followups' + q),
        get('/api/companion-boundary' + q), get('/api/actions' + q), today ? get('/api/next-step' + q) : Promise.resolve(null),
      ]);
      if (conversation?.session?.id !== id || !Array.isArray(conversation.messages) || !Array.isArray(conversation.memories) ||
        !Array.isArray(moods?.moods) || moods.moods.some(item => !window.XinjiMood.entryValid(item)) || new Set(moods.moods.map(item=>item.date)).size !== moods.moods.length ||
        !Array.isArray(followups?.followups) || followups.followups.some(item=>item?.session_id!==id) ||
        !window.XinjiContactContract.validBoundary(boundary) || !Array.isArray(actions?.actions)) throw Error('incomplete_update_snapshot');
      return {conversation,moods,followups,boundary,actions,next};
    },
    mountStatus(host, check) {
      if (!host) return () => {};
      const button = host.querySelector('[data-update-check]'), status = host.querySelector('[data-update-status]');
      const copy = (key, fallback) => window.EchoShared?.copy?.[key] || fallback;
      button.textContent = copy('connection.sync.check', '检查更新'); button.onclick = check;
      return kind => {
        const texts = {pending:copy('connection.sync.pending','有新内容，先保留你正在编辑的部分。'),
          updated:copy('connection.sync.updated','内容已更新。'), offline:copy('connection.sync.offline','暂时没能接上更新，草稿仍保留。'),
          unsupported:copy('connection.sync.unsupported','当前服务暂不支持自动更新，可以手动重新读取。'),
          identity:'服务已更换，请先核对连接。当前草稿仍保留。'};
        // An unchanged poll does not erase a useful update/error message.
        if (kind !== 'idle') status.textContent = texts[kind] || '';
        host.dataset.updateState = kind;
      };
    },
  };

  window.XinjiForegroundSync = {
    create({read, apply, canRefresh, version = () => null, onFailure = () => {}, clock = Date.now}) {
      let active = false, last = -Infinity;
      return async function refresh() {
        if (active || !canRefresh() || clock() - last < 1500) return false;
        active = true; last = clock();
        const previousVersion = version();
        try {
          const snapshot = await read();
          // A reply, source import or editor may have opened while reading.
          if (!canRefresh() || version() !== previousVersion) return false;
          apply(snapshot);
          return true;
        } catch (error) { onFailure(error); return false; }
        finally { active = false; }
      };
    },
    draft(input, surface, storage = localStorage) {
      const key = `xinji_composer_draft_v1_${surface}`;
      const save = () => { try { storage.setItem(key, input.value); } catch (_) {} };
      try { if (!input.value) input.value = storage.getItem(key) || ''; } catch (_) {}
      input.addEventListener('input', save);
      // Picks up programmatically inserted text as well as normal typing.
      window.addEventListener('pagehide', save);
      document.addEventListener('visibilitychange', () => { if (document.hidden) save(); });
      return {save};
    },
  };
})();
