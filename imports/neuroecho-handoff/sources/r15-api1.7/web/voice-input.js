/* Browser-local speech recognition. No audio is recorded or uploaded. */
(function (global) {
  'use strict';
  function attach({button, input, toast}) {
    const Recognition = global.SpeechRecognition || global.webkitSpeechRecognition;
    let recognition = null, listening = false, draft = '';
    const set = (label, active = false) => { if (button) { button.textContent = label; button.classList.toggle('listening', active); button.setAttribute('aria-pressed', active ? 'true' : 'false'); } };
    const fail = message => { listening = false; recognition = null; set('语音'); toast?.(message); };
    if (!Recognition) {
      set('文字');
      button?.setAttribute('title', '当前浏览器不支持本地语音识别，请直接输入文字。');
      button?.addEventListener('click', () => toast?.('当前浏览器不支持本地语音识别，请直接输入文字。'));
      return {stop() {}};
    }
    const stop = () => { if (recognition && listening) recognition.stop(); };
    button?.addEventListener('click', () => {
      if (listening) return stop();
      try {
        recognition = new Recognition(); recognition.lang = 'zh-CN'; recognition.interimResults = true; recognition.continuous = false;
        recognition.onstart = () => { listening = true; draft = String(input?.value || '').trim(); set('停止', true); };
        recognition.onresult = event => { let text = ''; for (let i = event.resultIndex; i < event.results.length; i++) text += event.results[i][0].transcript; const value = text.trim(); if (input && value) { input.value = draft ? `${draft}\n${value}` : value; input.dispatchEvent(new Event('input', {bubbles:true})); } };
        recognition.onerror = event => { if (event.error === 'not-allowed' || event.error === 'service-not-allowed') fail('浏览器未允许麦克风或本地语音识别。'); else if (event.error !== 'aborted') fail('本地语音识别失败，请重试或改用文字。'); };
        recognition.onend = () => { listening = false; recognition = null; set('语音'); };
        recognition.start();
      } catch (_) { fail('无法启动本地语音识别，请重试或改用文字。'); }
    });
    global.addEventListener?.('pagehide', stop);
    return {stop};
  }
  global.XinjiVoiceInput = {attach};
})(window);
