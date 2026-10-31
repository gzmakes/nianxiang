/* File input lives in the browser: the server receives only the confirmed preview. */
window.XinjiFilePicker = {
  mount(container, {sessionId, onConfirm, autoAttach = false, isCurrent = () => true}) {
    container.innerHTML = autoAttach ? `<div class="connection-card"><div class="connection-card-header"><span class="connection-card-icon" aria-hidden="true">⌂</span><h3>连接本机资料</h3></div>
      <p class="connection-value">选一点你愿意分享的背景，接着一起聊。</p>
      <p class="connection-scope">只读所选文本，最多 3 份，每份 256 KB，保存前 4000 字。相关片段会发送给当前模型。</p>
      <label class="connection-file-label">授权并选择文件<input type="file" multiple accept=".md,.markdown,.txt,.json,.py,.ts,.js,.csv" aria-label="授权并选择文本文件" /></label>
      <div class="file-previews" hidden></div><p class="note file-hint" role="status">在系统窗口选择完成后，自动接入当前对话。</p>
      <button type="button" class="btn primary small file-confirm is-hidden" disabled>授权</button></div>` : `<p class="note">最多选择 3 份 UTF-8 文本（.md / .markdown / .txt / .json / .py / .ts / .js / .csv），每份不超过 256 KB。先在本页面预览每份前 4000 个字符，确认后才传给本机服务并保存。新接入的文件可逐份移除；以前合并接入的资料仍按原批次移除。后续聊天可能按问题检索每份来源最多 3 段；当前对话的所有来源合计最多 8 段、3200 字（含来源标注），连同文件名、问题和必要上下文发送给已配置的模型服务；无匹配时不发送检索片段，但其他上下文仍可能发送。</p>
      <input type="file" multiple accept=".md,.markdown,.txt,.json,.py,.ts,.js,.csv" aria-label="选择文本文件" />
      <div class="file-previews"></div><p class="note file-hint" role="status">只读取你选择的文件。</p>
      <button type="button" class="btn primary small file-confirm" disabled>${sessionId ? '确认接入当前对话' : '确认并开始对话'}</button>`;
    const input = container.querySelector('input'), previews = container.querySelector('.file-previews');
    const hint = container.querySelector('.file-hint'), button = container.querySelector('.file-confirm');
    let selected = [], generation = 0;
    input.onchange = async () => {
      const turn = ++generation;
      selected = []; previews.replaceChildren(); button.disabled = true;
      const files = Array.from(input.files || []);
      if (!files.length) { hint.textContent = '只读取你选择的文件。'; return; }
      if (files.length > 3) { hint.textContent = '最多选择 3 份文件。'; return; }
      hint.textContent = '正在本页面读取所选文件…';
      try {
        const result = [];
        for (const f of files) {
          if (!/\.(md|markdown|txt|json|py|ts|js|csv)$/i.test(f.name) || f.name.length > 200 || /[\\/\x00-\x1f]/.test(f.name)) throw Error('文件名或类型不支持。');
          if (!f.size || f.size > 256 * 1024) throw Error('文件为空或超过 256 KB。');
          const content = new TextDecoder('utf-8', {fatal: true}).decode(await f.arrayBuffer());
          if (!content.trim() || content.includes('\0')) throw Error('文件为空或不是可用的文本。');
          // Match Swift Unicode scalars, Kotlin code points and the Python API;
          // UTF-16 slicing can otherwise leave half an emoji at this boundary.
          const characters = Array.from(content);
          result.push({name: f.name, text: characters.slice(0, 4000).join(''), truncated: characters.length > 4000});
        }
        if (turn !== generation || !isCurrent()) return;
        for (const f of result) {
          const section = document.createElement('section'), title = document.createElement('p'), textarea = document.createElement('textarea');
          title.textContent = `${f.name} · ${f.truncated ? '仅前 4000 个字符' : '完整内容'}`;
          textarea.readOnly = true; textarea.rows = 5; textarea.value = f.text; textarea.setAttribute('aria-label', `${f.name} 内容预览`);
          section.appendChild(title); section.appendChild(textarea); previews.appendChild(section);
        }
        selected = result.map(({name, text}) => ({name, text}));
        hint.textContent = '请核对以上内容；确认前不会发送到本机服务。';
        button.disabled = false;
        if (autoAttach) await button.onclick();
      } catch (e) { if (turn === generation) hint.textContent = e.message || '读取失败，请重新选择 UTF-8 文本。'; }
    };
    button.onclick = async () => {
      if (!selected.length || button.disabled || !isCurrent()) return;
      button.disabled = true; input.disabled = true;
      hint.textContent = '正在接入…';
      try { await onConfirm(selected, sessionId); selected = []; previews.replaceChildren(); input.value = ''; }
      catch (e) {
        if (e.status >= 400 && e.status < 500) { hint.textContent = e.message; button.disabled = false; input.disabled = false; }
        else { hint.textContent = '接入结果未确认。请返回对话并刷新，确认后再重试。'; input.disabled = false; }
      }
    };
  }
};
