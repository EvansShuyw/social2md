// Resolve a Douyin share / short link into aweme_id via HTTP 302 redirects.
// This step needs NO browser and NO login — v.douyin.com short links 302-redirect
// to https://www.douyin.com/video/<aweme_id> (or /note/<id> for image notes).
// Usage: node resolve_link.mjs "https://v.douyin.com/xxxxx/"
// Self-contained: no playwright / no dy_common import — pure Node fetch only.
function normalizeId(s) {
  const m = /(\d{15,19})/.exec(String(s || '').trim());
  return m ? m[1] : '';
}

const input = process.argv[2];
if (!input) {
  console.error('usage: node resolve_link.mjs "<douyin share link / short link / video url / id>"');
  process.exit(1);
}

const MOBILE_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) ' +
  'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1';

async function resolve(link) {
  const headers = { 'User-Agent': MOBILE_UA };
  let url = link;
  const seen = new Set();
  for (let i = 0; i < 12; i++) {
    if (seen.has(url)) break;
    seen.add(url);
    let resp;
    try {
      resp = await fetch(url, { headers, redirect: 'manual' });
    } catch (e) {
      console.error('[fetch err]', e.message);
      break;
    }
    const loc = resp.headers.get('location');
    console.error(`[hop ${i}] ${resp.status} -> ${loc || '(no location)'}`);
    if (loc) {
      // resolve relative redirects
      url = new URL(loc, url).toString();
      continue;
    }
    break;
  }
  return url;
}

const finalUrl = await resolve(input);
const awemeId = normalizeId(finalUrl) || normalizeId(input);
const kind = /\/(note|slides)\//.test(finalUrl) ? 'note' : 'video';

console.log(`INPUT=${input}`);
console.log(`FINAL_URL=${finalUrl}`);
console.log(`AWEME_ID=${awemeId || ''}`);
console.log(`KIND=${kind}`);
console.log(`VIDEO_URL=https://www.douyin.com/video/${awemeId}`);
if (!awemeId) {
  console.error('[WARN] Could not extract aweme_id from the link. The link may be expired or require login to resolve.');
}
