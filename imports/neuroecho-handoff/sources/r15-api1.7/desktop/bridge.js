// 本地文件桥的纯逻辑（可单测，不依赖 Electron）
const fs = require("node:fs");
const path = require("node:path");

const TEXT_EXT = new Set([".md", ".markdown", ".txt", ".json"]);
const MAX_BYTES = 1024 * 1024;

function inspectFile(absPath) {
  const ext = path.extname(absPath).toLowerCase();
  if (!TEXT_EXT.has(ext)) return { ok: false, reason: `不支持的类型 ${ext || "(无扩展名)"}` };
  let st;
  try {
    st = fs.statSync(absPath);
  } catch (e) {
    return { ok: false, reason: "文件不存在或无权限" };
  }
  if (!st.isFile()) return { ok: false, reason: "不是文件" };
  if (st.size > MAX_BYTES) return { ok: false, reason: "文件超过 1MB 上限" };
  return { ok: true, size: st.size, ext };
}

function readTextFile(absPath) {
  const info = inspectFile(absPath);
  if (!info.ok) return info;
  try {
    const text = fs.readFileSync(absPath, "utf8");
    return { ok: true, name: path.basename(absPath), size: info.size, text: text.slice(0, 20000) };
  } catch (e) {
    return { ok: false, reason: "读取失败" };
  }
}

module.exports = { TEXT_EXT, MAX_BYTES, inspectFile, readTextFile };
