/**
 * 念响公共模型代理：让 clone 下来的客户端无需自带 key 也能跑真模型。
 *
 * 设计取舍（务必知情）：
 * - key 只存在本函数的环境变量里，客户端拿不到；
 * - 但这个代理本身是公开的，任何人知道地址就能花你的资源点 → 因此有
 *   按 IP 限流 + 全局每日上限 + 强制收窄的请求形状。
 * - 计数器在实例内存里，冷启动会重置，只是"防手滑"，不是防攻击。
 */
const https = require('https');
const { URL } = require('url');

const AI_BASE = (process.env.AI_BASE || '').replace(/\/+$/, '');
const AI_KEY = process.env.AI_KEY || '';
const PUBLIC_MODEL = process.env.PUBLIC_MODEL || 'deepseek-v4-flash';

const PER_IP_LIMIT = 20;          // requests
const PER_IP_WINDOW_MS = 10 * 60 * 1000;
const DAILY_LIMIT = 500;          // requests per instance-day (demo budget)
const MAX_MESSAGES = 16;
const MAX_CHARS = 12000;
const MAX_TOKENS = 800;

const buckets = new Map();
let dayKey = '';
let dayCount = 0;

function rateLimited(ip, now) {
  const day = new Date(now).toISOString().slice(0, 10);
  if (day !== dayKey) { dayKey = day; dayCount = 0; }
  dayCount += 1;
  if (dayCount > DAILY_LIMIT) return 'daily';

  const entry = buckets.get(ip);
  if (!entry || now > entry.resetAt) {
    buckets.set(ip, { count: 1, resetAt: now + PER_IP_WINDOW_MS });
    if (buckets.size > 5000) {
      for (const [k, v] of buckets) if (now > v.resetAt) buckets.delete(k);
    }
    return null;
  }
  entry.count += 1;
  return entry.count > PER_IP_LIMIT ? 'ip' : null;
}

function reply(statusCode, payload) {
  return {
    statusCode,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'x-nx-proxy': '1',
    },
    body: JSON.stringify(payload),
  };
}

function post(url, body, headers) {
  return new Promise((resolve) => {
    const target = new URL(url);
    const data = Buffer.from(JSON.stringify(body));
    const req = https.request({
      hostname: target.hostname,
      port: 443,
      path: target.pathname + target.search,
      method: 'POST',
      headers: Object.assign({
        'content-type': 'application/json',
        'content-length': data.length,
      }, headers),
      timeout: 25000,
    }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({
        status: res.statusCode || 502,
        body: Buffer.concat(chunks).toString('utf8'),
      }));
    });
    req.on('timeout', () => req.destroy(new Error('upstream timeout')));
    req.on('error', (err) => resolve({ status: 502, body: JSON.stringify({ error: String(err.message || err) }) }));
    req.write(data);
    req.end();
  });
}

function sanitize(payload) {
  const messages = Array.isArray(payload.messages) ? payload.messages.slice(-MAX_MESSAGES) : null;
  if (!messages || !messages.length) return { error: 'messages required' };
  let chars = 0;
  for (const m of messages) {
    if (!m || typeof m.content !== 'string' || !m.content) return { error: 'invalid message' };
    if (!['system', 'user', 'assistant'].includes(m.role)) return { error: 'invalid role' };
    chars += m.content.length;
  }
  if (chars > MAX_CHARS) return { error: 'prompt too long' };
  const maxTokens = Math.min(Number(payload.max_tokens) || 600, MAX_TOKENS);
  return {
    body: {
      model: PUBLIC_MODEL,
      messages,
      temperature: typeof payload.temperature === 'number' ? Math.min(Math.max(payload.temperature, 0), 1.5) : 0.6,
      max_tokens: maxTokens,
      thinking: { type: 'disabled' },
    },
  };
}

exports.main = async (event) => {
  const method = (event.httpMethod || event.requestContext?.httpMethod || 'POST').toUpperCase();
  const rawPath = event.path || event.requestContext?.path || '/';
  const ip = (event.headers?.['x-forwarded-for'] || event.headers?.['X-Forwarded-For'] || 'unknown')
    .split(',')[0].trim();

  if (method === 'GET') {
    return reply(200, { ok: true, model: PUBLIC_MODEL, note: 'POST /v1/chat/completions' });
  }
  if (method !== 'POST') return reply(405, { error: 'method not allowed' });
  if (!/chat\/completions\/?$/.test(rawPath)) return reply(404, { error: 'not found' });

  const blocked = rateLimited(ip, Date.now());
  if (blocked) {
    return reply(429, {
      error: blocked === 'daily' ? 'daily quota exhausted for this proxy' : 'too many requests, slow down',
    });
  }

  let payload;
  try {
    payload = typeof event.body === 'string'
      ? JSON.parse(event.isBase64Encoded ? Buffer.from(event.body, 'base64').toString('utf8') : event.body)
      : (event.body || {});
  } catch {
    return reply(400, { error: 'invalid json' });
  }

  const clean = sanitize(payload);
  if (clean.error) return reply(400, { error: clean.error });

  const upstream = await post(`${AI_BASE}/chat/completions`, clean.body, {
    authorization: `Bearer ${AI_KEY}`,
  });
  const out = {
    statusCode: upstream.status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'x-nx-proxy': '1',
    },
    body: upstream.body,
  };
  return out;
};
