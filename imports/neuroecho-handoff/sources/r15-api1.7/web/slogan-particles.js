/* 标语粒子（2026-10-31，产品要求）：桌面版名字两侧的两半标语，每 90 秒化作粒子散开，停一下再聚回文字。
   只是视觉，不改任何状态。开了「减少动态」或系统偏好减少动态、页面不可见、窗口窄于 900px 时跳过这一轮。 */
window.XinjiSloganParticles = (() => {
  const root = document.documentElement;
  const INTERVAL = 90000, SCATTER = 1100, HOLD = 240, GATHER = 1200, STEP = 2, PAD = 32;
  const reducedMotion = () => root.dataset.reduceMotion === 'true' || (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  const parts = [...document.querySelectorAll('#app .brand-line [data-slogan-part]')];
  const easeOut = t => 1 - Math.pow(1 - t, 3);
  const easeInOut = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  let playing = false, timer = null;

  // 把一半标语按当前字体画到离屏画布上，采样成粒子（屏幕坐标以 CSS 像素计）。
  function sample(part) {
    const text = part.querySelector('span');
    if (!text) return null;
    const rect = text.getBoundingClientRect(), hostRect = part.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const style = getComputedStyle(text);
    const w = Math.ceil(hostRect.width) + PAD * 2, h = Math.ceil(hostRect.height) + PAD * 2;
    const off = document.createElement('canvas');
    off.width = Math.ceil(w * dpr); off.height = Math.ceil(h * dpr);
    const ctx = off.getContext('2d', { willReadFrequently: true });
    if (!ctx) return null;
    ctx.scale(dpr, dpr);
    ctx.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    if ('letterSpacing' in ctx) ctx.letterSpacing = style.letterSpacing === 'normal' ? '0px' : style.letterSpacing;
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#000';
    const ox = rect.left - hostRect.left + PAD, oy = rect.top - hostRect.top + PAD + rect.height / 2;
    ctx.fillText(text.textContent, ox, oy);
    const data = ctx.getImageData(0, 0, off.width, off.height).data;
    const particles = [];
    const step = Math.max(1, Math.round(STEP * dpr));
    for (let y = 0; y < off.height; y += step) {
      for (let x = 0; x < off.width; x += step) {
        const alpha = data[(y * off.width + x) * 4 + 3];
        if (alpha < 110) continue;
        const angle = Math.random() * Math.PI * 2, dist = 10 + Math.random() * 26;
        particles.push({
          x: x / dpr, y: y / dpr,
          tx: x / dpr + Math.cos(angle) * dist, ty: y / dpr + Math.sin(angle) * dist - 6 - Math.random() * 8,
          r: .9 + Math.random() * .7, delay: Math.random() * .25, a: alpha / 255,
        });
      }
    }
    return { particles, w, h, dpr, color: style.color || '#56627A' };
  }

  function prepare(part) {
    const info = sample(part);
    if (!info || !info.particles.length) return null;
    let canvas = part.querySelector('canvas');
    if (!canvas) { canvas = document.createElement('canvas'); canvas.setAttribute('aria-hidden', 'true'); part.appendChild(canvas); }
    canvas.width = Math.ceil(info.w * info.dpr); canvas.height = Math.ceil(info.h * info.dpr);
    canvas.style.width = info.w + 'px'; canvas.style.height = info.h + 'px';
    canvas.style.left = -PAD + 'px'; canvas.style.top = -PAD + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(info.dpr, 0, 0, info.dpr, 0, 0);
    return { part, canvas, ctx, ...info };
  }

  function draw(scene, elapsed) {
    const { ctx, particles, w, h, color } = scene;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = color;
    for (const p of particles) {
      let x, y, alpha, r;
      if (elapsed < SCATTER) {
        const t = easeOut(Math.max(0, Math.min(1, (elapsed / SCATTER - p.delay) / (1 - p.delay))));
        x = p.x + (p.tx - p.x) * t; y = p.y + (p.ty - p.y) * t; alpha = p.a * (1 - .55 * t); r = p.r * (1 - .35 * t);
      } else if (elapsed < SCATTER + HOLD) {
        const wob = Math.sin((elapsed / 180) + p.delay * 20) * .6;
        x = p.tx + wob; y = p.ty + wob * .5; alpha = p.a * .45; r = p.r * .65;
      } else {
        const t = easeInOut(Math.max(0, Math.min(1, ((elapsed - SCATTER - HOLD) / GATHER - p.delay * .6) / (1 - p.delay * .6))));
        x = p.tx + (p.x - p.tx) * t; y = p.ty + (p.y - p.ty) * t; alpha = p.a * (.45 + .55 * t); r = p.r * (.65 + .35 * t);
      }
      ctx.globalAlpha = alpha;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function eligible() {
    return parts.length && !playing && !document.hidden && !reducedMotion() && window.innerWidth >= 900 && parts.every(part => part.getClientRects().length);
  }

  async function play() {
    if (!eligible()) return false;
    playing = true;
    try { await document.fonts?.ready; } catch (_) {}
    const scenes = parts.map(prepare).filter(Boolean);
    if (!scenes.length) { playing = false; return false; }
    const total = SCATTER + HOLD + GATHER;
    await new Promise(resolve => {
      const start = performance.now();
      for (const scene of scenes) { draw(scene, 0); scene.part.classList.add('is-particles'); }
      function frame(now) {
        const elapsed = now - start;
        if (elapsed >= total || document.hidden) {
          for (const scene of scenes) { scene.ctx.clearRect(0, 0, scene.w, scene.h); scene.part.classList.remove('is-particles'); }
          resolve(); return;
        }
        // 聚回的最后一段让文字先淡入，粒子随之消失，看起来是粒子“落回”字里。
        if (elapsed >= total - 320) for (const scene of scenes) scene.part.classList.remove('is-particles');
        for (const scene of scenes) draw(scene, elapsed);
        requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });
    playing = false;
    return true;
  }

  function schedule() {
    if (timer) clearInterval(timer);
    timer = setInterval(() => { void play(); }, INTERVAL);
  }
  if (parts.length) {
    schedule();
    document.addEventListener('visibilitychange', () => { if (!document.hidden) schedule(); });
  }
  return { play, interval: INTERVAL };
})();
