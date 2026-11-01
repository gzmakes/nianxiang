/* Small, local-only view of memories. It never changes the underlying records. */
(() => {
  'use strict';
  const explicitSources = new Set(['对话原话 · 用户选存', '对话原话 · 用户纠正', '用户手动添加']);
  const valid = (m, sources) => m && m.status !== 'deleted' && m.source !== '示例资料' && m.source_label !== '示例资料'
    && !/撤回后来源待核对|来源待核对/.test([m.source, m.source_label].filter(Boolean).join(' '))
    && (!m.source_attachment_id || sources === null || sources.some(s => s.id === m.source_attachment_id && !s.stale && s.connector_id !== 'sample' && s.label !== '示例资料'));
  function known(m, sources) {
    return valid(m, sources) && m.kind === 'fact' && (m.status === 'confirmed' || (m.status === 'auto' && explicitSources.has(m.source)));
  }
  function activities(sources) {
    const seen = new Set();
    return (sources || []).filter(source => source && !source.stale && source.connector_id === 'apple_reminders')
      .flatMap(source => Array.isArray(source.items) ? source.items : [])
      .filter(item => item && (item.type === '提醒' || item.type === 'reminder') && typeof item.title === 'string')
      .sort((a,b) => String(b.modified_at || '').localeCompare(String(a.modified_at || '')))
      .map(item => item.title.trim().replace(/\s+/g, ' '))
      .filter(text => text && !/[?？<>]/.test(text) && !/^(?:无标题|新建提醒|提醒事项|提醒|未命名)$/.test(text))
      .filter(text => {const key = text.toLowerCase(); if (seen.has(key)) return false; seen.add(key); return true;})
      .slice(0, 3).map(text => {
        const chars = Array.from(text); const clipped = chars.length > 50 ? chars.slice(0, 50).join('') + '…' : text;
        return `你曾有提醒「${clipped}」。`;
      });
  }
  function summary(records, sources) {
    const seen = new Set();
    const personal = /^(?:我|你)(?:是|在|有|想|希望|喜欢|不喜欢|需要|正在|习惯|倾向|偏好|平时|目前|最近|从事|负责|做|用|会|更)/;
    const personalWithoutSubject = /^(?:是|喜欢|不喜欢|希望|需要|正在|习惯|倾向|偏好|平时|目前|最近|从事|负责)/;
    const facts = records.filter(m => known(m, sources)).slice().sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
      .map(m => ({text:String(m.text || '').trim().replace(/\s+/g, ' '), source:m.source}))
      .filter(({text, source}) => text && !/[?？]|(?:可能|推测|似乎|猜测)/.test(text)
        && (personal.test(text) || (explicitSources.has(source) && personalWithoutSubject.test(text))))
      .filter(({text}) => { const key = text.replace(/[\s，。！？,.!?]/g, '').toLowerCase(); if (seen.has(key)) return false; seen.add(key); return true; })
      .slice(0, 5).map(({text}) => {
        const chars = Array.from(text); const clipped = chars.length > 100 ? chars.slice(0, 100).join('') + '…' : text;
        return /^我/.test(clipped) ? '你' + clipped.slice(1) : /^你/.test(clipped) ? clipped : '你' + clipped;
      });
    return facts.concat(activities(sources)).slice(0, 5);
  }
  function review(records, sources) {
    const seen = new Set();
    return records.filter(m => valid(m, sources) && m.status === 'candidate' && m.kind === 'fact')
      .filter(m => { const text = String(m.text || '').trim();
        if (!text || /[?？]|^(洞察|推测|问题|本次展示|此次展示)/.test(text) || !/(?:我|我的|本人|用户|你)(?:是|在|有|的|想|希望|喜欢|不喜欢|需要|正在|习惯|倾向|偏好|平时|目前|最近|负责|从事|做|用|会|更)/.test(text)) return false;
        const key = text.replace(/[\s，。！？,.!?]/g, '').toLowerCase(); if (seen.has(key)) return false; seen.add(key); return true; });
  }
  window.XinjiMemoryInsights = {known, summary, review, activities};
})();
