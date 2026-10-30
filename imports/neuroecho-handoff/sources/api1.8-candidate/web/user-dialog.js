/* Async document dialogs also work in Electron, where window.prompt is unsupported. */
(() => {
  let pending = Promise.resolve();
  function enqueue(kind, options = {}) {
    const run = () => new Promise((resolve) => {
      const doc = document, previous = doc.activeElement;
      const parent = previous?.closest?.('[role="dialog"], dialog[open]') || doc.body;
      const dialog = doc.createElement('dialog');
      dialog.className = 'echo-user-dialog';
      dialog.setAttribute('aria-labelledby', 'echo-user-dialog-title');
      dialog.setAttribute('aria-describedby', 'echo-user-dialog-description');
      dialog.innerHTML = '<form method="dialog"><h2 id="echo-user-dialog-title"></h2><p id="echo-user-dialog-description"></p><label class="echo-dialog-field"><span></span><textarea rows="3"></textarea></label><div class="echo-dialog-actions"><button type="button" data-cancel>取消</button><button type="submit" data-confirm></button></div></form>';
      const title = dialog.querySelector('h2'), description = dialog.querySelector('p');
      const field = dialog.querySelector('textarea'), label = dialog.querySelector('label');
      const confirm = dialog.querySelector('[data-confirm]'), cancel = dialog.querySelector('[data-cancel]');
      title.textContent = options.title || (kind === 'prompt' ? '记下一件事' : '请确认');
      description.textContent = options.message || '';
      label.hidden = kind !== 'prompt';
      label.querySelector('span').textContent = options.label || '内容';
      field.setAttribute('aria-label', options.label || '内容');
      field.value = String(options.value ?? '');
      field.placeholder = options.placeholder || '';
      field.maxLength = options.maxLength || 4000;
      confirm.textContent = options.confirmLabel || '确认';
      confirm.classList.toggle('danger', !!options.danger);
      let settled = false, observer;
      function finish(accepted) {
        if (settled) return;
        settled = true;
        observer?.disconnect();
        if (dialog.open) dialog.close();
        dialog.remove();
        if (previous?.isConnected && !previous.closest?.('.is-hidden, [hidden], [inert]')) previous.focus();
        resolve(kind === 'prompt' ? (accepted ? field.value : null) : !!accepted);
      }
      dialog.querySelector('form').addEventListener('submit', (event) => { event.preventDefault(); finish(true); });
      cancel.addEventListener('click', () => finish(false));
      dialog.addEventListener('cancel', (event) => { event.preventDefault(); finish(false); });
      // Keep an enclosing source-dialog's Escape handler from dismissing both layers.
      dialog.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); finish(false); }
      }, true);
      parent.appendChild(dialog);
      try { dialog.showModal(); }
      catch (_) { finish(false); return; }
      (kind === 'prompt' ? field : options.danger ? cancel : confirm).focus();
      if (typeof MutationObserver !== 'undefined') {
        observer = new MutationObserver(() => {
          if (!dialog.isConnected || parent.closest?.('.is-hidden, [hidden], [inert]')) finish(false);
        });
        observer.observe(doc.body, {childList:true, subtree:true, attributes:true, attributeFilter:['class','hidden','inert']});
      }
    });
    const result = pending.then(run, run);
    pending = result.catch(() => {});
    return result;
  }
  window.XinjiDialogs = {prompt: (options) => enqueue('prompt', options), confirm: (options) => enqueue('confirm', options)};
})();
