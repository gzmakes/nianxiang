/* Consent-based local follow-ups; bounded presentation is separately opt-in. */
window.XinjiFollowups = (() => {
  const copy = (key,fallback) => window.EchoShared?.copy?.[key] ?? fallback;
  const legacyKey = 'xinji_followup_pending_v1';
  // Server policy is the only notification switch and cross-client deduplication authority.
  const settingFields = ['time_zone','quiet_start','quiet_end','cooldown_minutes','daily_limit','pause_until'];
  const desktop = () => !!window.xinjiDesktop;
  const browserSupport = () => !!globalThis.Notification && typeof globalThis.Notification.requestPermission === 'function';
  function notificationStatus(settings) {
    if (!desktop() && !browserSupport()) return 'unsupported';
    if (!settings || typeof settings.enabled !== 'boolean') return 'unavailable';
    if (!settings.enabled) return 'off';
    if (!desktop() && globalThis.Notification.permission === 'denied') return 'denied';
    if (!desktop() && globalThis.Notification.permission !== 'granted') return 'permission';
    return 'enabled';
  }
  function settingsBody(settings, session, overrides = {}) {
    const body = {session_id:session, enabled:settings.enabled, expected_revision:settings.revision};
    for (const key of settingFields) body[key] = settings[key];
    return {...body, ...overrides};
  }
  function followupTime(item) {
    const due = new Date(item.due_at), explicitZone = typeof item.time_zone === 'string' && item.time_zone.trim();
    if (Number.isNaN(due.getTime())) return '时间无法读取';
    const zone = explicitZone || 'UTC';
    try { return due.toLocaleString('zh-CN', {dateStyle:'medium', timeStyle:'short', timeZone:zone}) + ' · ' + zone + (explicitZone ? '' : '（原时区未提供）'); }
    catch (_) { return '时间无法读取（跟进时区无效）'; }
  }
  function contactStatus(item) {
    if (item.allow_contact !== true) return null;
    const reason = item.contact_reason;
    if (['boundary_changed','suppressed_occurrence','boundary_paused','boundary_until'].includes(reason)) return '轻问许可已失效，需重新约定；事项仍可查看。';
    if (reason === 'expired') return copy('followup.contact.expired','窗口已过，不再补问') + '；若还需要轻问，请重新约定。';
    if (['quiet','item_quiet','paused'].includes(reason)) return '当前处于安静或临时暂停时段，不会轻问；窗口过后不补问。';
    if (reason === 'item_paused') return '这条跟进已暂停，不会轻问；继续后仍需符合窗口和当前许可。';
    if (['already_claimed','topic_window_claimed'].includes(reason)) return '本窗口已有一次联系尝试，不再重复；事项仍可查看。';
    if (['cooldown','daily_limit'].includes(reason)) return '当前达到提示频率上限，暂不轻问；窗口过后不补问。';
    if (reason === 'not_due') return '还没到约定时间；届时仍需符合当前许可与安静规则。';
    if (reason == null && item.contact_eligible === true) return '仅在本次窗口和当前许可均有效时尝试一次；错过不补问。';
    return '当前不会主动轻问，请核对关心设置；事项仍可查看。';
  }
  function create({api, getSessionId, surface = 'web'}) {
    const storageKey = 'xinji_followup_pending_v2_' + surface;
    let host = null, sid = null, epoch = 0, timer = null, sequence = 0, notificationSettings = null, notificationBusy = false, contactCapabilities = null;
    const drafts = new Map(), pending = new Map(), busyItems = new Set();
    const $ = selector => host?.querySelector(selector);
    const current = (ticket, session) => host && epoch === ticket && sid === session && getSessionId() === session && host.isConnected;
    function localMinute(date) {
      if (!Number.isFinite(date.getTime())) return '';
      return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    }
    function persist() {
      // Once execution is interrupted, the outcome of an in-flight request is unknown.
      const snapshot = [...pending.entries()].map(([key, entry]) => [key, {request: entry.request, uncertain: true}]);
      try {
        const value = JSON.stringify(snapshot);
        localStorage.setItem(storageKey, value);
        return localStorage.getItem(storageKey) === value;
      } catch (_) { return false; }
    }
    try {
      for (const [key, value] of JSON.parse(localStorage.getItem(storageKey) || localStorage.getItem(legacyKey) || sessionStorage.getItem(legacyKey) || '[]')) {
        // Accept pending requests written by the earlier version as uncertain too.
        const request = value?.request || value;
        if (request?.request_id && request?.session_id === key) pending.set(key, {request, uncertain: true});
      }
    } catch (_) {}
    function node(tag, text, css) {
      const el = document.createElement(tag); if (text != null) el.textContent = text; if (css) el.className = css; return el;
    }
    function resetTimer() {
      clearInterval(timer); timer = null;
      if (host && !document.hidden) timer = setInterval(() => refresh(), 45000);
    }
    function setStatus(text) { const status = $('[data-f-status]'); if (status) status.textContent = text; }
    function matches(item, request) {
      if (!item || !request) return false;
      const due = Date.parse(item?.created_due_at || item?.due_at), expected = Date.parse(request.due_at);
      const sameOptions = (!request.repeat_rule || (item.repeat_rule || 'once') === request.repeat_rule) && (!request.time_zone || item.time_zone === request.time_zone) && (!('quiet_start' in request) || (item.quiet_start || null) === request.quiet_start) && (!('quiet_end' in request) || (item.quiet_end || null) === request.quiet_end);
      return typeof item?.id === 'string' && !!item.id && item.session_id === request.session_id && item.request_id === request.request_id && item.content === request.content && Number.isFinite(due) && Number.isFinite(expected) && due === expected && sameOptions && ['pending','done','cancelled'].includes(item.status) && (!('allow_contact' in request) || item.allow_contact === request.allow_contact) && (!('contact_window_minutes' in request) || item.contact_window_minutes === request.contact_window_minutes) && (!('contact_topic' in request) || item.contact_topic === request.contact_topic);
    }
    function receiptStatus(item) {
      return item.status === 'done' ? '已核对，这次跟进已完成。' : item.status === 'cancelled' ? '已核对，这次跟进已取消。' : '已保存，打开回响时可以看到。';
    }
    function acknowledge(item, request, session) {
      if (!matches(item, request)) return false;
      if (pending.get(session)?.request.request_id === request.request_id) {
        pending.delete(session); persist(); drafts.set(session,{content:'',time:'',open:false});
      }
      return true;
    }
    function syncForm() {
      if (!host || !sid) return;
      const d = drafts.get(sid) || {content:'', time:'', open:false};
      drafts.set(sid, d);
      const locked = pending.has(sid);
      const form = $('[data-f-form]'), content = $('[data-f-content]'), time = $('[data-f-time]');
      const allow = $('[data-f-contact]'), windowField = $('[data-f-window]'), topic = $('[data-f-topic]');
      if (allow) { allow.checked = locked ? pending.get(sid).request.allow_contact === true : d.allowContact === true; allow.disabled = locked || preparing || !window.XinjiContactContract?.supported(contactCapabilities); windowField.disabled = locked || preparing || !allow.checked; topic.disabled = locked || preparing || !allow.checked; windowField.value = String(locked ? pending.get(sid).request.contact_window_minutes || 30 : d.contactWindow || 30); topic.value = locked ? pending.get(sid).request.contact_topic || '' : d.contactTopic || ''; }
      const repeat = $('[data-f-repeat]'), quietStart = $('[data-f-quiet-start]'), quietEnd = $('[data-f-quiet-end]');
      $('[data-f-suggested]').hidden = !d.suggested || locked;
      form.hidden = !(d.open || locked);
      content.value = locked ? pending.get(sid).request.content : d.content;
      if (locked) {
        const date = new Date(pending.get(sid).request.due_at);
        time.value = localMinute(date);
      } else time.value = d.time;
      content.disabled = locked || preparing; time.disabled = locked || preparing;
      repeat.value = locked ? (pending.get(sid).request.repeat_rule || 'once') : (d.repeat || 'once');
      quietStart.value = locked ? (pending.get(sid).request.quiet_start || '') : (d.quietStart || '');
      quietEnd.value = locked ? (pending.get(sid).request.quiet_end || '') : (d.quietEnd || '');
      repeat.disabled = locked || preparing; quietStart.disabled = locked || preparing; quietEnd.disabled = locked || preparing;
      $('[data-f-open]').hidden = !form.hidden;
      $('[data-f-hide]').hidden = locked;
      $('[data-f-submit]').textContent = locked ? '核对并重试保存' : '确认保存';
      $('[data-f-submit]').disabled = sending || preparing;
      if (locked) setStatus('上次保存结果尚未确认。可用同一请求重试，或查看下方列表；请勿重复新建。');
    }
    function stop() {
      if (sending && sid && pending.has(sid)) { pending.get(sid).uncertain = true; persist(); }
      epoch++; sequence++; clearInterval(timer); timer = null; host = null; sid = null; notificationSettings = null;
    }
    function mount(element) {
      stop(); host = element; sid = getSessionId(); if (!host || !sid) return;
      const ticket = epoch, session = sid;
      host.innerHTML = `<div class="followup-card"><div class="followup-head"><div><span class="followup-eyebrow">给未来的自己</span><h3>留一条跟进</h3></div><button type="button" class="mini-btn" data-f-open>添加</button></div><details class="notification-settings"><summary>提醒边界与系统通知</summary><p>安静时间、间隔和次数也作用于应用内轻问。系统通知需单独开启，待办一直可查看。</p><p>这项设置同时作用于连接同一本机服务的桌面版和浏览器。只有对应程序正在运行时才尝试提醒；浏览器还需后台页面保持运行。系统权限或勿扰可能阻止或延迟显示。桌面版还限制每小时最多 1 条、任意 24 小时最多 3 条。</p><button type="button" class="mini-btn" data-f-notification disabled>开启系统通知</button><p data-f-notification-status role="status">正在读取通知设置…</p><div data-f-boundaries hidden><p>主动关心遵守安静、间隔和次数；事项一直可在 Today 查看。系统通知开关只控制系统通知。</p><label>时区（IANA）<input data-f-n-zone aria-label="通知时区" placeholder="Asia/Shanghai"></label><label>安静时间 <input data-f-n-start type="time" aria-label="通知安静开始"> 至 <input data-f-n-end type="time" aria-label="通知安静结束"></label><label>最短间隔（分钟）<input data-f-n-cooldown type="number" min="60" max="1440"></label><label>每天最多（条）<input data-f-n-limit type="number" min="1" max="3"></label><button type="button" class="mini-btn" data-f-n-save>保存安静时间与频率</button> <button type="button" class="mini-btn" data-f-n-reload>重新读取设置</button> <small>重新读取会替换未保存的修改。</small> <button type="button" class="mini-btn" data-f-n-pause>暂停主动提示 24 小时</button><p data-f-n-feedback role="status"></p></div></details><form data-f-form hidden><p data-f-suggested hidden>这是对话中的建议，请核对内容与时间；时间不确定时请自行填写。</p><label>想跟进什么<textarea data-f-content maxlength="1000" rows="3" required placeholder="例如：周五再看看这件事"></textarea></label><fieldset class="followup-contact"><legend>要不要我轻问一次？</legend><label class="followup-contact-choice"><input type="checkbox" data-f-contact disabled> <span data-f-contact-label>允许在约定窗口里轻问一次</span></label><p data-f-contact-default>默认不主动问，由你决定。</p><label>窗口（从到点开始）<select data-f-window disabled><option value="5">5 分钟</option><option value="15">15 分钟</option><option value="30" selected>30 分钟</option><option value="60">1 小时</option><option value="180">3 小时</option></select></label><label>这次围绕什么（留空使用事项内容）<input data-f-topic maxlength="1000" disabled></label><small data-f-contact-note>正在核对服务能力…</small></fieldset><label>什么时候再看<input data-f-time type="datetime-local" required></label><label>重复<select data-f-repeat><option value="once">一次</option><option value="daily">每天</option></select></label><label>安静时段（可选）<input data-f-quiet-start type="time" aria-label="安静时段开始"> 至 <input data-f-quiet-end type="time" aria-label="安静时段结束"></label><p>确认后保存在本机；每日跟进按你当前时区计算。关闭期间不会通知，重开可查看。</p><div class="followup-actions"><button type="submit" class="mini-btn confirm" data-f-submit>确认保存</button><button type="button" class="mini-btn" data-f-hide>先收起</button></div></form><p data-f-status role="status"></p><div data-f-list aria-live="polite"></div><button type="button" class="text-btn" data-f-refresh>刷新跟进</button></div>`;
      const d = drafts.get(session) || {content:'',time:'',open:false}; drafts.set(session,d);
      $('[data-f-contact-label]').textContent = copy('followup.contact.consent','允许在约定窗口轻问一次');
      $('[data-f-contact-default]').textContent = copy('followup.contact.default','默认不主动问，由你决定。');
      function renderNotifications(populate = false) {
        for (const name of ['zone','start','end','cooldown','limit']) $('[data-f-n-'+name+']').disabled = notificationBusy;
        const status = notificationStatus(notificationSettings), button = $('[data-f-notification]');
        button.textContent = status === 'unavailable' ? '重新读取通知设置' : notificationSettings?.enabled ? '关闭系统通知' : '开启系统通知';
        button.disabled = notificationBusy || status === 'unsupported';
        $('[data-f-boundaries]').hidden = !notificationSettings;
        const paused = notificationSettings?.pause_until && Date.parse(notificationSettings.pause_until) > Date.now();
        $('[data-f-n-pause]').textContent = paused ? '恢复主动提示' : '暂停主动提示 24 小时';
        $('[data-f-notification-status]').textContent = status === 'unsupported' ? '当前环境不支持系统通知；仍可设置应用内轻问的安静时间和频率。' :
          status === 'unavailable' ? '未能读取通知设置，请稍后重试。' :
          status === 'denied' ? '系统通知权限已关闭，请在浏览器或系统设置中调整；仍可关闭这里的开关。' :
          status === 'permission' ? '系统通知未获权限，请关闭后重新开启以请求权限。' :
          status === 'enabled' ? (paused ? '已开启，当前暂停中；暂停结束后才会尝试提醒。' : '已开启；对应程序运行时才会尝试提醒，系统权限或勿扰可能阻止或延迟显示。桌面版还限制每小时最多 1 条、任意 24 小时最多 3 条。') :
          '默认关闭；开启后按你设置的时间和上限尝试系统通知。';
        if (populate && notificationSettings) {
          $('[data-f-n-zone]').value = notificationSettings.time_zone;
          $('[data-f-n-start]').value = notificationSettings.quiet_start;
          $('[data-f-n-end]').value = notificationSettings.quiet_end;
          $('[data-f-n-cooldown]').value = String(notificationSettings.cooldown_minutes);
          $('[data-f-n-limit]').value = String(notificationSettings.daily_limit);
          if (notificationSettings.configured === false) $('[data-f-n-feedback]').textContent = '下方是待确认的本地默认值，保存后才成为共用规则。尚未配置时按各条跟进的时区评估安静时间。';
        }
      }
      async function loadSettings() {
        try {
          const caps = await api('/api/capabilities');
          if (!current(ticket, session)) return;
          if (!window.XinjiContactContract?.supported(caps)) { notificationSettings = null; renderNotifications(); $('[data-f-notification-status]').textContent = '当前服务暂不支持受控系统通知。聊天与待办照常。'; return; }
          const data = await api('/api/followup-notification-settings?session_id=' + encodeURIComponent(session));
          if (!current(ticket,session)) return;
          if (!data || typeof data.enabled !== 'boolean' || !Number.isSafeInteger(data.revision) || data.revision < 0 || settingFields.some(k => !(k in data))) throw new Error('设置格式不正确');
          notificationSettings = data; if (data.configured === false) { try { notificationSettings = {...data,time_zone:Intl.DateTimeFormat().resolvedOptions().timeZone || data.time_zone}; } catch (_) {} } renderNotifications(true);
        } catch (_) { if (current(ticket,session)) { notificationSettings = null; renderNotifications(); } }
      }
      async function saveSettings(overrides, message) {
        if (!current(ticket,session) || !notificationSettings || notificationBusy) return;
        notificationBusy = true; window.XinjiCompanionBoundary?.invalidate(); renderNotifications();
        try {
          const body = settingsBody(notificationSettings,session,overrides);
          const data = await api('/api/followup-notification-settings', {method:'PUT',body:JSON.stringify(body)});
          const sameSetting = key => key === 'pause_until' && body[key] != null ? Date.parse(data?.[key]) === Date.parse(body[key]) : data?.[key] === body[key];
          if (!data || data.enabled !== body.enabled || data.revision !== body.expected_revision + 1 || settingFields.some(k => !(k in data) || !sameSetting(k))) throw new Error('设置回执不完整');
          if (current(ticket,session)) { notificationSettings = {...data,configured:true}; window.XinjiCompanionBoundary?.invalidate(); await window.XinjiCompanionBoundary?.refreshAll?.(); renderNotifications(true); $('[data-f-n-feedback]').textContent = message; }
        } catch (error) { if (current(ticket,session)) $('[data-f-n-feedback]').textContent = error.status === 409 ? '其他窗口已更改设置，当前输入未保存。请先重新读取设置并核对，再保存。' : '设置结果未确认，请重新读取设置核对。'; }
        finally { notificationBusy = false; if (current(ticket,session)) renderNotifications(); }
      }
      renderNotifications();
      const advanced = host.querySelector('.notification-settings');
      if (advanced) advanced.ontoggle = () => { if (advanced.open && !notificationSettings) void loadSettings(); };
      if (window.XinjiContactContract) void api('/api/capabilities').then(caps => {
        if (!current(ticket, session)) return; contactCapabilities = caps; syncForm();
        $('[data-f-contact-note]').textContent = window.XinjiContactContract.supported(caps) ? '只在你选的窗口轻问一次；错过不补问。' : '当前服务暂不支持受控关心；可只保存待办。';
      }).catch(() => { if (current(ticket, session)) $('[data-f-contact-note]').textContent = '暂时没能核对关心能力；不会主动提示。'; });
      $('[data-f-contact]').onchange = event => { d.allowContact = event.target.checked; syncForm(); };
      $('[data-f-window]').onchange = event => { d.contactWindow = Number(event.target.value); };
      $('[data-f-topic]').oninput = event => { d.contactTopic = event.target.value; };
      const uiSettings = () => ({time_zone:$('[data-f-n-zone]').value.trim(), quiet_start:$('[data-f-n-start]').value, quiet_end:$('[data-f-n-end]').value, cooldown_minutes:Number($('[data-f-n-cooldown]').value), daily_limit:Number($('[data-f-n-limit]').value)});
      $('[data-f-notification]').onclick = async () => {
        if (notificationBusy) return;
        if (!notificationSettings) return loadSettings();
        if (!desktop() && !browserSupport()) return;
        if (notificationSettings.enabled) return saveSettings({enabled:false}, '系统通知已关闭。');
        const edited = uiSettings();
        if (notificationSettings.configured !== false && Object.keys(edited).some(k => edited[k] !== notificationSettings[k])) {
          $('[data-f-n-feedback]').textContent = '提醒边界有未保存的修改，请先保存，再开启系统通知。'; return;
        }
        if (!desktop()) {
          notificationBusy = true; renderNotifications();
          try {
            const permission = globalThis.Notification.permission === 'granted' ? 'granted' : await globalThis.Notification.requestPermission();
            if (!current(ticket,session)) return;
            if (permission !== 'granted') { $('[data-f-n-feedback]').textContent = '未获得通知权限，系统通知没有开启。'; return; }
          } catch (_) { if (current(ticket,session)) $('[data-f-n-feedback]').textContent = '通知权限请求失败，系统通知没有开启。'; return; }
          finally { notificationBusy = false; if (current(ticket,session)) renderNotifications(); }
        }
        if (current(ticket,session)) {
          await saveSettings(notificationSettings.configured === false ? {...edited,enabled:true} : {enabled:true}, '已开启系统通知；是否显示由系统决定。');
        }
      };
      $('[data-f-n-save]').onclick = () => saveSettings(uiSettings(), '提醒边界已保存。');
      $('[data-f-n-reload]').onclick = () => loadSettings();
      $('[data-f-n-pause]').onclick = () => {
        const paused = notificationSettings?.pause_until && Date.parse(notificationSettings.pause_until) > Date.now();
        return saveSettings({pause_until:paused ? null : new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()}, paused ? '已恢复主动提示，仍须满足各条窗口与联系许可。' : '主动提示已暂停 24 小时，待办仍可查看。');
      };
      $('[data-f-open]').onclick = () => { d.open = true; syncForm(); $('[data-f-content]').focus(); };
      $('[data-f-hide]').onclick = () => { d.open = false; syncForm(); $('[data-f-open]').focus(); };
      $('[data-f-content]').oninput = event => { d.content = event.target.value; };
      $('[data-f-time]').oninput = event => { d.time = event.target.value; };
      $('[data-f-repeat]').onchange = event => { d.repeat = event.target.value; };
      $('[data-f-quiet-start]').oninput = event => { d.quietStart = event.target.value; };
      $('[data-f-quiet-end]').oninput = event => { d.quietEnd = event.target.value; };
      $('[data-f-form]').onsubmit = event => { event.preventDefault(); submit(ticket, session); };
      $('[data-f-refresh]').onclick = () => refresh();
      syncForm(); resetTimer(); refresh();
    }
    function canRefresh() {
      return !host || !host.isConnected || (!sending && !preparing && !notificationBusy && !busyItems.size && !pending.has(sid) && ($('[data-f-form]')?.hidden !== false));
    }
    function acceptSnapshot(data, metadata = null) {
      if (!host || !host.isConnected) return true;
      const ticket = metadata?.ticket ?? epoch, session = metadata?.session ?? sid, request = metadata?.request ?? ++sequence;
      if (!current(ticket, session) || request !== sequence || !Array.isArray(data?.followups)) return false;
        const saved = pending.get(session);
        if (saved) {
          const receipt = data.followups.find(item => matches(item, saved.request));
          if (receipt && acknowledge(receipt, saved.request, session)) { syncForm(); setStatus(receiptStatus(receipt)); }
          else if (data.followups.some(item => item.session_id === session && item.request_id === saved.request.request_id)) {
            setStatus('同一请求的内容、时间或状态不匹配，原标识仍保留，请核对记录；不会重复新建。');
          }
        }
        const list = $('[data-f-list]'); list.replaceChildren();
        const active = data.followups.filter(item => item.session_id === session && item.status === 'pending');
        if (!active.length) list.append(node('p', '还没有待跟进的事。', 'followup-empty'));
        for (const item of active) {
          const card = node('article', null, 'followup-item');
          card.append(node('span', item.paused ? '已暂停' : item.due && item.quiet ? '安静时段 · 已到时间' : (item.review_available ?? (item.due && !item.paused && !item.quiet)) ? '已到时间' : '待跟进', 'followup-tag'));
          if (item.contact_reason === 'expired') card.append(node('span', copy('followup.contact.expired','窗口已过，不再补问'), 'followup-tag'));
          if (item.repeat_rule === 'daily') card.append(node('span', '每天', 'followup-tag'));
          card.append(node('p', item.content, 'followup-content'));
          card.append(node('time', followupTime(item), 'followup-time'));
          const contact = contactStatus(item);
          if (contact) {
            if (typeof item.contact_topic === 'string' && item.contact_topic.trim()) card.append(node('p', '轻问话题：' + item.contact_topic, 'followup-contact-topic'));
            card.append(node('p', contact, 'followup-contact-status'));
          }
          const actions = node('div', null, 'followup-actions');
          for (const [label, status] of [['完成','done'],[item.paused ? '继续' : '暂停',item.paused ? 'resumed' : 'paused'],['取消','cancelled']]) {
            const button = node('button', label, 'mini-btn'); button.type = 'button'; button.disabled = busyItems.has(item.id) || (status === 'done' && item.repeat_rule === 'daily' && !item.due);
            button.onclick = () => update(item, status, ticket, session); actions.append(button);
          }
          card.append(actions); list.append(card);
        }
      return true;
    }
    async function refresh() {
      if (!host || !sid || document.hidden) return;
      const ticket = epoch, session = sid, request = ++sequence;
      try {
        const data = await api('/api/followups?session_id=' + encodeURIComponent(session));
        if (!current(ticket, session) || request !== sequence) return;
        if (!Array.isArray(data.followups)) throw new Error('返回格式不正确');
        return acceptSnapshot(data, {ticket, session, request});
      } catch (error) {
        if (!current(ticket, session) || request !== sequence) return;
        const list = $('[data-f-list]'); list.replaceChildren(node('p', `未能读取跟进：${error.message}`, 'followup-error'));
      }
    }
    let sending = false, preparing = false;
    async function submit(ticket, session) {
      if (!current(ticket, session) || sending || preparing) return;
      const draft = {...drafts.get(session)}; let entry = pending.get(session);
      const initialAttempt = !entry;
      if (!entry) {
        const content = draft.content.trim(), local = draft.time, selected = new Date(local), millis = selected.getTime();
        if (!content || content.length > 1000 || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(local) || !Number.isFinite(millis) || millis <= Date.now()) { setStatus('请填写内容，并选择未来的时间。'); return; }
        if (localMinute(selected) !== local) { setStatus('这个本地时间不存在，请选择其他时间。'); return; }
        if (!globalThis.crypto?.randomUUID) { setStatus('当前环境无法安全创建请求编号，请换用较新版本的浏览器。'); return; }
        const quietStart = draft.quietStart || '', quietEnd = draft.quietEnd || '';
        if ((!!quietStart !== !!quietEnd) || (quietStart && quietStart === quietEnd)) { setStatus('请填写不同的安静时段开始和结束时间，或都留空。'); return; }
        if (draft.allowContact === true && window.XinjiContactContract?.supported(contactCapabilities)) {
          preparing = true; syncForm();
          try {
            const boundary = await api('/api/companion-boundary?session_id=' + encodeURIComponent(session));
            if (!current(ticket, session)) return;
            if (!window.XinjiContactContract.validBoundary(boundary) || boundary.mode !== 'active') { setStatus('先在对话中恢复关心，再重新确认这条轻问；也可取消勾选，只保存待办。'); return; }
          } catch (_) { if (current(ticket, session)) setStatus('暂时没能核对关心设置，尚未提交；文字保留。'); return; }
          finally { preparing = false; if (host) syncForm(); }
        }
        const request = {session_id:session, content, due_at:new Date(millis).toISOString(), request_id:crypto.randomUUID(), confirmed:true,
          repeat_rule:draft.repeat || 'once', time_zone:Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
          quiet_start:quietStart || null, quiet_end:quietEnd || null};
        if (window.XinjiContactContract?.supported(contactCapabilities)) {
          request.allow_contact = draft.allowContact === true; request.contact_window_minutes = draft.contactWindow || 30;
          request.contact_topic = draft.contactTopic?.trim() || content;
        }
        entry = {request, uncertain:false}; pending.set(session, entry);
        // Without a recoverable request ID we cannot safely reconcile an interrupted save.
        if (!persist()) { pending.delete(session); setStatus('无法安全保存请求编号，请允许本地会话存储后重试。'); return; }
      }
      sending = true; sequence++; syncForm(); setStatus('正在保存…');
      try {
        const result = await api('/api/followups', {method:'POST', body:JSON.stringify(entry.request)});
        if (!acknowledge(result, entry.request, session)) throw new Error('保存回执的标识、内容、时间或状态不匹配');
        if (current(ticket, session)) { syncForm(); setStatus(receiptStatus(result)); refresh(); }
      } catch (error) {
        // Only a brand-new first validation rejection can release an unused ID.
        // Once uncertain (including reload), preserve the original request.
        if (initialAttempt && [400,422].includes(error.status) && pending.get(session)?.request.request_id === entry.request.request_id) { pending.delete(session); persist(); }
        else { entry.uncertain = true; persist(); }
        if (current(ticket, session)) { syncForm(); setStatus(pending.has(session) ? `保存结果尚未确认：${error.message}。请用同一请求重试。` : `未保存：${error.message}`); refresh(); }
      } finally {
        sending = false;
        // A newly reopened view of the same session may have mounted while the request was in flight.
        if (current(epoch, session)) { syncForm(); refresh(); }
      }
    }
    async function update(item, status, ticket, session) {
      if (!current(ticket, session) || busyItems.has(item.id)) return;
      busyItems.add(item.id); sequence++; // invalidate older list responses
      const buttons = $('[data-f-list]')?.querySelectorAll('button'); buttons?.forEach(button => button.disabled = true);
      try {
        const result = await api('/api/followups/' + encodeURIComponent(item.id), {method:'PATCH',body:JSON.stringify({session_id:session,status,occurrence_at:item.repeat_rule === 'daily' && status === 'done' ? item.due_at : null})});
        if (result?.id !== item.id || (status === 'paused' ? result.paused !== true : status === 'resumed' ? result.paused !== false : status === 'done' && item.repeat_rule === 'daily' ? result.last_occurrence_at !== item.due_at : result.status !== status)) throw new Error('更新回执不完整');
        if (current(ticket,session)) setStatus(status === 'done' ? (item.repeat_rule === 'daily' ? '这次已完成，下一次已安排。' : '已标记完成。') : status === 'paused' ? '已暂停跟进。' : status === 'resumed' ? '已恢复跟进。' : '已取消这条跟进。');
      } catch (error) {
        if (current(ticket,session)) setStatus(`更新结果未确认：${error.message}。请刷新列表核对。`);
      } finally { busyItems.delete(item.id); if (current(ticket,session)) refresh(); }
    }
    function visibility() { if (!host) return; resetTimer(); if (!document.hidden) refresh(); }
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pagehide', stop);
    function offer(proposal) {
      const session = getSessionId();
      if (!session || proposal?.kind !== 'reminder' || typeof proposal.title !== 'string' || !proposal.title.trim()) return 'invalid';
      if (pending.has(session)) return 'pending';
      const old = drafts.get(session);
      if (old && (old.content?.trim() || old.time || old.quietStart || old.quietEnd || (old.repeat && old.repeat !== 'once'))) return 'draft';
      const title = proposal.title.trim(), detail = typeof proposal.detail === 'string' ? proposal.detail.trim() : '';
      const content = detail && detail !== title ? `${title}\n${detail}` : title;
      const raw = typeof proposal.when === 'string' ? proposal.when.trim() : '';
      let time = '';
      if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})?$/.test(raw)) {
        const date = new Date(raw);
        const minute = localMinute(date);
        const floating = !/(?:Z|[+-]\d{2}:\d{2})$/.test(raw);
        // A nonexistent or normalized wall time must never become a different reminder.
        if (minute && (!floating || minute === raw.slice(0, 16))) time = minute;
      }
      drafts.set(session, {content, time, open:true, suggested:true});
      if (sid === session && host) syncForm();
      return 'ready';
    }
    return {mount, stop, refresh, offer, canRefresh, acceptSnapshot};
  }
  return {create};
})();

// Automatic presentation is authorized by the unified R9 contact path only.
window.XinjiFollowups.startReminder = options => window.XinjiProactiveContact?.create(options) || {refresh:async()=>{},stop(){}};
