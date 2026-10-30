const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { inspectFile, readTextFile } = require("../bridge");

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "xinji-bridge-"));

test("读取允许的 markdown", () => {
  const p = path.join(dir, "a.md");
  fs.writeFileSync(p, "# 你好\n这是资料");
  const out = readTextFile(p);
  assert.equal(out.ok, true);
  assert.equal(out.name, "a.md");
  assert.match(out.text, /你好/);
});

test("拒绝非白名单扩展名", () => {
  const p = path.join(dir, "a.exe");
  fs.writeFileSync(p, "x");
  const out = inspectFile(p);
  assert.equal(out.ok, false);
  assert.match(out.reason, /不支持/);
});

test("拒绝超过 1MB 的文件", () => {
  const p = path.join(dir, "big.txt");
  fs.writeFileSync(p, "x".repeat(1024 * 1024 + 1));
  const out = inspectFile(p);
  assert.equal(out.ok, false);
  assert.match(out.reason, /1MB/);
});

test("不存在文件返回可读原因", () => {
  const out = inspectFile(path.join(dir, "missing.md"));
  assert.equal(out.ok, false);
});
