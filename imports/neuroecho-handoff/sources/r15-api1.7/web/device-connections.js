/* Device cards describe available capabilities; rendering never reads or connects a device. */
(() => {
  const devices = [
    {id:'rokid', name:'Rokid 眼镜', detail:'待连接 app 或热点链接', message:'Rokid 连接功能待接入，暂时无法通过 app 或热点连接。'},
    {id:'mindlink', name:'脑机接口', detail:'通过本机 MindLink 服务读取', message:'请在连接设备的电脑上操作；开启前需要你的同意。'},
    {id:'badge', name:'电子吧唧', detail:'待接入', message:'电子吧唧连接功能待接入。'},
    {id:'watch', name:'智能手表', detail:'待接入', message:'智能手表连接功能待接入。'}
  ];
  const paths = {
    rokid:'<path d="M3 8h18l-1.5 6a2 2 0 0 1-2 1.5h-2a2 2 0 0 1-1.8-1.1l-.5-1a1.3 1.3 0 0 0-2.3 0l-.5 1a2 2 0 0 1-1.8 1.1h-2A2 2 0 0 1 4.5 14L3 8Z"/><path d="M6 8 5 5m13 3 1-3"/>',
    mindlink:'<path d="M12 4a3 3 0 0 0-5 2.3A3.6 3.6 0 0 0 5.8 13 3.3 3.3 0 0 0 9 18h3Zm0 0a3 3 0 0 1 5 2.3A3.6 3.6 0 0 1 18.2 13 3.3 3.3 0 0 1 15 18h-3"/><path d="M8 9h2m4 2h2M9 15h1m4-8h1"/>',
    badge:'<circle cx="12" cy="12" r="7.3"/><path d="M8.5 13.3c1.8 2 5.2 2 7 0M9 10h.01M15 10h.01M10 4.7l1-2h2l1 2"/>',
    watch:'<rect x="6.7" y="7" width="10.6" height="10" rx="3"/><path d="M9 7 9.6 3h4.8l.6 4M9 17l.6 4h4.8l.6-4M12 9.5V12l1.8 1"/>'
  };
  const icons = {feishu:'lark.png', apple_calendar:'apple-calendar.png', apple_reminders:'apple-reminders.png'};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function sourceIcon(id, fallback) {
    return icons[id] ? `<img src="/static/connection-icons/${icons[id]}" alt="${esc(fallback)}" width="32" height="32" style="display:block;width:32px;height:32px;object-fit:contain;border-radius:8px">` : esc(fallback);
  }
  function icon(id) {
    return `<svg aria-hidden="true" width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${paths[id]}</svg>`;
  }
  function html({mobile = false} = {}) {
    return devices.map(device => mobile
      ? `<div class="m-connector"><div class="ico">${icon(device.id)}</div><div class="bd"><b>${device.name}</b><small>${device.detail}</small></div><button type="button" class="go" data-device-connect="${device.id}">连接</button></div>`
      : `<div class="app-card"><div class="ico">${icon(device.id)}</div><div class="app-source-content"><b>${device.name}</b><small>${device.detail}</small></div><button type="button" class="btn ghost small" data-device-connect="${device.id}">连接</button></div>`).join('');
  }
  function bind(container, {onMindLink, onUnavailable} = {}) {
    container.querySelectorAll('[data-device-connect]').forEach(button => {
      button.onclick = () => {
        const device = devices.find(item => item.id === button.dataset.deviceConnect);
        if (!device) return;
        if (device.id === 'mindlink') onMindLink?.();
        else onUnavailable?.({id:device.id, name:device.name, message:device.message});
      };
    });
  }
  window.XinjiDeviceConnections = {html, bind, sourceIcon};
})();
