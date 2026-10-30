/* 心情记录卡的滑杆填充色（2026-10-31，产品要求）：把当前值写成 --p，样式里用它画已填充的那段。
   只改外观；记录、草稿和提交仍由 mood.js 负责。 */
(() => {
  const update = input => {
    const min = Number(input.min) || -1, max = Number(input.max) || 1, value = Number(input.value) || 0;
    input.style.setProperty('--p', `${(((value - min) / (max - min)) * 100).toFixed(1)}%`);
  };
  const all = () => document.querySelectorAll('.mood-sliders input[type=range]').forEach(update);
  let raf = 0;
  const schedule = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; all(); }); };
  for (const type of ['input', 'change', 'pointermove', 'pointerup', 'keyup', 'click']) document.addEventListener(type, schedule, { capture: true, passive: true });
  const start = () => { all(); new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true }); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
