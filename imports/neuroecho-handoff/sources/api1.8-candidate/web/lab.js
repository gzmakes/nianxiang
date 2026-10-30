/* Local-only design experiments. No API, storage, analytics, or device access. */
(() => {
  const instances = new WeakMap();
  const clamp = n => Math.max(-100, Math.min(100, Number(n) || 0));
  function tint(x, y) {
    const u = (clamp(x) + 100) / 200, w = (clamp(y) + 100) / 200;
    const colors = [[131,151,204],[130,190,181],[215,139,140],[202,207,121]];
    return 'rgb(' + colors[0].map((_, i) => Math.round((1-w)*((1-u)*colors[0][i]+u*colors[1][i])+w*((1-u)*colors[2][i]+u*colors[3][i]))).join(', ') + ')';
  }
  function mount(container) {
    if (!container) return;
    close(container);
    container.innerHTML = `<section class="echo-lab" aria-label="实验区"><div class="echo-lab-heading"><div><span class="echo-lab-kicker">EXPERIMENTS · 实验区</span><h3>一起试试新想法</h3></div><span class="echo-lab-badge">体验探索</span></div><p>这里收集还在探索中的交互。你可以随时试，也可以什么都不选。</p><div class="echo-lab-list"><article class="echo-lab-entry"><div><b>心情表达方式</b><p>同一种感受，用地图或滑杆来表达。</p></div><button type="button" data-lab-open>试一试</button></article></div><div data-lab-editor hidden></div></section>`;
    const editor = container.querySelector('[data-lab-editor]');
    const open = container.querySelector('[data-lab-open]');
    let disposeEditor = () => {};
    function leave(restoreFocus = false) { disposeEditor(); disposeEditor = () => {}; editor.replaceChildren(); editor.hidden = true; if (restoreFocus) open.focus?.(); }
    open.onclick = () => {
      if (!editor.hidden) return;
      editor.hidden = false;
      editor.innerHTML = `<div class="echo-lab-experiment"><div class="echo-lab-title"><div><span class="echo-lab-kicker">01 · FEELING</span><h4>找到此刻的位置</h4></div><button type="button" class="echo-lab-close" data-lab-close aria-label="关闭心情实验">×</button></div><p>同一种心情，未必只有一个名字。试试两种方式，看看哪一种更适合你。</p><div class="echo-lab-switch" aria-label="选择表达方式"><button type="button" data-lab-plane-mode aria-pressed="true">A · 心情地图</button><button type="button" data-lab-slider-mode aria-pressed="false">B · 两条滑杆</button></div><div class="echo-lab-stage"><div data-lab-map-panel><div class="echo-lab-axis-mid">↑ 更有活力</div><div class="echo-lab-plane" data-lab-plane role="group" aria-label="心情地图，也可以用两条滑杆调整"><span data-lab-point class="echo-lab-point"></span></div><div class="echo-lab-axis"><span>更不舒服</span><span>更舒服 →</span></div><div class="echo-lab-axis-mid">↓ 更平缓</div><button type="button" class="echo-lab-text-button" data-lab-accessible>使用滑杆或键盘调整</button></div><div class="echo-lab-sliders" data-lab-sliders hidden><label>舒服的程度<input data-lab-x type="range" min="-100" max="100" value="0" step="1"><span class="echo-lab-axis"><span>更不舒服</span><span>更舒服</span></span></label><label>活力的程度<input data-lab-y type="range" min="-100" max="100" value="0" step="1"><span class="echo-lab-axis"><span>更平缓</span><span>更有活力</span></span></label></div><p class="echo-lab-reading" data-lab-reading aria-live="polite">还在寻找自己的位置</p><label class="echo-lab-reflection">想给它起个名字吗？（可留空）<textarea data-lab-note rows="2" maxlength="300" placeholder="也许有点复杂，或者我还说不清……"></textarea></label></div><p class="echo-lab-disclosure">这是交互实验，尚未验证疗效；坐标与颜色不判断你的情绪。输入只留在当前页面，关闭实验或离开设置后清除，不会保存、上传或写入心情记录。</p><div class="echo-lab-actions"><button type="button" data-lab-reset>清空本次实验</button><button type="button" data-lab-done>结束实验</button></div></div>`;
      const q = selector => editor.querySelector('[data-lab-' + selector + ']');
      const plane=q('plane'), point=q('point'), xInput=q('x'), yInput=q('y'), reading=q('reading'), note=q('note');
      let x=0, y=0, touched=false;
      function render() {
        point.style.left=(x+100)/2+'%'; point.style.top=(100-y)/2+'%';
        xInput.value=String(x); yInput.value=String(y);
        plane.style.background='linear-gradient(145deg, '+tint(x,y)+', #e8ddd3)';
        const a=x>25?'偏舒服':x< -25?'偏不舒服':'舒服程度还不确定';
        const b=y>25?'偏有活力':y< -25?'偏平缓':'活力程度还不确定';
        reading.textContent=touched?a+' · '+b:'还在寻找自己的位置';
      }
      function mode(isPlane) {
        q('map-panel').hidden=!isPlane; q('sliders').hidden=isPlane;
        q('plane-mode').setAttribute('aria-pressed', String(isPlane)); q('slider-mode').setAttribute('aria-pressed', String(!isPlane));
      }
      function position(event) {
        const rect=plane.getBoundingClientRect();
        if (!(rect.width > 0 && rect.height > 0)) return;
        x=clamp(Math.round((event.clientX-rect.left)/rect.width*200-100));
        y=clamp(Math.round(100-(event.clientY-rect.top)/rect.height*200)); touched=true; render();
      }
      plane.onpointerdown = event => { plane.setPointerCapture?.(event.pointerId); position(event); };
      plane.onpointermove = event => { if (plane.hasPointerCapture?.(event.pointerId)) position(event); };
      xInput.oninput=()=>{x=clamp(xInput.value);touched=true;render();};
      yInput.oninput=()=>{y=clamp(yInput.value);touched=true;render();};
      q('plane-mode').onclick=()=>mode(true); q('slider-mode').onclick=()=>mode(false);
      q('accessible').onclick=()=>{mode(false); xInput.focus?.();};
      q('reset').onclick=()=>{x=0;y=0;touched=false;note.value='';render();};
      q('close').onclick=()=>leave(true); q('done').onclick=()=>leave(true);
      disposeEditor = () => { x=0; y=0; touched=false; note.value=''; };
      render();
    };
    instances.set(container, {leave});
  }
  function close(container) {
    if (!container) return;
    const instance=instances.get(container);
    if (instance) instance.leave();
  }
  window.XinjiLab = {mount, close, tint};
})();
