/* User-requested tasks stay in this browser and are tied to a specific chat entry. */
(() => {
  'use strict';
  const key = 'xinji_personal_tasks_v1';
  const lockName = 'xinji-personal-tasks-v1';
  let localQueue = Promise.resolve();
  function taskFrom(part) {
    if (!part || typeof part.text !== 'string' || typeof part.id !== 'string' || !part.id) return null;
    const marker = /^[ \t]*我要创建任务：/m.exec(part.text);
    if (!marker) return null;
    const detail = part.text.slice(marker.index + marker[0].length).trim();
    if (!detail) return null;
    const title = detail.split(/\r?\n/).find(line => line.trim())?.trim().slice(0, 80) || '';
    return {title, detail, originMessageId: part.id, sessionId: part.sessionId || ''};
  }
  function append(task) {
    const raw = localStorage.getItem(key);
    const items = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(items) || !items.every(item => item && typeof item.title === 'string' && typeof item.detail === 'string')) throw Error('invalid task storage');
    if (items.some(item => item.originMessageId === task.originMessageId)) return false;
    localStorage.setItem(key, JSON.stringify([...items, task]));
    window.dispatchEvent(new CustomEvent('xinji-personal-tasks-change'));
    return true;
  }
  function record(part) {
    const task = taskFrom(part);
    if (!task) return Promise.resolve(false);
    // Web Locks serializes read/modify/write across tabs where available.
    if (globalThis.navigator?.locks?.request) return Promise.resolve().then(() => navigator.locks.request(lockName, () => append(task)));
    // Same-page fallback for browsers that do not expose Web Locks.
    const next = localQueue.then(() => append(task));
    localQueue = next.catch(() => {});
    return next;
  }
  window.XinjiPersonalTasks = {record};
})();
