(() => {
  const ALLOWED_EMOTIONS = new Set(['warm','playful','serious','concerned','calm','curious']);
  const ALLOWED_FORMATS = new Set(['plain','markdown']);
  const cleanText = value => typeof value === 'string' ? value.trim() : '';
  const detectFormat = text => /```|^\s{0,3}#{1,6}\s|\|[^\n]+\|\s*\n\s*\|?\s*:?-{3,}/m.test(text) ? 'markdown' : 'plain';
  function tryEnvelope(value) {
    if (value && typeof value === 'object' && !Array.isArray(value)) return value;
    if (typeof value !== 'string') return null;
    const source = value.trim();
    const candidates = [source];
    const fenced = source.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (fenced) candidates.push(fenced[1].trim());
    const start = source.indexOf('{');
    const end = source.lastIndexOf('}');
    if (start >= 0 && end > start) candidates.push(source.slice(start, end + 1));
    for (const candidate of candidates) {
      try {
        const parsed = JSON.parse(candidate);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
      } catch (_) { /* ordinary prose or malformed protocol; use safe fallback */ }
    }
    return null;
  }
  function parse(value) {
    const raw = typeof value === 'string' ? value.trim() : '';
    const envelope = tryEnvelope(value);
    if (envelope && Array.isArray(envelope.messages) && envelope.messages.length && envelope.messages.every(item => typeof item === 'string' && item.trim())) {
      const messages = envelope.messages.map(item => item.trim());
      const format = ALLOWED_FORMATS.has(envelope.format) ? envelope.format : detectFormat(messages.join('\n'));
      const emotion = ALLOWED_EMOTIONS.has(envelope.emotion) ? envelope.emotion : null;
      return {messages, emotion, format};
    }
    const fallback = raw || (value == null ? '' : String(value)).trim();
    return {messages:[fallback || '暂时没有可显示的回复。'], emotion:null, format:detectFormat(fallback)};
  }
  const api = Object.freeze({parse});
  globalThis.XinjiResponseParser = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
