/* Memory overview: a local view over the existing, editable memory records. */
(() => {
  'use strict';
  const categories = [
    { id: 'projects', label: '项目与工作', icon: '▤', color: 'peach', match: /项目|工作|团队|会议|产品|开发|设计|project|work|meeting/i },
    { id: 'preferences', label: '偏好与习惯', icon: '♡', color: 'blue', match: /喜欢|偏好|习惯|不喜欢|倾向|prefer|favo(?:u)?rite/i },
    { id: 'life', label: '生活与经历', icon: '◌', color: 'lilac', match: /生活|家庭|朋友|旅行|家人|城市|居住|life|travel/i },
    { id: 'health', label: '健康与状态', icon: '✳', color: 'coral', match: /健康|睡眠|运动|身体|心情|情绪|health|sleep/i },
    { id: 'other', label: '其他记忆', icon: '◇', color: 'sand' }
  ];
  const byId = new Map(categories.map(item => [item.id, item]));
  const storageKey = 'xinji.memory.category.v1';
  function readPreferences() {
    try { const value = JSON.parse(localStorage.getItem(storageKey) || '{}'); return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; } catch (_) { return {}; }
  }
  function writePreferences(value) { try { localStorage.setItem(storageKey, JSON.stringify(value)); return true; } catch (_) { return false; } }
  function suggestion(record) {
    const text = String(record.text || '');
    return categories.find(category => category.match?.test(text))?.id || 'other';
  }
  function isPersonalExcerpt(record) {
    if (!['confirmed', 'auto'].includes(record.status) || record.kind !== 'fact') return false;
    if (/撤回后来源待核对|来源待核对/.test([record.source, record.source_label].filter(Boolean).join(' '))) return false;
    const text = String(record.text || '').trim();
    if (!text) return false;
    // Automatic records enter only through trusted user-authored channels. Their
    // wording need not repeat a narrow set of first-person grammatical patterns.
    if (record.status === 'auto') return ['对话原话 · 自动记录', '对话原话 · 用户选存', '对话原话 · 用户纠正', '用户手动添加'].includes(record.source);
    // An explicitly confirmed fact can also come from an authorized source.
    // It is presented as a sourced record, never as an inferred personal trait.
    return record.status === 'confirmed';
  }
  function excerpt(text) {
    const chars = Array.from(String(text || '').trim());
    return chars.length > 150 ? chars.slice(0, 150).join('') + '…' : chars.join('');
  }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function mount({ list }) {
    if (!list || !list.parentNode) return null;
    const overview = element('div', 'memory-overview');
    const toolbar = element('div', 'memory-overview-toolbar');
    const back = element('button', 'memory-overview-back', '← 返回记忆概览');
    back.type = 'button'; back.dataset.memoryBack = '';
    const heading = element('h4', 'memory-overview-list-title');
    toolbar.append(back, heading);
    list.parentNode.insertBefore(overview, list);
    list.parentNode.insertBefore(toolbar, list);
    let records = [], sources = null, session = '', view = null;
    let modelSummary = null, summaryMessage = '', generating = false, revision = 0, currentFingerprint = '';
    const accountStatus = element('p', 'memory-summary-account');
    accountStatus.setAttribute('role', 'status'); accountStatus.hidden = true;
    const selected = new Set();
    let preferences = readPreferences();
    function preference(record) { return preferences[session]?.[String(record.id)]; }
    function categoryFor(record) { const stored = preference(record); return byId.has(stored) ? stored : suggestion(record); }
    function activeRecords() { return records.filter(item => item && item.status !== 'deleted'); }
    function sampleSource(source) {
      return source && (source.connector_id === 'sample' || source.label === '示例资料');
    }
    function sourceAvailable(record) {
      if (record.source === '示例资料' || record.source_label === '示例资料') return false;
      if (!record.source_attachment_id || sources === null) return true;
      return sources.some(source => source.id === record.source_attachment_id && !source.stale && !sampleSource(source));
    }
    function known(record) { return window.XinjiMemoryInsights.known(record, sources); }
    function reviewRecords() { return window.XinjiMemoryInsights.review(activeRecords(), sources); }
    function inView(record, target) {
      if (target === 'pending') return reviewRecords().slice(0, 5).includes(record);
      if (target === 'all') return true;
      if (target === 'other' && !known(record)) return !reviewRecords().slice(0, 5).includes(record);
      return known(record) && categoryFor(record) === target;
    }
    function fingerprint() {
      return JSON.stringify([session, activeRecords().map(record => [String(record.id), record.version, record.status, record.kind, record.text, record.source, record.source_label, record.source_attachment_id, sourceAvailable(record)]).sort((a, b) => a[0].localeCompare(b[0]))]);
    }
    function availableInputs() {
      return activeRecords().filter(record => known(record) && record.id && Number.isInteger(record.version) && record.version > 0)
        .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
    }
    function summaryInputs() { return availableInputs().filter(record => selected.has(String(record.id))); }
    async function generateSummary() {
      if (generating || !session) return;
      const inputs = summaryInputs();
      if (!inputs.length || inputs.length > 20 || inputs.reduce((sum, record) => sum + Array.from(String(record.text)).length, 0) > 12000) return;
      const requestedRevision = revision, requestedSession = session;
      const message = `将把下方可核对的 ${inputs.length} 条你手动添加、自动记录或已确认的记忆的完整内容和来源发送给当前配置的模型服务（可能在云端），用于生成认识总结。是否继续？`;
      generating = true; summaryMessage = ''; renderOverview();
      try {
        const approved = window.XinjiDialogs?.confirm
          ? await window.XinjiDialogs.confirm({title: '生成认识总结', message, confirmLabel: '同意发送并生成'})
          : window.confirm(message);
        if (!approved || requestedRevision !== revision || requestedSession !== session) return;
        summaryMessage = '正在生成，请稍候…'; renderOverview();
        const response = await fetch('/api/memory/summary', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({session_id: requestedSession, confirm: true, memories: inputs.map(record => ({id: record.id, version: record.version}))})
        });
        const data = await response.json().catch(() => ({}));
        if (requestedRevision !== revision || requestedSession !== session) return;
        if (!response.ok) {
          const detail = typeof data.detail === 'string' ? data.detail : '';
          throw new Error(response.status === 403 ? '认识总结目前仅在本机使用。' : detail || (response.status === 409 ? '记忆已变化，请重新核对后再试。' : '模型暂时不可用，请检查当前模型配置后再试。'));
        }
        if (typeof data.summary !== 'string' || !data.summary.trim() || !Array.isArray(data.evidence)) throw new Error('没有收到可核对的总结，请稍后再试。');
        const wanted = new Set(inputs.map(record => `${record.id}\u0000${record.version}`));
        const received = new Set(data.evidence.map(record => `${record.id}\u0000${record.version}`));
        if (data.evidence.length !== inputs.length || received.size !== wanted.size || [...received].some(key => !wanted.has(key))) throw new Error('总结依据不完整，请重新核对记忆后再试。');
        modelSummary = {text: data.summary, evidence: data.evidence}; summaryMessage = '';
      } catch (error) {
        if (requestedRevision === revision && requestedSession === session) summaryMessage = error.message || '模型暂时不可用，请稍后再试。';
      } finally {
        if (requestedRevision === revision && requestedSession === session) { generating = false; renderOverview(); }
      }
    }
    function open(id) { view = id; applyView(); toolbar.querySelector('h4').focus?.(); }
    function showAll() { open('all'); }
    function applyView() {
      const active = activeRecords();
      const recordMap = new Map(active.map(record => [String(record.id), record]));
      overview.hidden = view !== null;
      toolbar.hidden = view === null;
      list.hidden = view === null;
      heading.textContent = view === 'all' ? '全部记忆' : view === 'pending' ? '待核对' : byId.get(view)?.label || '记忆';
      heading.tabIndex = -1;
      list.querySelectorAll('.mem-item[data-id]').forEach(card => {
        const record = recordMap.get(card.dataset.id);
        card.hidden = !record || !inView(record, view);
      });
      let empty = list.querySelector('.memory-overview-empty');
      if (!empty) { empty = element('p', 'memory-overview-empty', '这个分类还没有记忆。'); list.append(empty); }
      const matches = active.filter(record => inView(record, view));
      empty.hidden = view === null || matches.length > 0 || (view === 'all' && !active.length);
    }
    function addSelectors() {
      const recordMap = new Map(activeRecords().map(record => [String(record.id), record]));
      list.querySelectorAll('.mem-item[data-id]').forEach(card => {
        const record = recordMap.get(card.dataset.id);
        if (!record) return;
        const existing = card.querySelector('.memory-category-control');
        if (existing) {
          existing.querySelector('select').value = categoryFor(record);
          existing.querySelector('.memory-category-hint').textContent = preference(record) ? '已在本机调整' : '建议分类，可调整';
          return;
        }
        const control = element('details', 'memory-category-control');
        control.append(element('summary', '', '调整分类'));
        const picker = element('label', 'memory-category-picker');
        const label = element('span', '', '分类');
        const select = element('select', 'memory-category-select');
        select.setAttribute('aria-label', '调整这条记忆的分类');
        select.dataset.memoryCategory = '';
        for (const category of categories) {
          const option = element('option', '', category.label); option.value = category.id; select.append(option);
        }
        select.value = categoryFor(record);
        const hint = element('small', 'memory-category-hint', preference(record) ? '已在本机调整' : '建议分类，可调整');
        select.addEventListener('change', () => {
          const choice = select.value;
          if (!byId.has(choice)) return;
          preferences = readPreferences();
          if (!preferences[session] || typeof preferences[session] !== 'object') preferences[session] = {};
          preferences[session][String(record.id)] = choice;
          const saved = writePreferences(preferences);
          hint.textContent = saved ? '已在本机调整' : '当前页面已调整，无法保存到本机';
          renderOverview(); applyView();
        });
        picker.append(label, select, hint);
        control.append(picker);
        card.append(control);
      });
    }
    function renderOverview() {
      const active = activeRecords();
      const confirmed = active.filter(known);
      const pending = active.filter(record => !known(record)).length;
      overview.replaceChildren();
      const summary = element('section', 'memory-summary');
      const kicker = element('div', 'memory-summary-kicker', '✦  慢慢认识你');
      const title = element('h4', 'memory-summary-title', '我对你的了解');
      summary.append(kicker, title);
      const lines = window.XinjiMemoryInsights.summary(active, sources);
      if (lines.length) {
        const excerpts = element('ul', 'memory-summary-excerpts');
        lines.forEach(line => excerpts.append(element('li', '', line)));
        summary.append(excerpts);
      } else {
        summary.append(element('p', 'memory-summary-intro', '聊得越多，我会慢慢记住对你重要的事。'));
      }
      overview.append(summary);
      const reviewable = reviewRecords();
      if (reviewable.length) {
        const review = element('button', 'memory-review-link', `有 ${Math.min(reviewable.length, 5)} 条想请你确认 →`);
        review.type = 'button'; review.dataset.memoryPending = ''; review.addEventListener('click', () => open('pending'));
        overview.append(review);
      }
      const row = element('div', 'memory-overview-section');
      row.append(element('h4', '', '分类'), element('span', '', '建议分类，可调整'));
      overview.append(row);
      const grid = element('div', 'memory-category-grid');
      categories.forEach(category => {
        const count = active.filter(record => inView(record, category.id)).length;
        const button = element('button', `memory-category-card is-${category.color}`); button.type = 'button'; button.dataset.memoryGroup = category.id;
        const icon = element('span', 'memory-category-icon', category.icon); icon.setAttribute('aria-hidden', 'true');
        button.append(icon, element('strong', '', category.id === 'other' ? '其他记录' : category.label), element('span', 'memory-category-count', category.id === 'other' ? '查看详情' : `${count} 条记忆`));
        button.addEventListener('click', () => open(category.id)); grid.append(button);
      });
      overview.append(grid);

    }
    back.addEventListener('click', () => { view = null; applyView(); overview.querySelector('[data-memory-all]')?.focus(); });
    return {
      render(nextRecords, sessionId, nextSources) {
        const nextSession = String(sessionId || '');
        if (session !== nextSession) { session = nextSession; view = null; accountStatus.textContent = ''; accountStatus.hidden = true; }
        records = Array.isArray(nextRecords) ? nextRecords : [];
        sources = Array.isArray(nextSources) ? nextSources : null;
        const nextFingerprint = fingerprint();
        if (nextFingerprint !== currentFingerprint) {
          const wasActive = !!modelSummary || generating;
          currentFingerprint = nextFingerprint; revision++; modelSummary = null; generating = false; selected.clear();
          summaryMessage = wasActive ? '记忆已变化，原总结已失效，请重新核对后生成。' : '';
        }
        preferences = readPreferences();
        // A render receives the current authoritative session snapshot. Drop local
        // labels for records that have been deleted or withdrawn from this session.
        const saved = preferences[session];
        if (session && saved && typeof saved === 'object' && !Array.isArray(saved)) {
          const ids = new Set(activeRecords().map(record => String(record.id)));
          let changed = false;
          Object.keys(saved).forEach(id => { if (!ids.has(id)) { delete saved[id]; changed = true; } });
          if (!Object.keys(saved).length) { delete preferences[session]; changed = true; }
          if (changed) writePreferences(preferences);
        }
        renderOverview(); addSelectors(); applyView();
      },
      showAll,
      setAccountStatus() {}
    };
  }
  window.XinjiMemoryOverview = { mount };
})();
