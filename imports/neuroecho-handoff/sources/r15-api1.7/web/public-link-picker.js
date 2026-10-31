/* A public URL is a readable source, never evidence of account authorization. */
window.XinjiPublicLinkPicker = {
  mount(container, {sourceId, api, isCurrent, onConfirm, autoAttach = false}) {
    const name = sourceId === 'jike' ? '即刻公开帖子' : 'WaytoAGI 公开资料';
    const supported = sourceId === 'jike' ? '支持 m.okjike.com/originalPosts/… 的公开动态链接。' : '支持 about.waytoagi.com 的介绍页及 www.waytoagi.com/zh/question/… 的问答页；飞书知识库链接请从飞书入口读取。';
    container.innerHTML = `<div class="connection-card"><div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">${sourceId === 'jike' ? '即' : 'W'}</span><h3>${name}</h3></div>
      <p class="note">${autoAttach ? "粘贴一页想一起看的内容，连接后就聊聊它。" : "粘贴你想一起看的公开链接。先读取并展示正文，由你核对后加入当前对话。"}</p>
      <p class="note">${supported}</p>
      <label>公开链接<input type="url" class="public-url" autocomplete="off" spellcheck="false" placeholder="https://…" /></label>
      <p class="connection-scope">只读这一页公开正文，相关片段会发送给当前模型。无需登录账号。</p><button type="button" class="btn primary small public-read">${autoAttach ? "授权" : "读取公开正文"}</button>
      <p class="note public-status" role="status">确认接入后，所选正文会保存在本机，并可在聊天时发送相关片段给当前模型。</p>
      <div class="public-preview"></div>
      <button type="button" class="btn primary small public-confirm${autoAttach ? " is-hidden" : ""}" disabled>确认接入当前对话</button></div>`;
    const input = container.querySelector('.public-url'), readButton = container.querySelector('.public-read');
    const status = container.querySelector('.public-status'), preview = container.querySelector('.public-preview');
    const confirm = container.querySelector('.public-confirm');
    let epoch = 0, result = null;
    const current = (version) => version === epoch && container.isConnected && isCurrent();
    input.oninput = () => { epoch++; result = null; confirm.disabled = true; readButton.disabled = false; preview.replaceChildren(); status.textContent = '链接已更改，请重新读取。'; };
    readButton.onclick = async () => {
      if (readButton.disabled) return;
      const url = input.value.trim(), version = ++epoch;
      result = null; confirm.disabled = true; preview.replaceChildren();
      try { if (new URL(url).protocol !== 'https:') throw Error(); }
      catch (_) { status.textContent = '请粘贴完整的 HTTPS 公开链接。'; return; }
      readButton.disabled = true; status.textContent = '正在向该平台读取真实正文…';
      try {
        const data = await api('/api/onboarding/real/read', {method:'POST',body:JSON.stringify({source_id:sourceId,url,...(autoAttach ? {start_intro:true} : {})})});
        if (!current(version)) return;
        if (!data.ok) { globalThis.NianxiangSound?.play('gentleError'); throw Error([data.error || '读取失败', data.hint].filter(Boolean).join(' · ')); }
        if (!data.preview_id || typeof data.text !== 'string' || !data.text.trim() || data.connector?.id !== sourceId) throw Error('没有取得可核对的正文，没有接入任何内容。');
        const heading = document.createElement('h4'), text = document.createElement('textarea');
        heading.textContent = data.title || name; text.value = data.text; text.readOnly = true; text.rows = 9;
        text.setAttribute('aria-label', name + '正文预览');
        preview.appendChild(heading); preview.appendChild(text);
        status.textContent = `已从原站读取 ${Array.from(data.text).length} 字${data.truncated ? '（正文超限，已截取）' : ''}。请核对后确认；预览 10 分钟有效。`;
        result = data; confirm.disabled = false;
        if (autoAttach) await confirm.onclick();
      } catch (error) { if (current(version)) status.textContent = error.message; }
      finally { if (current(version)) readButton.disabled = false; }
    };
    confirm.onclick = async () => {
      if (!result || confirm.disabled || !current(epoch)) return;
      const version = epoch, selected = result;
      confirm.disabled = true; input.disabled = true; readButton.disabled = true; status.textContent = '正在接入当前对话…';
      try { await onConfirm(selected); }
      catch (error) {
        if (!current(version)) return;
        result = null; preview.replaceChildren(); input.disabled = false; readButton.disabled = false;
        status.textContent = `${error.message || '接入结果未确认'} 请先核对已接入资料；如未接入，再重新读取。`;
      }
    };
  }
};
