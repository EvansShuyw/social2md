// Kuaishou share-page media URL resolver.
// Opens a Kuaishou share link in a headless browser (no login needed) and finds
// mainMvUrls[0].url from the rendered page state or the page's own API responses.
//
// Usage:
//   node resolve_kuaishou.mjs "<SHARE_LINK>" [--out /path/ks_meta.json]
//
// Emits shell-friendly KEY=value lines (MEDIA_URL, TITLE, AUTHOR, DURATION_MS,
// VERDICT, JSON_OUT) so the common core workflow can consume it unchanged.
//
// NOTE: no login cookie needed for Kuaishou share pages (unlike Douyin). The
// sibling production skill verified mainMvUrls[0].url is curl-downloadable.
import fs from 'node:fs';

const argv = process.argv.slice(2);
const input = argv.find(a => !a.startsWith('--'));
if (!input) {
  console.error('usage: node resolve_kuaishou.mjs "<share link>" [--out FILE]');
  process.exit(1);
}
function opt(name, def) {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : def;
}
const OUT = opt('--out', '/tmp/ks_meta.json');

const UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) ' +
  'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1';

function findChromeSync() {
  if (process.env.DOUYIN_CHROME && fs.existsSync(process.env.DOUYIN_CHROME)) return process.env.DOUYIN_CHROME;
  const hint = '/tmp/chrome_path.txt';
  if (fs.existsSync(hint)) {
    const p = fs.readFileSync(hint, 'utf8').trim();
    if (p && fs.existsSync(p)) return p;
  }
  for (const c of [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome', '/usr/bin/chromium',
  ]) if (fs.existsSync(c)) return c;
  return undefined;
}

// Recursively find the first media URL + nearby metadata in an arbitrary JSON value.
function dig(obj) {
  let mediaUrl = '';
  let title = '', author = '', duration = 0;
  const seen = new Set();
  function walk(node, depth) {
    if (!node || depth > 30 || seen.has(node)) return;
    if (typeof node === 'object') seen.add(node);
    if (Array.isArray(node)) {
      // mainMvUrls: [ { url, width, height }, ... ] — prefer first http(s) url
      for (const it of node) {
        if (typeof it === 'string' && /^https?:\/\//.test(it) && !mediaUrl && /mp4|\.video|kuaishou|chenzhongtech/.test(it)) {
          mediaUrl = it;
        }
        walk(it, depth + 1);
      }
      return;
    }
    if (typeof node !== 'object') return;
    for (const [k, v] of Object.entries(node)) {
      const kl = k.toLowerCase();
      if ((kl.includes('mainmvurl') || kl === 'playurl' || kl === 'videoplayurl' || kl === 'url') &&
          typeof v === 'string' && /^https?:\/\//.test(v) && !mediaUrl) {
        mediaUrl = v;
      }
      if (Array.isArray(v) && (kl.includes('mainmvurl') || kl.includes('playurl'))) {
        const first = v.find(x => typeof x === 'string' && /^https?:/.test(x)) ||
                      v.find(x => x && typeof x.url === 'string')?.url;
        if (first && !mediaUrl) mediaUrl = first;
      }
      if ((k === 'caption' || k === 'description' || k === 'title') && typeof v === 'string' && !title) title = v.slice(0, 200);
      if ((k === 'nickname' || k === 'userName' || k === 'user_name') && typeof v === 'string' && !author) author = v;
      if ((k === 'duration' || k === 'photoDuration') && typeof v === 'number' && !duration) duration = v;
      walk(v, depth + 1);
    }
  }
  walk(obj, 0);
  return { mediaUrl, title, author, duration };
}

let chromium;
try { ({ chromium } = await import('playwright')); }
catch (e) { console.error('[FATAL] playwright not installed:', e.message); process.exit(1); }

const executablePath = findChromeSync();
console.error('[chrome]', executablePath || 'playwright-bundled');
const browser = await chromium.launch({
  headless: true, executablePath,
  args: ['--no-sandbox', '--disable-blink-features=AutomationControlled'],
});
const context = await browser.newContext({
  userAgent: UA, viewport: { width: 390, height: 844 },
  isMobile: true, locale: 'zh-CN', ignoreHTTPSErrors: true,
});
const page = await context.newPage();

// CDP capture of page's own API responses (graphql / photo / vision).
let cdp = null;
const apiBodies = [];
try {
  cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  const interested = new Set();
  cdp.on('Network.requestWillBeSent', e => {
    if (/graphql|photo|vision|short-video|fw\/photo/i.test(e.request.url)) interested.add(e.requestId);
  });
  cdp.on('Network.loadingFinished', async e => {
    if (!interested.has(e.requestId)) return;
    try {
      const { body } = await cdp.send('Network.getResponseBody', { requestId: e.requestId });
      if (body && body.length > 50) apiBodies.push(body);
    } catch {}
  });
} catch { cdp = null; }

console.error('[nav]', input);
await page.goto(input, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(e => console.error('[nav err]', e.message));
const finalUrl = page.url();
await page.waitForTimeout(6000);
try { await page.evaluate(() => window.scrollBy(0, 600)); await page.waitForTimeout(2000); } catch {}

// Strategy 1: rendered page globals. Serialize inside the page (avoids passing
// circular objects across the bridge), then parse + search in Node.
let found = { mediaUrl: '', title: '', author: '', duration: 0 };
try {
  const blobs = await page.evaluate(() => {
    const out = [];
    const keys = Object.keys(window).filter(k => /apollo|router|state|data|photo|__/i.test(k));
    for (const k of keys) {
      try {
        const s = JSON.stringify(window[k]);
        if (s && s.length > 50 && /mainMvUrls|playUrl|photoUrl|mp4/i.test(s)) out.push(s);
      } catch {}
    }
    return out;
  });
  for (const s of blobs) {
    try {
      const d = dig(JSON.parse(s));
      if (d.mediaUrl) { found = d; break; }
    } catch {}
  }
} catch {}

// Strategy 2: CDP API bodies.
if (!found.mediaUrl) {
  for (const body of apiBodies) {
    try {
      const d = dig(JSON.parse(body));
      if (d.mediaUrl) { found = d; break; }
    } catch {}
  }
}

// Strategy 3: <video> src.
if (!found.mediaUrl) {
  try {
    found.mediaUrl = await page.evaluate(() => {
      const v = document.querySelector('video');
      return v ? (v.currentSrc || v.src || '') : '';
    });
  } catch {}
}

// Metadata from visible DOM text — Kuaishou share pages render the caption as
// "<author>：<title>#topic..." and the author after an "@" line. Verified on a
// live link (2026-11-16): line "高鑫屈：今日黄金，趋势解读#金价#黄金#高鑫屈".
let domLines = [];
try {
  domLines = await page.evaluate(() => document.body.innerText.split('\n').map(s => s.trim()).filter(Boolean));
} catch {}
if (!found.title) {
  // Prefer the longest line containing a #topic (that's the post caption).
  const caption = domLines
    .filter(l => l.includes('#') && l.length > 8 && !/打开快手|邀请你|热榜/.test(l))
    .sort((a, b) => b.length - a.length)[0];
  if (caption) {
    found.title = caption.slice(0, 200);
    // Author = text before the first full-width colon, if present.
    const m = /^([^：:#]{2,20})[：:]/.exec(caption);
    if (m && !found.author) found.author = m[1].trim();
  }
}
if (!found.author) {
  // Fallback: the line right after a standalone "@" line.
  const at = domLines.indexOf('@');
  if (at >= 0 && domLines[at + 1]) found.author = domLines[at + 1].slice(0, 40);
}

const pageTitle = await page.title().catch(() => '');
await browser.close();

const mediaUrl = found.mediaUrl || '';
const verdict = mediaUrl ? 'OK' : 'EMPTY';
const result = {
  ok: !!mediaUrl,
  verdict,
  verdict_reason: mediaUrl ? '' : '未找到 mainMvUrls/playUrl。分享页可能需登录、地区限制或结构变化；检查 apiHits 并更新提取规则。',
  input, final_url: finalUrl,
  MEDIA_URL: mediaUrl,
  TITLE: found.title || pageTitle,
  AUTHOR: found.author || '',
  DURATION_MS: found.duration || 0,
  photo_id: (/[?&]photoId=([^&]+)/.exec(finalUrl) || /\/photo\/([^?&/]+)/.exec(finalUrl))?.[1] || '',
  api_hit_count: apiBodies.length,
  checked_at: new Date().toISOString(),
};
fs.writeFileSync(OUT, JSON.stringify(result, null, 2));

console.log(`OK=${result.ok ? 'true' : 'false'}`);
console.log(`VERDICT=${verdict}`);
console.log(`MEDIA_URL=${mediaUrl}`);
console.log(`TITLE=${result.TITLE}`);
console.log(`AUTHOR=${result.AUTHOR}`);
console.log(`DURATION_MS=${result.DURATION_MS}`);
console.log(`JSON_OUT=${OUT}`);
if (!mediaUrl) console.error('[EMPTY] 检查输出 JSON 的 api_hit_count 与页面结构；参见 references/kuaishou.md。');
