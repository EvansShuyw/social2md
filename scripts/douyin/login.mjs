// One-time interactive login: open a VISIBLE Chromium, let the user scan the
// Douyin QR code, then gracefully close so cookies persist to the profile dir.
// The saved profile is reused by cdp_extract.mjs for all future extraction.
//
// Usage:
//   node login.mjs                         # uses DEFAULT_PROFILE
//   node login.mjs --profile /path/to/dir  # custom profile
//   node login.mjs --timeout 600           # seconds to wait (default 600)
//
// WHY LOGIN IS REQUIRED: Douyin's detail API is behind ArgusSecurity (a_bogus,
// msToken, s_v_web_id, uifid, x-secsdk-web-signature). Anonymous HTTP requests
// return HTTP 200 with an EMPTY body; reverse-engineered signatures fail with
// "Uifid Not Found / Validate Error". Logging in once and letting the real
// browser sign its own requests is the only reliable path. See references/notes.md.
import fs from 'node:fs';
import { execSync } from 'node:child_process';
import { launchContext, closeContext, getSessionCookie, DEFAULT_PROFILE } from './dy_common.mjs';

const args = process.argv.slice(2);
function arg(name, def) {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}
const PROFILE = arg('--profile', DEFAULT_PROFILE);
const TIMEOUT_S = parseInt(arg('--timeout', '600'), 10);

fs.mkdirSync(PROFILE, { recursive: true });
console.log('[profile]', PROFILE);
console.log('[open] 在弹出的浏览器里用抖音 App 扫码登录…');

const context = await launchContext({ headless: false, profileDir: PROFILE });

// macOS: force the browser window to the foreground so the QR code isn't hidden
// behind other apps (a real problem we hit — user couldn't see the QR window).
try { execSync("osascript -e 'tell application \"Chromium\" to activate'", { stdio: 'ignore' }); } catch {}
try { execSync("osascript -e 'tell application \"Google Chrome\" to activate'", { stdio: 'ignore' }); } catch {}
console.log('[front] 已尝试把浏览器窗口置顶');

const page = context.pages()[0] || await context.newPage();
await page.goto('https://www.douyin.com/', { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});

const deadline = Date.now() + TIMEOUT_S * 1000;
let loggedIn = false;
let tick = 0;
while (Date.now() < deadline) {
  const sid = await getSessionCookie(context);
  if (sid) {
    console.log('[SUCCESS] 检测到登录 cookie:', sid.name, 'value head:', String(sid.value).slice(0, 12));
    loggedIn = true;
    break;
  }
  // Refresh the QR periodically — Douyin QR codes expire in ~2-3 min.
  if (tick > 0 && tick % 50 === 0) {
    console.log('[refresh] 刷新二维码…');
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    try { execSync("osascript -e 'tell application \"Chromium\" to activate'", { stdio: 'ignore' }); } catch {}
  }
  if (tick % 10 === 0) console.log(`[waiting] ${tick * 2}s … 请扫码`);
  tick++;
  await page.waitForTimeout(2000);
}

// Graceful close is CRITICAL — a hard kill drops the sessionid cookie.
await closeContext(context);

if (loggedIn) {
  console.log('[DONE] 登录态已保存到', PROFILE);
  console.log('接下来对任意视频运行: node cdp_extract.mjs "<link>" --profile', PROFILE);
} else {
  console.error('[TIMEOUT] 未检测到登录，请重试: node login.mjs --timeout 600');
  process.exit(1);
}
