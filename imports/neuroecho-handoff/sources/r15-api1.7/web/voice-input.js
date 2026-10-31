/* User initiated MediaRecorder upload. Recognition never submits the chat. */
(function (global) {
  'use strict';
  function attach({button, input, api, toast, stopButton}) {
    let recorder = null, stream = null, timer = null, started = 0, busy = false;
    const original = () => String(input?.value || '').trim();
    const set = (label, active = false) => { if (button) { button.textContent = label; button.classList.toggle('listening', active); button.disabled = busy && !active; } };
    const cleanup = () => { if (timer) global.clearTimeout(timer); timer = null; stream?.getTracks?.().forEach(track => track.stop()); stream = null; recorder = null; };
    const fail = (message) => { cleanup(); busy = false; set('语音'); toast?.(message); };
    async function transcribe(blob, draft) {
      busy = true; set('正在识别…');
      try {
        const response = await fetch('/api/voice/transcribe', {method:'POST', headers:{'Content-Type': blob.type || 'application/octet-stream'}, body: blob});
        if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || '语音识别失败，可改用文字'); }
        const result = await response.json(); const text = String(result.text || '').trim();
        if (!text) throw new Error('没有识别到可用文字，请再说一次。');
        input.value = draft ? `${draft}\n${text}` : text;
        input.dispatchEvent(new Event('input', {bubbles:true}));
        busy = false; set('语音');
      } catch (error) { fail(error.message || '语音识别失败，可改用文字'); }
    }
    async function start() {
      if (busy) return;
      if (!global.MediaRecorder || !global.navigator?.mediaDevices?.getUserMedia) { fail('当前浏览器不支持麦克风录音。'); return; }
      try {
        stream = await navigator.mediaDevices.getUserMedia({audio:true});
        const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
        const type = types.find(value => MediaRecorder.isTypeSupported?.(value)) || '';
        const chunks = []; recorder = new MediaRecorder(stream, type ? {mimeType:type} : undefined); started = Date.now();
        recorder.ondataavailable = event => { if (event.data?.size) chunks.push(event.data); };
        recorder.onerror = () => fail('麦克风录音失败，可改用文字');
        recorder.onstop = () => { const blob = new Blob(chunks, {type: recorder?.mimeType || type || 'audio/webm'}); cleanup(); transcribe(blob, original()); };
        recorder.start(); set('停止', true); if (stopButton) stopButton.hidden = false;
        timer = global.setTimeout(() => stop(), 55_000);
      } catch (error) { fail(error?.name === 'NotAllowedError' ? '麦克风权限未开启。语音将发送到腾讯云进行识别；念响本机不长期保存原始录音。' : '无法开始麦克风录音。'); }
    }
    function stop() { if (recorder && recorder.state !== 'inactive') recorder.stop(); }
    button?.addEventListener('click', () => recorder ? stop() : start());
    stopButton?.addEventListener('click', stop);
    global.addEventListener?.('pagehide', cleanup); global.document?.addEventListener?.('visibilitychange', () => { if (global.document.hidden) stop(); });
    return {stop, cleanup};
  }
  global.XinjiVoiceInput = {attach};
})(window);
