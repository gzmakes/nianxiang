/* Local sticker markers are identifiers, never HTML. The same renderer is
   used on desktop and mobile and works even when a pack has been removed. */
(function (root) {
  "use strict";

  function render(text, items, escape) {
    const source = String(text || "");
    const list = Array.isArray(items) ? items : [];
    const safe = typeof escape === "function" ? escape : (value) => String(value).replace(/[&<>"']/g, ch => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[ch]));
    const pattern = /\[表情[:：]\s*([^\]\r\n]{1,240}?)\s*\]/g;
    let output = "", cursor = 0, match;
    while ((match = pattern.exec(source))) {
      output += safe(source.slice(cursor, match.index));
      const key = match[1].trim();
      // ID is unambiguous; labels and tags preserve older saved conversations.
      const item = list.find(entry => entry && entry.id === key) ||
        list.find(entry => entry && entry.label === key) ||
        list.find(entry => entry && Array.isArray(entry.tags) && entry.tags.includes(key));
      if (item && typeof item.url === "string" && /^\/(?:plugin-memes\/[^?#]+|static\/stickers\/(?:happy|comfort|curious|cheer)\.svg)$/.test(item.url)) {
        output += `<img class="chat-meme" src="${safe(item.url)}" alt="${safe(item.label || key)}" loading="lazy">`;
      } else {
        output += safe(match[0]);
      }
      cursor = pattern.lastIndex;
    }
    return output + safe(source.slice(cursor));
  }

  root.XinjiMeme = { render };
  if (typeof module !== "undefined" && module.exports) module.exports = root.XinjiMeme;
})(typeof window !== "undefined" ? window : globalThis);
