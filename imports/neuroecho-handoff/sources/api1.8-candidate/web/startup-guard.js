/* A failed cached dependency must not leave an empty, hidden application. */
(() => {
  function report(event) {
    if (event?.type !== 'unhandledrejection' && typeof event?.message !== 'string' && event?.target?.tagName !== 'SCRIPT') return;
    const app = document.querySelector('#app, #m-app');
    if (!app?.classList.contains('is-hidden') || document.querySelector('.restore-error')) return;
    const box = document.createElement('section');
    box.className = 'restore-error'; box.setAttribute('role','alert');
    const title = document.createElement('h2'); title.textContent = '页面暂时没能打开';
    const text = document.createElement('p'); text.textContent = '本机记录没有被清除。请重新载入页面，再核对尚未完成的发送。';
    const retry = document.createElement('button'); retry.className = 'btn primary'; retry.textContent = '重新载入'; retry.onclick = () => location.reload();
    box.append(title,text,retry); document.body.appendChild(box);
  }
  window.addEventListener('error',report,true);
  window.addEventListener('unhandledrejection',report);
})();
