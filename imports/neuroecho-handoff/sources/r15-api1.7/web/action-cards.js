/* Saved actions remain inspectable; copying a draft never sends it. */
(() => {
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function status(action) {
    if (action.status === 'unknown' || action.status === 'executing') return '结果待确认，请先检查系统';
    if (action.status === 'failed') return '未能完成';
    if (action.status === 'previewed') return '待确认';
    if (action.kind === 'message') return '草稿已保存 · 未发送';
    return action.real ? '已写入系统' : '仅存本机 · 尚未写入系统';
  }
  function html(actions, options = {}) {
    const labels = {reminder:'提醒',calendar:'日历',message:'消息草稿'};
    return actions.map((action, index) => `<div class="task-action">
      <b>${esc(labels[action.kind] || action.kind)} · ${esc(action.title)}</b>
      <span>${esc(status(action))}${action.when_text ? ' · ' + esc(action.when_text.replace('T', ' ')) : ''}</span>
      ${options.interactive && action.status === 'previewed' ? `<button type="button" class="btn ghost small" data-action-continue="${index}">继续确认</button>` : ''}
      ${options.interactive && ['unknown', 'executing'].includes(action.status) ? `<button type="button" class="btn ghost small" data-action-check="${index}">核对本机状态</button><p class="note">仅重新读取本机记录，不会再次写入系统。</p>` : ''}
      ${action.detail || action.kind === 'message' ? `<details class="action-draft"><summary>${action.kind === 'message' ? '查看草稿正文' : '查看内容'}</summary>
        <textarea readonly rows="4" aria-label="${action.kind === 'message' ? '消息草稿正文' : '动作内容'}">${esc(action.detail)}</textarea>
        ${action.kind === 'message' ? `<button type="button" class="btn ghost small" data-copy-draft="${index}">复制全文</button><p class="draft-copy-status" role="status">可以修改后再自行发送。</p>` : ''}
      </details>` : ''}
    </div>`).join('');
  }
  function bind(container, actions, options = {}) {
    for (const [selector, key, callback, allowed] of [
      ['[data-action-continue]', 'actionContinue', options.onContinue, ['previewed']],
      ['[data-action-check]', 'actionCheck', options.onCheck, ['unknown', 'executing']],
    ]) container.querySelectorAll(selector).forEach((button) => {
      button.disabled = typeof callback !== 'function';
      button.onclick = () => {
        const action = actions[Number(button.dataset[key])];
        if (action && allowed.includes(action.status) && typeof callback === 'function') callback(action);
      };
    });
    container.querySelectorAll('[data-copy-draft]').forEach((button) => {
      button.onclick = async () => {
        const action = actions[Number(button.dataset.copyDraft)];
        if (!action || action.kind !== 'message') return;
        const card = button.closest('.action-draft');
        const field = card.querySelector('textarea');
        const note = card.querySelector('.draft-copy-status');
        button.disabled = true;
        try {
          if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
          await navigator.clipboard.writeText(action.detail || '');
          note.textContent = '已复制草稿全文。';
        } catch (_) {
          field.focus();
          field.select();
          note.textContent = '自动复制不可用，正文已选中，请长按或用 ⌘C / Ctrl+C 复制。';
        } finally {
          button.disabled = false;
        }
      };
    });
  }
  function chatDraft(messages, index) {
    const answer = messages[index];
    if (answer?.role !== 'assistant' || !String(answer.text || '').trim()) return null;
    const parts = [];
    for (let i = index - 1; i >= 0 && messages[i].role === 'user' && parts.length < 4; i--) parts.unshift(messages[i].text || '');
    const request = parts.join('\n').trim();
    if (request.split('\n').slice(1).some(line => /^(?:算了|不用了|先不用|不需要|停下|别写|不要写|不要起草)/.test(line.trim()))) return null;
    if (!/^(?:请(?:你)?\s*)?(?:帮我(?:写|回复|回|起草)|起草)(?:一下)?/.test(request)) return null;
    if (/(?:不要|不用|别|先不|暂不)(?:帮我)?(?:起草|写邮件|写消息|写短信|生成草稿)|只是个假设|只是举例|只讨论|不是让你/.test(request)) return null;
    const opening = request.split(/[，,：:\n]/, 1)[0];
    const target = opening.match(/邮件|消息|短信|微信|回信/);
    if (!target || target.index > 40) return null;
    if (/[“”"'「」]|假设|如果|比如|举例|引用|代码|脚本|教程|不要|不用|别写|不想|只讨论/.test(opening)) return null;
    if (/^(?:时|的时候|的话|是什么|是什么意思)/.test(opening.slice(target.index + target[0].length))) return null;
    if (/^(?:还没有连接对话模型|模型暂时不可用|模型超时|刚才记忆或来源|我听到这里可能涉及安全)/.test(answer.text)) return null;
    return {title: opening.slice(0, 60), text: answer.text};
  }
  window.XinjiActionCards = {html, bind, chatDraft};
})();
