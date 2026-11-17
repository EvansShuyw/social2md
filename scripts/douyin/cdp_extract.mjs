// CORE: extract a Douyin video's full metadata + signed play URL by intercepting
// the browser's OWN detail API response via CDP — we never reverse-engineer the
// signature; the logged-in browser signs its own requests for us.
//
// Requires a login profile created by login.mjs. Without login, Douyin returns
// HTTP 200 with an empty body (see references/notes.md).
//
// Usage:
//   node cdp_extract.mjs "<share link / video url / id>" [options]
//   node cdp_extract.mjs "7708743309875751526" --profile ~/.workbuddy/douyin-profile \
//       --out /path/video_meta.json
//
// Options:
//   --profile DIR   login profile dir (default ~/.workbuddy/douyin-profile)
//   --out FILE      write full JSON here (default /tmp/dy_result.json)
//   --wait MS       ms to wait for API responses (default 15000)
//   --headless      force headless (default headless; login is the only visible step)
import fs from 'node:fs';
import { normalizeInput, launchContext, closeContext, getSessionCookie, DEFAULT_PROFILE } from './dy_common.mjs';

const argv = process.argv.slice(2);
const input = argv.find(a => !a.startsWith('--'));
if (!input) {
  console.error('usage: node cdp_extract.mjs "<link or id>" [--profile DIR] [--out FILE]');
  process.exit(1);
}
function opt(name, def) {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : def;
}
const PROFILE = opt('--profile', DEFAULT_PROFILE);
const OUT = opt('--out', '/tmp/dy_result.json');
const WAIT = parseInt(opt('--wait', '15000'), 10);

const { awemeId, videoUrl } = normalizeInput(input);
console.error('[input]', input, '->', videoUrl, 'aweme_id=', awemeId);

const context = await launchContext({ headless: true, profileDir: PROFILE });

// --- Login-state gate -------------------------------------------------------
const sid = await getSessionCookie(context);
if (!sid) {
  console.error('[NO LOGIN] 该 profile 没有 sessionid cookie。请先运行:');
  console.error(`  node login.mjs --profile ${PROFILE}`);
  await closeContext(context);
  // Still emit a structured failure so callers can detect it.
  const fail = { ok: false, reason: 'NO_LOGIN', aweme_id: awemeId, input };
  fs.writeFileSync(OUT, JSON.stringify(fail, null, 2));
  console.log(`OK=false\nREASON=NO_LOGIN\nAWEME_ID=${awemeId}\nJSON_OUT=${OUT}`);
  process.exit(2);
}
console.error('[login] ok, sessionid present');

const page = context.pages()[0] || await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send('Network.enable');

// Correct CDP capture pattern (learned the hard way):
//   requestWillBeSent -> record requestId -> url
//   responseReceived  -> record status ONLY (getResponseBody here => "No data found")
//   loadingFinished   -> THEN call Network.getResponseBody
const pending = new Map();
const hits = [];
const INTEREST = /\/aweme\/v1\/web\/aweme\/(detail|post)\/|aweme\/v2\/aweme\/detail|aweme\/v1\/aweme\/detail/;

cdp.on('Network.requestWillBeSent', e => {
  if (INTEREST.test(e.request.url)) pending.set(e.requestId, { url: e.request.url });
});
cdp.on('Network.responseReceived', e => {
  const p = pending.get(e.requestId);
  if (p) { p.status = e.response.status; p.mime = e.response.mimeType; }
});
cdp.on('Network.loadingFinished', async e => {
  const p = pending.get(e.requestId);
  if (!p) return;
  try {
    const { body } = await cdp.send('Network.getResponseBody', { requestId: e.requestId });
    p.body = body;
    hits.push(p);
    console.error('[HIT]', p.status, decodeURIComponent(p.url).slice(0, 110), 'len=', body.length);
  } catch (err) {
    console.error('[getBody err]', err.message);
  }
  pending.delete(e.requestId);
});
cdp.on('Network.loadingFailed', e => pending.delete(e.requestId));

console.error('[nav]', videoUrl);
await page.goto(videoUrl, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(e => console.error('[nav err]', e.message));

// Sometimes the detail request only fires after scroll / a bit of dwell.
await page.waitForTimeout(Math.min(WAIT, 6000));
for (const action of [
  () => page.evaluate(() => window.scrollBy(0, 600)),
  () => page.evaluate(() => window.scrollBy(0, -600)),
]) {
  try { await action(); } catch {}
  await page.waitForTimeout(2000);
}
await page.waitForTimeout(Math.max(0, WAIT - 10000));

// Fallback: in-page fetch (browser already executed all signing JS + has cookies).
let fallbackBody = null;
try {
  fallbackBody = await page.evaluate(async (id) => {
    const url = `/aweme/v1/web/aweme/detail/?aweme_id=${id}&device_platform=webapp&aid=6383&channel=channel_pc_web`;
    try { const r = await fetch(url, { credentials: 'include' }); return (await r.text()).slice(0, 200000); }
    catch (e) { return 'FETCH_ERR:' + e; }
  }, awemeId);
  console.error('[fallback detail] len=', String(fallbackBody).length, String(fallbackBody).slice(0, 120));
} catch (e) { console.error('[fallback err]', e.message); }

await closeContext(context);

// --- Parse ------------------------------------------------------------------
// VALIDITY GATE: Douyin can silently return a frozen/empty snapshot when the
// login is expired or risk-controlled — HTTP 200 + plausible-looking JSON, but
// aweme_detail is null and status_code != 0. Never trust a 200 alone.
function parseDetail(body) {
  if (!body || typeof body !== 'string') return null;
  try {
    const j = JSON.parse(body);
    const d = j.aweme_detail || j.aweme_list?.[0] || (j.aweme_id ? j : null);
    if (!d) return null;
    return { detail: d, status_code: j.status_code };
  } catch { return null; }
}
let parsed = null;
for (const h of hits) { parsed = parseDetail(h.body); if (parsed) break; }
if (!parsed) parsed = parseDetail(fallbackBody);
const detail = parsed?.detail || null;
const statusCode = parsed?.status_code;

const result = {
  ok: !!detail,
  input,
  aweme_id: awemeId || (detail && detail.aweme_id) || '',
  hits: hits.map(h => ({ url: h.url, status: h.status, len: (h.body || '').length })),
};
if (detail) {
  const v = detail.video || {};
  const pick = (addr) => addr && {
    url_list: addr.url_list || [],
    width: addr.width, height: addr.height, uri: addr.uri,
  };
  result.detail = {
    aweme_id: detail.aweme_id,
    desc: detail.desc,
    duration_ms: detail.duration,
    create_time: detail.create_time,
    author: detail.author && {
      nickname: detail.author.nickname,
      unique_id: detail.author.unique_id,
      sec_uid: detail.author.sec_uid,
    },
    statistics: detail.statistics,
    play_addr: pick(v.play_addr),
    download_addr: v.download_addr?.url_list || [],
    bitrate_info: v.bitrate_info,
    cover: v.cover?.url_list || [],
    music: detail.music && { title: detail.music.title, author: detail.music.author },
    is_image: !!detail.images,
    images: (detail.images || []).map(img => ({
      url_list: img.url_list || [], width: img.width, height: img.height,
    })),
  };
  // Choose the first playable play_addr URL as the download candidate.
  result.VIDEO_URL = result.detail.play_addr?.url_list?.[0] || '';
  result.TITLE = (detail.desc || '').split('\n')[0].slice(0, 120);
  result.AUTHOR = result.detail.author?.nickname || '';
  result.DURATION_MS = result.detail.duration_ms || 0;
} else {
  result.detail = null;
  result.raw_hits = hits.map(h => (h.body || '').slice(0, 1200));
  result.fallback = String(fallbackBody || '').slice(0, 1200);
}

// --- Validity / freshness verdict ------------------------------------------
// Signed play URL expires in hours; a frozen snapshot is the silent-failure
// mode. We flag it rather than silently producing a digest from stale data.
const nowS = Math.floor(Date.now() / 1000);
const ageHours = detail?.create_time ? (nowS - detail.create_time) / 3600 : null;
let verdict = 'OK';
let verdictReason = '';
if (!detail) {
  verdict = 'EMPTY';
  verdictReason = 'aweme_detail 为空 (status_code=' + statusCode + ')。多为登录态失效/风控，重新 login 或稍后重试。';
} else if (statusCode !== undefined && statusCode !== 0) {
  verdict = 'BAD_STATUS';
  verdictReason = '接口 status_code=' + statusCode + '（正常为 0），数据可能不可信。';
} else if (!result.VIDEO_URL) {
  verdict = 'NO_PLAY_URL';
  verdictReason = '没有 play_addr，可能是图文帖(IS_IMAGE)或无播放权限。';
} else if (ageHours !== null && ageHours > 24 * 365 * 5) {
  verdict = 'STALE';
  verdictReason = 'create_time 过早（' + ageHours.toFixed(0) + ' 小时前），疑似冻结快照。';
}
result.verdict = verdict;
result.verdict_reason = verdictReason;
result.status_code = statusCode ?? null;
result.create_time = detail?.create_time || null;
result.age_hours = ageHours === null ? null : Math.round(ageHours);
result.checked_at = new Date().toISOString();

fs.writeFileSync(OUT, JSON.stringify(result, null, 2));

console.log(`OK=${result.ok ? 'true' : 'false'}`);
console.log(`VERDICT=${result.verdict}`);
console.log(`STATUS_CODE=${result.status_code ?? ''}`);
console.log(`AGE_HOURS=${result.age_hours ?? ''}`);
console.log(`AWEME_ID=${result.aweme_id}`);
console.log(`VIDEO_URL=${result.VIDEO_URL || ''}`);
console.log(`TITLE=${result.TITLE || ''}`);
console.log(`AUTHOR=${result.AUTHOR || ''}`);
console.log(`DURATION_MS=${result.DURATION_MS || 0}`);
console.log(`IS_IMAGE=${result.detail?.is_image ? 'true' : 'false'}`);
console.log(`JSON_OUT=${OUT}`);
if (!result.ok) {
  console.error('[EMPTY] 未截获到 detail。常见原因: 登录态失效(重新 login) / 该视频需更高权限 / 风控拦截。查看 raw_hits 与 notes.md。');
}
