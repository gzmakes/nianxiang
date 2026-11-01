/* Independent, short-lived pet utterances; no conversation data is sent. */
(() => {
  'use strict';
  let pending = null;
  const generate = () => {
    if (pending) return pending;
    pending = fetch('/api/pet-whisper', {method:'POST', credentials:'same-origin', cache:'no-store'})
      .then(response => response.ok ? response.json() : null)
      .then(data => data?.available && typeof data.text === 'string' && data.text.trim() ? data.text.trim() : null)
      .catch(() => null)
      .finally(() => { pending = null; });
    return pending;
  };
  window.NianxiangPetWhisper = {generate};
})();
