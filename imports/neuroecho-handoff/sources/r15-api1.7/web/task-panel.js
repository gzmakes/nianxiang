/* Task suggestions and browser-local tasks. Loaded after app.js. */
(() => {
  'use strict';
  const root = document.getElementById('task-panel-enhancements');
  const legacy = document.getElementById('task-legacy');
  const input = document.getElementById('input');
  const composer = document.getElementById('composer');
  if (!root || !legacy || !input) return;

  const key = 'xinji_personal_tasks_v1';
  const mime = 'application/x-xinji-task-prompt';
  const defaults = [
    { icon: '☷', title: '整理今日重点', detail: '把你今天要做的事情列清楚，排出最值得先完成的一件。' },
    { icon: '⌧', title: '拆解一项计划', detail: '把一个目标拆成几步，明确下一步现在就能开始做什么。' },
    { icon: '✣', title: '梳理混乱想法', detail: '把你脑中的信息分组整理，提炼出重点、疑问和待决定事项。' },
    { icon: '≡', title: '回顾近期进展', detail: '根据我们的对话整理已经完成、暂时卡住和接下来要继续的事情。' },
    { icon: '◌', title: '清理待办清单', detail: '合并重复事项，删掉不再重要的内容，把剩下的安排得更清楚。' }
  ];
  let tasks = [];
  let storageAvailable = true;
  let currentView = 'default';
  root.innerHTML = `
    <div class="task-enhancement-actions"><button type="button" class="task-create-link">＋ 创建任务</button></div>
    <div class="task-view-switch" role="group" aria-label="任务视图">
      <button type="button" data-task-view="mine" aria-pressed="false">☷ 我的任务</button>
      <button type="button" data-task-view="default" aria-pressed="true">◷ 默认任务</button>
    </div>
    <form class="task-create-form" hidden>
      <label>任务名称<input name="title" required maxlength="80" autocomplete="off" placeholder="例如：整理本周计划"></label>
      <label>任务说明<textarea name="detail" rows="3" maxlength="1000" placeholder="希望念响如何帮你？（可选）"></textarea></label>
      <div class="task-form-actions"><button type="submit">保存任务</button><button type="button" class="task-form-cancel">取消</button></div>
    </form>
    <p class="task-storage-note">自己创建的任务保存在此浏览器中，暂不同步到其他设备。</p>
    <p class="task-status" role="status" aria-live="polite"></p>
    <div class="task-default-view"><h4>推荐任务</h4><p class="task-view-hint">点击＋添加到对话，也可拖入输入框。</p><div class="task-cards"></div></div>
    <div class="task-mine-view" hidden><div class="task-cards"></div></div>`;
  const form = root.querySelector('.task-create-form');
  const status = root.querySelector('.task-status');
  const defaultView = root.querySelector('.task-default-view');
  const mineView = root.querySelector('.task-mine-view');
  const buttons = [...root.querySelectorAll('[data-task-view]')];
  const say = text => { status.textContent = text; };
  const load = () => {
    try {
      const raw = localStorage.getItem(key);
      const value = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(value) || !value.every(item => item && typeof item.title === 'string' && typeof item.detail === 'string')) throw new Error('invalid task data');
      tasks = value;
      storageAvailable = true;
    } catch (_) {
      tasks = [];
      storageAvailable = false;
      say('无法读取本地任务，请检查浏览器存储设置；现有数据不会被覆盖。');
    }
  };
  const addToConversation = text => {
    if (!text) return;
    const separator = input.value && !input.value.endsWith('\n') ? '\n' : '';
    input.value += separator + text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    window.XinjiComposerDraft?.save();
    input.focus();
    say('已添加到对话输入框，可继续编辑后发送。');
  };
  const makeCard = (task, index, kind) => {
    const card = document.createElement('article');
    card.className = 'task-suggestion-card';
    card.draggable = true;
    const icon = document.createElement('span'); icon.className = 'task-suggestion-icon'; icon.textContent = task.icon || '＋'; icon.setAttribute('aria-hidden', 'true');
    const copy = document.createElement('div'); copy.className = 'task-suggestion-copy';
    const title = document.createElement('strong'); title.textContent = task.title;
    const detail = document.createElement('p'); detail.textContent = task.detail;
    copy.append(title, detail);
    const button = document.createElement('button'); button.type = 'button'; button.className = 'task-suggestion-add'; button.textContent = '＋'; button.setAttribute('aria-label', `将${task.title}添加到对话`);
    const prompt = task.detail || task.title;
    button.addEventListener('click', () => addToConversation(prompt));
    card.addEventListener('dragstart', event => { event.dataTransfer.setData(mime, JSON.stringify({ kind, index })); event.dataTransfer.effectAllowed = 'copy'; card.classList.add('is-dragging'); });
    card.addEventListener('dragend', () => { card.classList.remove('is-dragging'); composer?.classList.remove('task-drop-active'); });
    card.append(icon, copy, button);
    return card;
  };
  const render = () => {
    const recommended = defaultView.querySelector('.task-cards'); recommended.replaceChildren(...defaults.map((t, i) => makeCard(t, i, 'default')));
    const mine = mineView.querySelector('.task-cards');
    if (tasks.length) mine.replaceChildren(...tasks.map((t, i) => makeCard(t, i, 'mine')));
    else { const empty = document.createElement('p'); empty.className = 'task-empty'; empty.textContent = storageAvailable ? '还没有创建任务。点击上方「创建任务」开始。' : '本地任务暂时无法读取。'; mine.replaceChildren(empty); }
  };
  const setView = view => {
    currentView = view;
    defaultView.hidden = view !== 'default';
    mineView.hidden = view !== 'mine';
    legacy.hidden = view !== 'mine';
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.taskView === view)));
  };
  buttons.forEach(button => button.addEventListener('click', () => setView(button.dataset.taskView)));
  root.querySelector('.task-create-link').addEventListener('click', () => { form.hidden = !form.hidden; if (!form.hidden) form.elements.title.focus(); });
  root.querySelector('.task-form-cancel').addEventListener('click', () => { form.hidden = true; });
  form.addEventListener('submit', event => {
    event.preventDefault();
    const title = form.elements.title.value.trim();
    const detail = form.elements.detail.value.trim();
    if (!title) { form.elements.title.focus(); return; }
    if (!storageAvailable) { say('任务未保存：本地存储不可用或已有数据无法读取。'); return; }
    const next = [...tasks, { title, detail: detail || title }];
    try { localStorage.setItem(key, JSON.stringify(next)); }
    catch (_) { say('任务未保存：浏览器本地存储不可用或空间不足。请保留表单内容后重试。'); return; }
    tasks = next; render(); setView('mine'); form.reset(); form.hidden = true; say('任务已保存在此浏览器。');
  });
  const hasTask = event => Array.from(event.dataTransfer?.types || []).includes(mime);
  input.addEventListener('dragover', event => { if (!hasTask(event)) return; event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; composer?.classList.add('task-drop-active'); });
  input.addEventListener('dragleave', () => composer?.classList.remove('task-drop-active'));
  input.addEventListener('drop', event => {
    if (!hasTask(event)) return;
    event.preventDefault(); composer?.classList.remove('task-drop-active');
    try { const item = JSON.parse(event.dataTransfer.getData(mime)); const task = (item.kind === 'default' ? defaults : item.kind === 'mine' ? tasks : [])[item.index]; if (task) addToConversation(task.detail || task.title); } catch (_) { say('无法添加这项任务，请使用任务卡上的＋按钮。'); }
  });
  window.addEventListener('storage', event => { if (event.key === key) { load(); render(); setView(currentView); } });
  load(); render(); setView('default');
})();
