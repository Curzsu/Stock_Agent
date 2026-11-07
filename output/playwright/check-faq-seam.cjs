const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); return res.end(JSON.stringify({ ok: false, history: [] })); }
  let file;
  if (req.url === '/before') {
    res.setHeader('Content-Type', 'text/html');
    return res.end(fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8').replace('/static/workbench.css', '/before.css'));
  }
  if (req.url === '/before.css') file = path.join(root, 'output/faq-seam-before.css');
  else file = path.join(root, 'frontend', req.url === '/' ? 'index.html' : req.url.replace('/static/', ''));
  if (!fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', ({ '.css': 'text/css', '.js': 'application/javascript', '.html': 'text/html', '.woff': 'font/woff' })[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(r => server.listen(8765, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Users/Lukesu/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe' });
  try {
    const results = [];
    for (const [width, height] of [[1440, 1000], [390, 900]]) {
      const bounds = [];
      for (const [name, url] of [['before', '/before'], ['after', '/']]) {
        const page = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' });
        await page.goto('http://127.0.0.1:8765' + url, { waitUntil: 'networkidle' });
        await page.locator('#introOverlay').evaluate(el => el.remove());
        await page.evaluate(() => { if (window.__lenis) window.__lenis.stop(); });
        await page.waitForTimeout(4000);
        await page.evaluate(() => document.fonts.ready);
        const info = await page.evaluate(() => {
          const hero = document.querySelector('#howSection').getBoundingClientRect();
          const market = document.querySelector('#faqSection').getBoundingClientRect();
          return { bottom: hero.bottom + scrollY, marketTop: market.top + scrollY, heroHeight: hero.height, overflow: document.documentElement.scrollWidth > innerWidth };
        });
        await page.evaluate((boundary) => window.scrollTo({ top: boundary - innerHeight / 2, behavior: 'instant' }), info.bottom);
        await page.waitForTimeout(1100);
        bounds.push(info);
        assert(!info.overflow);
        const top = Math.round(info.bottom) - 90;
        await page.screenshot({ path: path.join(__dirname, `faq-seam-${name}-${width}.png`), fullPage: true, clip: { x: 0, y: top, width, height: 180 }, animations: 'disabled' });
        if (name === 'after' && width === 1440) await page.screenshot({ path: path.join(__dirname, 'faq-seam-fixed.png'), animations: 'disabled' });
        await page.close();
      }
      assert.deepEqual(bounds[0], bounds[1], 'Section geometry remains unchanged');
      results.push({ width, ...bounds[1] });
    }
    console.log(JSON.stringify(results));
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); server.close(); process.exitCode = 1; });
