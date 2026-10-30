/* Owner-only device access. Secrets stay in this live view, never browser storage. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.XinjiPairedDevices = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';
  const copy = (key, fallback) => root.EchoShared?.copy?.[key] || fallback;
  const text = {
    title: () => copy('connection.devices.title', '让回响陪你换一台设备'),
    scope: () => copy('connection.devices.scope', '这台设备可以查看和修改同一条对话、已接入资料、记忆、心情和跟进；不能调用电脑上的 CLI、系统动作、硬件或模型设置。'),
    secret: () => copy('connection.devices.secret', '连接码只在这里显示一次。仅交给你自己的设备，不要发进聊天或公开分享。'),
    revoked: () => copy('connection.devices.revoked', '已收回这台设备的新请求。已经开始的操作可能已经提交，不会自动回滚。'),
  };
  const validTime = value => typeof value === 'string' && Number.isFinite(Date.parse(value));
  function metadata(value) {
    if (!value || typeof value.id !== 'string' || !/^[A-Za-z0-9_-]{8,128}$/.test(value.id) ||
        typeof value.label !== 'string' || !value.label.trim() || value.label.length > 80 ||
        !validTime(value.created_at) || !validTime(value.expires_at) ||
        !(value.revoked_at === null || validTime(value.revoked_at))) throw Error('invalid device receipt');
    return {id:value.id, label:value.label, created_at:value.created_at, expires_at:value.expires_at,
            revoked_at:value.revoked_at};
  }
  function identity(value, sid) {
    if (typeof value?.service_instance_id !== 'string' || !value.service_instance_id ||
        value.conversation_id !== sid) throw Error('wrong service receipt');
    return value.service_instance_id;
  }
  function createController({api, getSessionId, onChange = () => {}, visible = () => true,
                             timers = root, timeout = 12000}) {
    let secret = '', operation = null, serial = 0, disposed = false;
    let state = {devices:[], loaded:false, busy:false, note:'', review:null, instance:null, sid:null, unknown:false};
    const current = () => !disposed && visible() && !!getSessionId();
    const snapshot = () => ({...state, devices:state.devices.map(item => ({...item})),
                             review:state.review ? {...state.review} : null, hasSecret:!!secret});
    const emit = () => { if (!disposed) onChange(snapshot()); };
    const clearSecret = () => { secret = ''; };
    async function request(path, options, kind) {
      const id = ++serial, sid = getSessionId(), abort = typeof AbortController === 'function' ? new AbortController() : null;
      operation = {id, sid, kind, abort}; state.busy = true; emit();
      let timer;
      try {
        const result = await Promise.race([
          api(path, {...options, ...(abort ? {signal:abort.signal} : {})}),
          new Promise((_, reject) => { timer = timers.setTimeout(() => { abort?.abort(); reject(Error('receipt timeout')); }, timeout); }),
        ]);
        if (!operation || operation.id !== id || getSessionId() !== sid || !current()) return null;
        return result;
      } catch (error) {
        if (!operation || operation.id !== id || getSessionId() !== sid || !current()) return null;
        throw error;
      } finally {
        if (timer !== undefined) timers.clearTimeout(timer);
        if (operation?.id === id) { operation = null; state.busy = false; }
      }
    }
    async function load() {
      if (!current() || state.busy) return false;
      clearSecret(); state.review = null;
      const sid = getSessionId();
      try {
        const response = await request('/api/paired-devices', {}, 'list');
        if (!response) return false;
        const instance = identity(response, sid);
        if (!Array.isArray(response.devices)) throw Error('invalid device list');
        const devices = response.devices.map(metadata);
        if (new Set(devices.map(device => device.id)).size !== devices.length) throw Error('duplicate devices');
        state = {...state, loaded:true, instance, sid, devices, note:'', unknown:false};
        emit(); return true;
      } catch (_) {
        state.loaded = false; state.review = null;
        state.note = '暂时无法核对设备。没有自动生成或收回连接码，请稍后重新读取。';
        emit(); return false;
      }
    }
    function prepare(label) {
      label = typeof label === 'string' ? label.trim() : '';
      if (!current() || state.busy || !state.loaded || state.unknown || state.sid !== getSessionId() || !label || label.length > 80) return false;
      clearSecret(); state.review = {kind:'issue', label}; state.note = ''; emit(); return true;
    }
    async function issue() {
      if (!current() || state.busy || !state.loaded || state.review?.kind !== 'issue' || state.sid !== getSessionId()) return false;
      const label = state.review.label, sid = state.sid, instance = state.instance;
      clearSecret(); state.review = null;
      try {
        const response = await request('/api/paired-devices', {
          method:'POST', body:JSON.stringify({label, expires_in_seconds:604800, confirmed:true}),
        }, 'issue');
        if (!response) return false;
        if (identity(response, sid) !== instance || response.scope !== 'personal_core' || response.local_actions_allowed !== false ||
            typeof response.token !== 'string' || !/^echo_pair_[A-Za-z0-9_-]{43}$/.test(response.token)) throw Error('invalid device receipt');
        const device = metadata(response.device);
        if (device.label !== label || device.revoked_at !== null) throw Error('invalid device receipt');
        secret = response.token;
        state.devices = [device, ...state.devices.filter(item => item.id !== device.id)];
        state.note = '连接码已生成，7 天内有效。请在原生 App 的连接设置中填写已准备好的 HTTPS 服务地址与连接码。生成连接码不会开放本机网络。';
        state.unknown = false; emit(); return true;
      } catch (_) {
        clearSecret(); state.unknown = true;
        state.note = '没能确认连接码是否生成，不会自动重试。先重新读取设备列表；若设备已出现但没有拿到连接码，可以收回后重新生成。';
        emit(); return false;
      }
    }
    function prepareRevoke(id) {
      if (!current() || state.busy || !state.loaded || state.sid !== getSessionId()) return false;
      const device = state.devices.find(item => item.id === id && item.revoked_at === null);
      if (!device) return false;
      clearSecret(); state.review = {kind:'revoke', id, label:device.label}; state.note = ''; emit(); return true;
    }
    async function revoke() {
      if (!current() || state.busy || state.review?.kind !== 'revoke' || state.sid !== getSessionId()) return false;
      const {id} = state.review, instance = state.instance;
      clearSecret(); state.review = null;
      try {
        const response = await request('/api/paired-devices/' + encodeURIComponent(id) + '/revoke', {
          method:'POST', body:JSON.stringify({confirmed:true}),
        }, 'revoke');
        if (!response) return false;
        if (response.service_instance_id !== instance || response.device_id !== id || response.revoked !== true ||
            response.in_flight_may_have_committed !== true) throw Error('invalid revocation receipt');
        state.devices = state.devices.map(item => item.id === id ? {...item, revoked_at:new Date().toISOString()} : item);
        state.note = text.revoked(); state.unknown = false; emit(); return true;
      } catch (_) {
        state.note = '还没确认是否已收回。请重新读取设备列表核对；不会把失败当作成功。';
        state.unknown = true; emit(); return false;
      }
    }
    function suspend() {
      clearSecret(); state.review = null;
      if (operation) {
        if (operation.kind !== 'list') { state.unknown = true; state.note = '操作回执尚未核对，重新打开后先读取设备列表。'; }
        operation.abort?.abort(); operation = null; ++serial; state.busy = false;
      }
      emit();
    }
    return {snapshot, load, prepare, issue, prepareRevoke, revoke,
      cancelReview() { state.review = null; clearSecret(); emit(); },
      secretForView() { return current() && state.sid === getSessionId() ? secret : ''; },
      suspend, dispose() { suspend(); disposed = true; },
    };
  }

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function mount(container, {api, getSessionId, visible = () => true} = {}) {
    if (!container || !api || !getSessionId) return null;
    container._pairedDevices?.dispose();
    const document = container.ownerDocument;
    let closed = false, lastReview = null;
    const live = () => !closed && container.isConnected && visible() && !document.hidden;
    let controller;
    function render(state) {
      if (!container.isConnected || closed) return;
      const previousLabel = container.querySelector('[data-device-label]')?.value || '';
      container.innerHTML = `<section class="paired-devices" aria-label="其他设备连接">
        <div class="paired-heading"><span aria-hidden="true">⌁</span><h3>${esc(text.title())}</h3></div>
        <p class="note">在自己的 iPhone 或 Android 上接着聊。先准备好安全服务地址，再为那台设备生成连接码。</p>
        <p class="paired-network-note">当前页面不会开启远程服务，也不会把电脑开放到局域网或公网。</p>
        <label class="paired-field">设备名称<input data-device-label maxlength="80" autocomplete="off" placeholder="例如：我的 iPhone" ${state.busy ? 'disabled' : ''}></label>
        <div class="paired-actions"><button type="button" class="btn primary" data-device-prepare ${!state.loaded || state.busy || state.unknown ? 'disabled' : ''}>为这台设备生成连接码</button><button type="button" class="btn ghost" data-device-reload ${state.busy ? 'disabled' : ''}>重新读取</button></div>
        <p class="note" role="status" aria-live="polite">${esc(state.busy ? '正在核对…' : state.note)}</p>
        <div data-device-review></div><div data-device-secret></div>
        <div class="paired-list" aria-label="已生成连接码的设备">${!state.loaded ? '<p class="note">需要先核对这台电脑的设备记录。</p>' : !state.devices.length ? '<p class="note">还没有为其他设备生成连接码。</p>' : state.devices.map(device => {
          const inactive = device.revoked_at !== null || Date.parse(device.expires_at) <= Date.now();
          const status = device.revoked_at !== null ? '已收回' : inactive ? '已到期' : '连接码有效';
          return `<article class="paired-device-row"><div><b>${esc(device.label)}</b><small>${esc(status)} · ${esc(new Date(device.expires_at).toLocaleDateString('zh-CN'))} 到期</small></div>${!inactive ? `<button type="button" class="btn ghost" data-device-revoke="${esc(device.id)}" ${state.busy ? 'disabled' : ''}>收回</button>` : ''}</article>`;
        }).join('')}</div>
      </section>`;
      const label = container.querySelector('[data-device-label]'); label.value = previousLabel;
      container.querySelector('[data-device-prepare]').onclick = () => {
        if (!controller.prepare(label.value)) { label.focus(); label.setCustomValidity('请填一个 80 字以内的设备名称。'); label.reportValidity(); label.oninput = () => label.setCustomValidity(''); }
      };
      container.querySelector('[data-device-reload]').onclick = () => controller.load();
      container.querySelectorAll('[data-device-revoke]').forEach(button => button.onclick = () => controller.prepareRevoke(button.dataset.deviceRevoke));
      const review = container.querySelector('[data-device-review]');
      if (state.review) {
        review.innerHTML = `<div class="paired-review"><h4>${state.review.kind === 'issue' ? '我打算这样连接' : '收回这台设备？'}</h4><p>${esc(state.review.label)}</p><p>${esc(state.review.kind === 'issue' ? text.scope() : copy('connection.devices.revoke_review', '确认后将阻止这台设备的新请求。已经开始的操作可能已经提交，不会自动回滚。'))}</p>${state.review.kind === 'issue' ? '<p>7 天后自动失效；也可以随时在这里收回。这不是单份资料授权，已接入的资料也在访问范围内。</p>' : ''}<div class="paired-actions"><button type="button" class="btn primary" data-device-confirm>${state.review.kind === 'issue' ? '确认范围并生成' : '确认收回'}</button><button type="button" class="btn ghost" data-device-cancel>不用</button></div></div>`;
        review.querySelector('[data-device-confirm]').onclick = () => state.review.kind === 'issue' ? controller.issue() : controller.revoke();
        review.querySelector('[data-device-cancel]').onclick = () => controller.cancelReview();
        if (lastReview !== state.review.kind) review.querySelector('[data-device-confirm]').focus();
      }
      lastReview = state.review?.kind || null;
      const secret = controller?.secretForView();
      if (secret) {
        const target = container.querySelector('[data-device-secret]');
        target.innerHTML = `<div class="paired-secret"><b>只显示这一次</b><p>${esc(text.secret())}</p><label>设备连接码<input data-device-code readonly autocomplete="off" spellcheck="false" aria-label="设备连接码，仅显示一次"></label><button type="button" class="btn ghost" data-device-select>选中连接码</button><p class="note">切换页面、隐藏窗口或重新读取后，连接码会从页面清除。没有保存时，可收回后重新生成。</p></div>`;
        const input = target.querySelector('[data-device-code]'); input.value = secret;
        target.querySelector('[data-device-select]').onclick = () => { input.focus(); input.select(); };
      }
    }
    controller = createController({api, getSessionId, visible:live, onChange:render});
    const hidden = () => { if (document.hidden) controller.suspend(); };
    const pagehide = () => controller.suspend();
    document.addEventListener('visibilitychange', hidden);
    root.addEventListener('pagehide', pagehide);
    const handle = {load:() => controller.load(), suspend:() => controller.suspend(), dispose() {
      if (closed) return;
      controller.dispose(); closed = true; container.replaceChildren();
      document.removeEventListener('visibilitychange', hidden); root.removeEventListener('pagehide', pagehide);
    }};
    container._pairedDevices = handle;
    render(controller.snapshot()); controller.load();
    return handle;
  }
  return {createController, mount};
});
