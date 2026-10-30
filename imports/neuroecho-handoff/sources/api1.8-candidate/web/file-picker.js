/* Text is previewed in the browser; Word is parsed in memory by the Echo service. */
window.XinjiFilePicker = {
  mount(container, {sessionId, onConfirm}) {
    container.innerHTML = `<p class="note">最多选择 3 份 UTF-8 文本（.md / .markdown / .txt / .json / .py / .ts / .js / .csv，每份不超过 256 KB）或 Word 文档（.docx，每份不超过 2 MB）。Word 文件会发送到运行回响服务的设备，在内存中提取正文供预览，不保存原文件或发送给模型；图片、扫描内容和批注不会读取。先预览每份前 4000 个字符，确认后才接入对话。新接入的文件可逐份移除；以前合并接入的资料仍按原批次移除。后续聊天可能按问题检索每份来源最多 3 段；当前对话的所有来源合计最多 8 段、3200 字（含来源标注），连同文件名、问题和必要上下文发送给已配置的模型服务；无匹配时不发送检索片段，但其他上下文仍可能发送。</p>
      <input type="file" multiple accept=".md,.markdown,.txt,.json,.py,.ts,.js,.csv,.docx" aria-label="选择文本或 Word 文件" />
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
      hint.textContent = '正在读取所选文件…';
      try {
        const result = [];
        for (const f of files) {
          if (!/\.(md|markdown|txt|json|py|ts|js|csv|docx)$/i.test(f.name) || f.name.length > 200 || /[\\/\x00-\x1f]/.test(f.name)) throw Error('文件名或类型不支持。');
          const word = /\.docx$/i.test(f.name);
          if (!f.size || f.size > (word ? 2 * 1024 * 1024 : 256 * 1024)) throw Error(word ? 'Word 文件为空或超过 2 MB。' : '文件为空或超过 256 KB。');
          let content, truncated = false;
          if (word) {
            const bytes = new Uint8Array(await f.arrayBuffer());
            if (bytes.length !== f.size) throw Error('文件读取不完整，请重新选择。');
            let binary = '';
            for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
            const response = await fetch('/api/local-files/preview-document', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:f.name, data:btoa(binary)})});
            let preview;
            try { preview = await response.json(); } catch (_) { throw Error('Word 预览返回格式无效。'); }
            if (!response.ok) throw Error(typeof preview.detail === 'string' ? preview.detail : '无法读取 Word 文档。');
            if (preview.name !== f.name || typeof preview.text !== 'string' || typeof preview.truncated !== 'boolean') throw Error('Word 预览返回格式无效。');
            content = preview.text; truncated = preview.truncated;
          } else content = new TextDecoder('utf-8', {fatal: true}).decode(await f.arrayBuffer());
          if (!content.trim() || content.includes('\0')) throw Error('文件为空或不是可用的文本。');
          // Match Swift Unicode scalars, Kotlin code points and the Python API;
          // UTF-16 slicing can otherwise leave half an emoji at this boundary.
          const characters = Array.from(content);
          result.push({name: f.name, text: characters.slice(0, 4000).join(''), truncated: truncated || characters.length > 4000});
        }
        if (turn !== generation) return;
        for (const f of result) {
          const section = document.createElement('section'), title = document.createElement('p'), textarea = document.createElement('textarea');
          title.textContent = `${f.name} · ${f.truncated ? '仅前 4000 个字符' : '完整内容'}`;
          textarea.readOnly = true; textarea.rows = 5; textarea.value = f.text; textarea.setAttribute('aria-label', `${f.name} 内容预览`);
          section.appendChild(title); section.appendChild(textarea); previews.appendChild(section);
        }
        selected = result.map(({name, text}) => ({name, text}));
        hint.textContent = '请核对以上内容；确认前不会保存或发送给模型。';
        button.disabled = false;
      } catch (e) { if (turn === generation) hint.textContent = e.message || '读取失败，请检查文件并重试。'; }
    };
    button.onclick = async () => {
      if (!selected.length || button.disabled) return;
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
