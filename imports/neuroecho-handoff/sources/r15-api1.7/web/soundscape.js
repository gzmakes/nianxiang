/* Opt-in local soundscape. Audio assets ship with the app; no external service is contacted. */
(function (global) {
  'use strict';
  const KEY = 'xinji_soundscape_v1';
  const themes = {dawn:'晨曦 · 温暖陪伴', breath:'呼吸 · 舒缓', tide:'深潮 · 安静专注', stardust:'星尘 · 灵感', circuit:'电路 · 探索', pulse:'心跳 · 陪伴'};
  const randomThemes = ['dawn', 'breath', 'tide'];
  const events = new Set(['wake', 'send', 'receive', 'success', 'gentleError', 'notify', 'toggleOn', 'toggleOff']);
  const base = new URL('sounds/', document.currentScript.src).href;
  const defaults = {music:false, effects:false, theme:'random', musicVolume:0.22, effectsVolume:0.35};
  let saved = {}; try { saved = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (_) {}
  let config = {music:saved.music === true, effects:saved.effects === true,
    theme:saved.theme === 'random' || themes[saved.theme] ? saved.theme : defaults.theme,
    musicVolume:Number.isFinite(saved.musicVolume) ? Math.max(0,Math.min(1,saved.musicVolume)) : defaults.musicVolume,
    effectsVolume:Number.isFinite(saved.effectsVolume) ? Math.max(0,Math.min(1,saved.effectsVolume)) : defaults.effectsVolume};
  let recording = false, voice = false, unlocked = false, current = null, previous = null, preview = false, previewTimer = null, effectTimer = null, sequence = 0, error = '';
  let guiding = false, guidePaused = false, guideMuted = false, guideElapsed = 0, guideStarted = 0, guideTimer = null, guideClockRunning = false, lastPublicState = '';
  const music = new Audio(); music.preload = 'none'; music.loop = true;
  const sfx = new Audio(); sfx.preload = 'none';
  const panels = new Set();
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(config)); } catch (_) {} };
  const quiet = () => { const resume = document.querySelector('[data-companion-boundary] [data-b-resume]'); return !!resume && !resume.hidden; };
  const blocked = () => recording || voice || document.hidden || quiet();
  const guideSound = () => guiding && !guidePaused && !guideMuted;
  const wantsMusic = () => guideSound() || (!guiding && (preview || config.music));
  function guideTime() {
    if (!guiding || guidePaused || blocked()) return guideElapsed;
    if (guideMuted) return guideElapsed + (guideClockRunning ? Date.now() - guideStarted : 0);
    return Number.isFinite(music.currentTime) ? music.currentTime * 1000 : guideElapsed;
  }
  function freezeGuide() {
    if (!guiding || guidePaused) return;
    if (guideMuted) {
      if (guideClockRunning) guideElapsed += Date.now() - guideStarted;
    } else if (Number.isFinite(music.currentTime)) guideElapsed = music.currentTime * 1000;
    guideClockRunning = false;
  }
  function resumeGuideClock() {
    if (guiding && !guidePaused && guideMuted && !blocked()) { guideStarted = Date.now(); guideClockRunning = true; }
  }
  function publicState() { return {music:config.music, active:guiding ? !guideMuted : config.music, effects:config.effects, theme:config.theme, playing:!music.paused, blocked:blocked(), guiding, guidePaused, guideMuted, error}; }
  function announceState() {
    const state = publicState(), signature = JSON.stringify(state);
    if (signature !== lastPublicState) { lastPublicState = signature; global.dispatchEvent(new CustomEvent('nianxiang-sound-change', {detail:state})); }
  }
  function choose() {
    if (config.theme !== 'random') return config.theme;
    const pool = randomThemes.filter(item => item !== previous);
    return pool[Math.floor(Math.random() * pool.length)];
  }
  function cleanPanels() { for (const panel of panels) if (!panel.isConnected) panels.delete(panel); }
  function render() {
    cleanPanels();
    for (const panel of panels) {
      panel.querySelector('[data-sound-music]').checked = config.music;
      panel.querySelector('[data-sound-effects]').checked = config.effects;
      panel.querySelector('[data-sound-theme]').value = config.theme;
      panel.querySelector('[data-sound-music-volume]').value = config.musicVolume;
      panel.querySelector('[data-sound-effects-volume]').value = config.effectsVolume;
      const btn = panel.querySelector('[data-sound-preview]');
      btn.textContent = preview ? '停止试听' : '试听';
      btn.setAttribute('aria-pressed', String(preview));
      const status = panel.querySelector('[data-sound-status]');
      status.textContent = error || (blocked() && (config.music || preview || guideSound()) ? (quiet() ? '先不打扰期间，声音已暂停。' : '语音或页面后台期间，声音已暂停。') : preview ? `正在试听${themes[current]}。` : config.music && !music.paused ? `正在播放${themes[current]}。` : config.music && !unlocked ? '已开启；点一下页面后开始播放。' : config.music ? '音乐已暂停；可在这里重新开启。' : '音乐默认关闭，想听时再开启。');
      const guide = panel.querySelector('[data-breath-status]');
      const elapsed = guideTime();
      const phase = (elapsed % 10000) / 1000;
      guide.textContent = !guiding ? '跟着节奏试一试，也可以按自己舒服的方式呼吸。' : guidePaused ? '已暂停，准备好再继续。' : `${phase < 4 ? '吸气' : '呼气'} · ${Math.ceil(phase < 4 ? 4 - phase : 10 - phase)} 秒${blocked() ? ' · 声音已暂停' : guideMuted ? ' · 引导已静音' : ''}`;
      panel.querySelector('[data-breath-start]').textContent = !guiding ? '开始呼吸' : guidePaused ? '继续' : '暂停';
      panel.querySelector('[data-breath-end]').hidden = !guiding;
      panel.querySelector('[data-breath-mute]').hidden = !guiding;
      panel.querySelector('[data-breath-mute]').textContent = guideMuted ? '开启引导声音' : '引导静音';
      panel.querySelector('[data-breath-mute]').setAttribute('aria-pressed', String(guideMuted));
    }
    announceState();
  }
  function halt() { ++sequence; music.pause(); }
  function clearPreview() { preview = false; clearTimeout(previewTimer); previewTimer = null; }
  function setSource(theme) { current = theme; previous = theme; music.src = base + 'bgm/' + theme + '_loop.mp3'; music.volume = config.musicVolume; }
  function startMusic(theme) {
    const ticket = ++sequence;
    if (theme) setSource(theme);
    if (!current || blocked() || !unlocked || !wantsMusic()) { music.pause(); render(); return; }
    global.XinjiAmbientMusic?.stop();
    music.volume = config.musicVolume; error = '';
    const result = music.play();
    if (result && typeof result.then === 'function') result.then(() => {
      if (ticket !== sequence) return;
      if (blocked() || !wantsMusic()) music.pause();
      render();
    }).catch(() => { if (ticket !== sequence) return; error = '暂时无法播放，请点击试听重试，或检查设备声音。'; clearPreview(); render(); });
    render();
  }
  function refreshAudio() {
    if (blocked()) { freezeGuide(); halt(); sfx.pause(); global.XinjiAmbientMusic?.stop(); }
    else { resumeGuideClock(); if (unlocked && wantsMusic()) startMusic(); }
    render();
  }
  function play(event, options = {}) {
    if (!events.has(event) || !config.effects || blocked()) return false;
    if (event === 'receive' && options.messageId != null) {
      let auto = true; try { auto = JSON.parse(localStorage.getItem('xinji_voice_autoplay_v1')) !== false; } catch (_) {}
      const messages = document.querySelectorAll('#messages .msg.assistant[data-message-id], #m-messages .msg.assistant[data-message-id]');
      const message = Array.from(messages).find(item => item.dataset.messageId === String(options.messageId));
      const clip = message?.querySelector('[data-voice-clip]');
      if (auto && clip && !clip.hidden) return false;
    }
    sfx.pause(); clearTimeout(effectTimer); sfx.src = base + 'sfx/dawn_' + event + '.wav'; sfx.volume = config.effectsVolume;
    const result = sfx.play(); if (result?.catch) result.catch(() => {});
    effectTimer = setTimeout(() => sfx.pause(), event === 'wake' ? 2200 : 1400);
    return true;
  }
  function setMusicEnabled(value) {
    config.music = !!value; unlocked = true; clearPreview(); error = ''; save();
    if (guiding) {
      freezeGuide();
      if (!config.music) { guideMuted = true; halt(); resumeGuideClock(); }
      else {
        const wasMuted = guideMuted; guideMuted = false;
        if (wasMuted) { try { music.currentTime = (guideElapsed % 40000) / 1000; } catch (_) {} }
        if (!guidePaused) startMusic();
      }
      render();
    } else if (config.music) startMusic(choose()); else { halt(); render(); }
    return publicState();
  }
  function mount(container) {
    if (!container || container.querySelector('.soundscape-settings')) return;
    const panel = document.createElement('section'); panel.className = 'soundscape-settings';
    panel.innerHTML = `<div class="soundscape-heading"><div><h3>声音与音乐</h3><p>让陪伴的声音按你的节奏出现</p></div><span aria-hidden="true">♫</span></div>
      <label class="soundscape-toggle"><span><b>背景音乐</b><small>开启后可随机播放或选择一首。</small></span><input type="checkbox" data-sound-music></label>
      <label class="soundscape-select"><span>陪伴氛围</span><select data-sound-theme aria-label="选择陪伴音乐"><option value="random">随机：晨曦、呼吸、深潮</option><option value="dawn">晨曦 · 温暖陪伴</option><option value="breath">呼吸 · 舒缓</option><option value="tide">深潮 · 安静专注</option><option value="stardust">星尘 · 灵感</option><option value="circuit">电路 · 探索</option><option value="pulse">心跳 · 陪伴</option></select><button type="button" data-sound-preview aria-pressed="false">试听</button></label>
      <label class="soundscape-volume"><span>音乐音量</span><input type="range" min="0" max="1" step="0.05" data-sound-music-volume aria-label="音乐音量"></label>
      <label class="soundscape-toggle"><span><b>交互音效</b><small>发送、回复和重要状态的轻提示。</small></span><input type="checkbox" data-sound-effects></label>
      <label class="soundscape-volume"><span>音效音量</span><input type="range" min="0" max="1" step="0.05" data-sound-effects-volume aria-label="音效音量"></label>
      <p class="soundscape-status" data-sound-status role="status" aria-live="polite"></p><button type="button" class="soundscape-silence" data-sound-silence>一键关闭音乐与音效</button><p class="soundscape-note">录音、朗读、先不打扰或离开页面时声音暂停；设置只保存在此设备。</p>
      <div class="soundscape-breath"><div><b>一起呼吸</b><small>可随时暂停或结束，不必勉强跟随节奏。</small></div><p data-breath-status role="status"></p><div class="soundscape-breath-actions"><button type="button" data-breath-start>开始呼吸</button><button type="button" data-breath-mute hidden>引导静音</button><button type="button" data-breath-end hidden>结束</button></div></div>`;
    container.appendChild(panel); panels.add(panel);
    panel.querySelector('[data-sound-music]').onchange = e => {
      setMusicEnabled(e.target.checked);
    };
    panel.querySelector('[data-sound-effects]').onchange = e => { config.effects = e.target.checked; save(); if (!config.effects) sfx.pause(); else play('toggleOn'); render(); };
    panel.querySelector('[data-sound-theme]').onchange = e => { config.theme = e.target.value; save(); error = ''; clearPreview(); if (guiding) { render(); } else if (config.music) { unlocked = true; startMusic(choose()); } else { halt(); render(); } };
    panel.querySelector('[data-sound-preview]').onclick = () => {
      unlocked = true; error = '';
      if (guiding) { error = '请先结束呼吸引导，再试听其他音乐。'; render(); return; }
      if (preview) { clearPreview(); if (config.music) startMusic(choose()); else { halt(); render(); } return; }
      preview = true; startMusic(choose());
      previewTimer = setTimeout(() => { clearPreview(); if (config.music) startMusic(choose()); else { halt(); render(); } }, 10000);
    };
    panel.querySelector('[data-sound-silence]').onclick = () => {
      freezeGuide(); config.music = false; config.effects = false; guideMuted = true; clearPreview(); halt(); resumeGuideClock(); sfx.pause(); save(); render();
    };
    panel.querySelector('[data-breath-start]').onclick = () => {
      unlocked = true; error = ''; clearPreview();
      if (!guiding) { guiding = true; guidePaused = false; guideMuted = false; guideElapsed = 0; guideClockRunning = false; startMusic('breath'); }
      else if (!guidePaused) { freezeGuide(); guidePaused = true; halt(); }
      else { guidePaused = false; resumeGuideClock(); if (!guideMuted) startMusic(); }
      clearInterval(guideTimer); if (!guidePaused) guideTimer = setInterval(render, 250); render();
    };
    panel.querySelector('[data-breath-mute]').onclick = () => {
      freezeGuide(); guideMuted = !guideMuted;
      if (guideMuted) { halt(); resumeGuideClock(); }
      else { try { music.currentTime = (guideElapsed % 40000) / 1000; } catch (_) {} if (!guidePaused) startMusic(); }
      render();
    };
    panel.querySelector('[data-breath-end]').onclick = () => {
      guiding = false; guidePaused = false; guideClockRunning = false; clearInterval(guideTimer); guideTimer = null; guideElapsed = 0;
      if (config.music) startMusic(choose()); else { halt(); render(); }
    };
    panel.querySelector('[data-sound-music-volume]').oninput = e => { config.musicVolume = Number(e.target.value); music.volume = config.musicVolume; save(); };
    panel.querySelector('[data-sound-effects-volume]').oninput = e => { config.effectsVolume = Number(e.target.value); sfx.volume = config.effectsVolume; save(); };
    render();
  }
  document.addEventListener('visibilitychange', refreshAudio);
  function init() {
    mount(document.getElementById('sound-settings'));
    let wasQuiet = quiet();
    new MutationObserver(() => { const now = quiet(); if (now !== wasQuiet) { wasQuiet = now; refreshAudio(); } }).observe(document.body, {attributes:true, attributeFilter:['hidden'], childList:true, subtree:true});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  // Persisted opt-in may resume only after a fresh user gesture, per browser policy.
  document.addEventListener('click', event => { if (event.target.closest?.('[data-tool=music]')) return; if (!unlocked && config.music) { unlocked = true; startMusic(current || choose()); } }, true);
  global.NianxiangSound = {mount, play, isBlocked: blocked, setMusicEnabled, toggleMusic() { return setMusicEnabled(!publicState().active); }, getState:publicState, pauseForOtherMusic() {
    freezeGuide(); config.music = false; guideMuted = true; clearPreview(); halt(); resumeGuideClock(); save(); render();
  }, setRecording(value) { recording = !!value; refreshAudio(); }, setVoiceActive(value) { voice = !!value; refreshAudio(); }};
})(window);
