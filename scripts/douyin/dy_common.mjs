// Shared helpers for Douyin scripts: Chromium discovery, anti-detect launch,
// link -> aweme_id normalization, and login-state checks.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
// playwright is imported DYNAMICALLY inside findChrome()/launchContext() so that
// pure-HTTP helpers (normalizeInput) and `--help` work without the dependency.

export const UA_DESKTOP =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

export const DEFAULT_PROFILE =
  process.env.DOUYIN_PROFILE || path.join(os.homedir(), '.workbuddy', 'douyin-profile');

/**
 * Locate a usable Chromium/Chrome binary.
 * Priority: DOUYIN_CHROME env > /tmp/chrome_path.txt > common macOS/Linux/Win paths
 * > Playwright's own bundled executable. Returns a path or undefined (use bundled).
 */
export async function findChrome() {
  if (process.env.DOUYIN_CHROME && fs.existsSync(process.env.DOUYIN_CHROME)) {
    return process.env.DOUYIN_CHROME;
  }
  const hintFile = '/tmp/chrome_path.txt';
  if (fs.existsSync(hintFile)) {
    const p = fs.readFileSync(hintFile, 'utf8').trim();
    if (p && fs.existsSync(p)) return p;
  }
  const candidates = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ];
  for (const c of candidates) if (fs.existsSync(c)) return c;
  try {
    const { chromium } = await import('playwright');
    return chromium.executablePath();
  } catch { return undefined; }
}

/**
 * Launch a persistent (login-state) or ephemeral browser context with basic
 * anti-automation patches. Caller decides headless and profileDir.
 */
export async function launchContext({ headless = true, profileDir = null } = {}) {
  const { chromium } = await import('playwright');
  const executablePath = await findChrome();
  console.error('[chrome]', executablePath || 'playwright-bundled');
  const args = ['--no-sandbox', '--disable-blink-features=AutomationControlled'];
  let context;
  if (profileDir) {
    fs.mkdirSync(profileDir, { recursive: true });
    context = await chromium.launchPersistentContext(profileDir, {
      headless, executablePath, args,
      viewport: { width: 1920, height: 1080 },
      locale: 'zh-CN',
      ignoreHTTPSErrors: true,
    });
  } else {
    const browser = await chromium.launch({
      headless, executablePath, args,
    });
    context = await browser.newContext({
      userAgent: UA_DESKTOP,
      viewport: { width: 1920, height: 1080 },
      locale: 'zh-CN',
      ignoreHTTPSErrors: true,
    });
    context.__ownBrowser = browser; // remember to close
  }
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
  });
  return context;
}

export async function closeContext(context) {
  try {
    if (context.__ownBrowser) await context.__ownBrowser.close();
    else await context.close();
  } catch {}
}

/**
 * Normalize any input (share link, v.douyin.com short link, video URL, raw id)
 * into { awemeId, videoUrl, input }.
 */
export function normalizeInput(input) {
  input = String(input || '').trim();
  const m = /(\d{15,19})/.exec(input);
  const awemeId = m ? m[1] : '';
  let videoUrl = input;
  if (awemeId && !/^https?:\/\//.test(input)) {
    videoUrl = `https://www.douyin.com/video/${awemeId}`;
  }
  return { awemeId, videoUrl, input };
}

/** Return the sessionid cookie from a context, or null. */
export async function getSessionCookie(context) {
  try {
    const cookies = await context.cookies();
    return cookies.find(c => c.name === 'sessionid' || c.name === 'sessionid_ss') || null;
  } catch { return null; }
}

/** Check whether a profile dir has a sessionid in its Cookies sqlite DB. */
export function profileHasLogin(profileDir) {
  // Heuristic: profile dir exists and has a Cookies DB with nonzero size.
  // Real verification is done via getSessionCookie() after launch.
  const db = path.join(profileDir, 'Default', 'Cookies');
  return fs.existsSync(db) && fs.statSync(db).size > 0;
}
