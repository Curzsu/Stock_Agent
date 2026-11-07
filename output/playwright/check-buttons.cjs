const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
const before = process.argv.includes('--before');
const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); return res.end(JSON.stringify({ ok: false, history: [] })); }
  const file = path.join(root, 'frontend', req.url === '/' ? 'index.html' : req.url.replace('/static/', ''));
  if (!fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', ({ '.css': 'text/css', '.js': 'application/javascript', '.html': 'text/html', '.woff': 'font/woff' })[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(r => server.listen(8766, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Users/Lukesu/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe' });
  const errors = [], measurements = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8766', { waitUntil: 'networkidle' });
    await page.locator('#introOverlay').evaluate(el => el.remove());
    await page.waitForTimeout(4200);
    await page.evaluate(() => { if (window.__lenis) window.__lenis.stop(); });
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      const search = page.locator('#analyzeBtn');
      await page.locator('#stockInput').focus();
      await search.hover();
      await page.waitForTimeout(500);
      const hover = await search.evaluate(el => {
        const style = getComputedStyle(el), layer = getComputedStyle(el, '::before');
        const rect = el.getBoundingClientRect(), wrapper = el.parentElement.getBoundingClientRect();
        return { radius: style.borderRadius, overlayRadius: layer.borderRadius, overlayContent: layer.content, overlayDisplay: layer.display, background: style.backgroundColor, color: style.color, withinSearch: rect.left >= wrapper.left && rect.right <= wrapper.right && rect.top >= wrapper.top && rect.bottom <= wrapper.bottom };
      });
      if ([1440,390].includes(width)) await page.locator('.search-wrapper').screenshot({ path: path.join(__dirname, `search-${before ? 'before' : 'after'}-${width}.png`) });
      if (!before) {
        assert(hover.overlayDisplay === 'none' || hover.overlayContent === 'none', 'hover paints one button surface without a second rounded layer');
        assert(hover.withinSearch, 'search button stays within the input');
        assert.equal(hover.background, 'rgb(201, 162, 39)');
        assert.equal(hover.color, 'rgb(10, 10, 10)');
      }
      const cta = page.locator('#ctaAnalyzeBtn');
      await cta.scrollIntoViewIfNeeded();
      await page.waitForTimeout(800);
      await page.mouse.move(0, 0);
      await page.evaluate(() => document.activeElement.blur());
      await page.waitForTimeout(400);
      const normal = await cta.evaluate(el => ({ shadow: getComputedStyle(el).boxShadow, transform: getComputedStyle(el).transform, height: el.getBoundingClientRect().height }));
      await cta.hover();
      await page.waitForTimeout(400);
      const active = await cta.evaluate(el => ({ shadow: getComputedStyle(el).boxShadow, transform: getComputedStyle(el).transform }));
      if (!before) {
        assert.equal(normal.shadow, 'none');
        assert.equal(active.shadow, 'none');
        assert.equal(active.transform, 'none');
        assert(normal.height >= 44, 'CTA keeps a comfortable click target');
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      }
      await page.mouse.move(0, 0);
      await page.waitForTimeout(400);
      if ([1440,390].includes(width)) await page.locator('#ctaSection').screenshot({ path: path.join(__dirname, `cta-${before ? 'before' : 'after'}-${width}.png`) });
      await cta.click();
      await page.waitForTimeout(1300);
      assert(await page.locator('#stockInput').evaluate(el => el === document.activeElement), 'CTA returns focus to the stock input');
      measurements.push({ width, hover, normal, active });
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ before, errors, measurements }));
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
