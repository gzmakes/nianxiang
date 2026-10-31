/* 背景音乐（2026-10-31，产品要求）：对话栏「播放音乐」按钮开关的一段轻环境音。
   用 WebAudio 现场合成（几组慢慢换和弦的柔和长音 + 偶尔一粒五声音阶的高音），不带任何音频文件，不联网，不记录。
   只在用户点了按钮后才建 AudioContext（浏览器要求手势）；关掉标签页即停。 */
window.XinjiAmbientMusic = (() => {
  const CHORDS = [
    [130.81, 196.00, 246.94, 329.63], // C  G  B  E
    [110.00, 164.81, 220.00, 261.63], // A  E  A  C
    [87.31, 130.81, 174.61, 261.63],  // F  C  F  C
    [98.00, 146.83, 196.00, 293.66],  // G  D  G  D
  ];
  const SPARKLE = [523.25, 587.33, 659.25, 783.99, 880.00, 1046.5];
  const CHORD_SECONDS = 14, MASTER = 0.07;
  let ctx = null, master = null, voices = [], chordTimer = null, sparkleTimer = null, chordIndex = 0, playing = false;

  function ensure() {
    if (ctx) return ctx;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    ctx = new Ctx();
    master = ctx.createGain(); master.gain.value = 0;
    const filter = ctx.createBiquadFilter(); filter.type = 'lowpass'; filter.frequency.value = 1400; filter.Q.value = 0.4;
    // 一点点回声，让长音更像在房间里
    const delay = ctx.createDelay(1.5); delay.delayTime.value = 0.42;
    const feedback = ctx.createGain(); feedback.gain.value = 0.28;
    const wet = ctx.createGain(); wet.gain.value = 0.35;
    master.connect(filter); filter.connect(ctx.destination);
    filter.connect(delay); delay.connect(feedback); feedback.connect(delay); delay.connect(wet); wet.connect(ctx.destination);
    return ctx;
  }

  function voice(freq, when) {
    const gain = ctx.createGain(); gain.gain.setValueAtTime(0, when);
    const oscs = [0, 2.2, -1.8].map(detune => { const osc = ctx.createOscillator(); osc.type = 'triangle'; osc.frequency.value = freq; osc.detune.value = detune; osc.connect(gain); osc.start(when); return osc; });
    // 很慢的起伏，像呼吸
    const lfo = ctx.createOscillator(); lfo.type = 'sine'; lfo.frequency.value = 0.08 + Math.random() * 0.06;
    const lfoGain = ctx.createGain(); lfoGain.gain.value = 0.08;
    lfo.connect(lfoGain); lfoGain.connect(gain.gain); lfo.start(when);
    gain.connect(master);
    gain.gain.linearRampToValueAtTime(0.22, when + 4);
    return { gain, stop(at) { gain.gain.cancelScheduledValues(at); gain.gain.setValueAtTime(gain.gain.value, at); gain.gain.linearRampToValueAtTime(0, at + 5); for (const osc of oscs) osc.stop(at + 5.2); lfo.stop(at + 5.2); } };
  }

  function playChord() {
    const now = ctx.currentTime;
    for (const old of voices) old.stop(now);
    voices = CHORDS[chordIndex % CHORDS.length].map(freq => voice(freq, now));
    chordIndex += 1;
  }

  function sparkle() {
    if (!playing) return;
    const now = ctx.currentTime, freq = SPARKLE[Math.floor(Math.random() * SPARKLE.length)];
    const osc = ctx.createOscillator(); osc.type = 'sine'; osc.frequency.value = freq;
    const gain = ctx.createGain(); gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.12, now + 0.03); gain.gain.exponentialRampToValueAtTime(0.0005, now + 3.5);
    osc.connect(gain); gain.connect(master); osc.start(now); osc.stop(now + 3.6);
    sparkleTimer = setTimeout(sparkle, 3500 + Math.random() * 5000);
  }

  async function start() {
    if (playing) return true;
    if (!ensure()) return false;
    try { if (ctx.state === 'suspended') await ctx.resume(); } catch (_) { return false; }
    playing = true;
    master.gain.cancelScheduledValues(ctx.currentTime); master.gain.setValueAtTime(master.gain.value, ctx.currentTime);
    master.gain.linearRampToValueAtTime(MASTER, ctx.currentTime + 2.5);
    playChord();
    chordTimer = setInterval(playChord, CHORD_SECONDS * 1000);
    sparkleTimer = setTimeout(sparkle, 2500);
    document.dispatchEvent(new CustomEvent('xinji-ambient-music', { detail: { playing: true } }));
    return true;
  }

  function stop() {
    if (!playing) return;
    playing = false;
    clearInterval(chordTimer); clearTimeout(sparkleTimer); chordTimer = sparkleTimer = null;
    const now = ctx.currentTime;
    master.gain.cancelScheduledValues(now); master.gain.setValueAtTime(master.gain.value, now);
    master.gain.linearRampToValueAtTime(0, now + 1.8);
    for (const old of voices) old.stop(now + 1.5);
    voices = [];
    document.dispatchEvent(new CustomEvent('xinji-ambient-music', { detail: { playing: false } }));
  }

  window.addEventListener('pagehide', stop);
  return { start, stop, toggle: () => (playing ? (stop(), Promise.resolve(false)) : start()), playing: () => playing };
})();
