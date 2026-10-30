/* Per-tab suggestions; an explicit "remember this quote" confirms the literal quote. */
window.createMemoryProposal = function ({box, toggle, state, api, toast, refresh}) {
  const lastOffered = new Map(), ignored = new Map();
  let pending = null;
  try { toggle.checked = localStorage.getItem('xinji_memory_proposals') === 'on'; }
  catch (_) { toggle.checked = false; }
  toggle.onchange = () => {
    try { localStorage.setItem('xinji_memory_proposals', toggle.checked ? 'on' : 'off'); } catch (_) {}
    if (!toggle.checked) clear();
  };
  function clear() { pending = null; box.replaceChildren(); box.classList.add('is-hidden'); }
  function sync() { if (pending && state.session?.id !== pending.sid) clear(); }
  function shouldRequest(sid) {
    sync();
    const count = state.messages.filter(m => m.role === 'user').length;
    return toggle.checked && state.session?.id === sid && !pending && count >= 3 && count - (lastOffered.get(sid) || 0) >= 3 && (!lastOffered.has(sid) || count - lastOffered.get(sid) >= 8);
  }
  function offer(sid, result) {
    const proposal = result.memory_proposal;
    if (!toggle.checked || !proposal || state.session?.id !== sid || pending) return;
    const key = proposal.quote;
    if (ignored.get(sid)?.has(key)) return;
    lastOffered.set(sid, state.messages.filter(m => m.role === 'user').length);
    const offered = pending = {sid, ...proposal};
    const isCurrent = () => pending === offered && state.session?.id === sid;
    const heading = document.createElement('div');
    heading.textContent = '这句偏好，要留下吗？';
    const quote = document.createElement('blockquote');
    quote.textContent = proposal.quote;
    quote.style.margin = '5px 0';
    const hint = document.createElement('div');
    hint.textContent = '只保存下面这句原话；确认后，回响在之后聊天时可能参考它。你可以在「记忆」里修改或删除。';
    const save = document.createElement('button');
    save.type = 'button'; save.className = 'mini-btn confirm'; save.textContent = '记住这句';
    const dismiss = document.createElement('button');
    dismiss.type = 'button'; dismiss.className = 'mini-btn'; dismiss.textContent = '不用';
    dismiss.onclick = () => {
      if (!ignored.has(sid)) ignored.set(sid, new Set());
      ignored.get(sid).add(key); clear();
    };
    save.onclick = async () => {
      if (!isCurrent() || save.disabled) return;
      save.disabled = true;
      const finish = (saved, memories) => {
        if (!isCurrent()) return;
        if (memories) state.memories = memories;
        else state.memories = [...state.memories.filter(m => m.id !== saved.id), saved];
        refresh(); clear(); toast('已记住这句，可在「记忆」中修改或删除');
      };
      try {
        const saved = await api('/api/memory/proposal', {method:'POST', body:JSON.stringify({session_id:sid, message_id:proposal.message_id, confirm:true})});
        if (!isCurrent()) return;
        if (saved.status !== 'confirmed' || saved.kind !== 'fact' || saved.text !== proposal.quote
            || saved.source !== '对话原话 · 用户选存' || saved.source_message_id !== proposal.message_id) {
          hint.textContent = '尚未确认保存，请到「记忆」中查看状态。';
          toast('尚未确认保存，请查看记忆列表');
          return;
        }
        finish(saved);
      } catch (e) {
        if (!isCurrent()) return;
        if (e.status >= 400 && e.status < 500) {
          save.disabled = false; toast(`未保存：${e.message}`); return;
        }
        // The POST may have committed. Reconcile once; never blindly POST again.
        try {
          const latest = await api('/api/memory?session_id=' + encodeURIComponent(sid));
          if (!isCurrent()) return;
          const saved = latest.memories.find(m => m.status === 'confirmed' && m.kind === 'fact'
            && m.source_message_id === proposal.message_id && m.text === proposal.quote
            && m.source === '对话原话 · 用户选存');
          if (saved) { finish(saved, latest.memories); return; }
        } catch (_) { /* A missing receipt is not evidence of a failed write. */ }
        if (!isCurrent()) return;
        hint.textContent = '保存状态还不能确认，请先到「记忆」中查看，避免重复操作。';
        dismiss.textContent = '稍后查看';
        toast('保存状态未知，请查看记忆列表；没有再次提交');
      }
    };
    box.replaceChildren(heading, quote, hint, save, dismiss); box.classList.remove('is-hidden');
  }
  return {shouldRequest, offer, sync};
};
