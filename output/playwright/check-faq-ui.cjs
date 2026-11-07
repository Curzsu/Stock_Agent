const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); return res.end(JSON.stringify({ ok: false, history: [] })); }
  const file = path.join(root, 'frontend', req.url === '/' ? 'index.html' : req.url.replace('/static/', ''));
  if (!fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', ({ '.css': 'text/css', '.js': 'application/javascript', '.html': 'text/html', '.woff': 'font/woff' })[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(r => server.listen(8765, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Users/Lukesu/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe' });
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
    await page.locator('#introOverlay').evaluate(el => el.remove());
    await page.waitForTimeout(4200);
    await page.evaluate(() => { if (window.__lenis) window.__lenis.stop(); });
    const section = page.locator('#faqSection');
    const items = section.locator('details');
    assert.equal(await items.count(), 4);
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      await section.scrollIntoViewIfNeeded();
      await page.waitForTimeout(1000);
      const layout = await page.evaluate(() => {
        const faq = document.querySelector('#faqSection');
        const history = document.querySelector('#historySection');
        const intro = faq.querySelector('.faq-header').getBoundingClientRect();
        const list = faq.querySelector('.faq-list').getBoundingClientRect();
        const market = document.querySelector('#marketSection .market-header').getBoundingClientRect();
        const headingStyle = selector => {
          const style = getComputedStyle(document.querySelector(selector));
          return Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'color'].map(key => [key, style[key]]));
        };
        return { intro: intro.toJSON(), list: list.toJSON(), market: market.toJSON(), marketHeading: headingStyle('.market-section .market-title'), faqHeading: headingStyle('.faq-section .faq-title'), faqBg: getComputedStyle(faq).backgroundColor, historyBg: getComputedStyle(history).backgroundColor, gap: history.getBoundingClientRect().top - faq.getBoundingClientRect().bottom, overflow: document.documentElement.scrollWidth > innerWidth };
      });
      assert(!layout.overflow);
      assert.equal(layout.faqBg, layout.historyBg);
      assert(Math.abs(layout.gap) < 1);
      assert(layout.list.y >= layout.intro.y + layout.intro.height, 'FAQ heading sits above questions');
      for (const block of [layout.intro, layout.list, layout.market]) assert(Math.abs(block.x + block.width / 2 - width / 2) < 1, 'section content is centered');
      assert.deepEqual(layout.faqHeading, layout.marketHeading, 'FAQ and index headings have identical typography');
      await page.evaluate(() => document.activeElement.blur());
      if ([1440,390].includes(width)) await section.screenshot({ path: path.join(__dirname, `faq-redesign-${width}.png`) });
      const question = items.nth(0).locator('summary');
      await question.click();
      assert(await items.nth(0).evaluate(el => el.open));
      assert(await items.nth(0).locator('.faq-answer').isVisible());
      assert(await items.nth(0).locator('.faq-answer').evaluate(el => el.scrollWidth <= el.clientWidth));
      if ([1440,390].includes(width)) await section.screenshot({ path: path.join(__dirname, `faq-redesign-open-${width}.png`) });
      await question.focus();
      await page.keyboard.press('Enter');
      assert.equal(await items.nth(0).evaluate(el => el.open), false, 'keyboard toggles the native disclosure');
      assert.equal(await items.nth(1).evaluate(el => el.open), false, 'other questions keep their state');
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('#marketSection').scrollIntoViewIfNeeded();
    await page.waitForTimeout(1000);
    await page.locator('#marketSection').screenshot({ path: path.join(__dirname, 'market-centered-1440.png') });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ errors, checkedWidths: [1440,1024,768,390,320], verified: ['centered headings above content', 'identical heading typography', 'native click and keyboard disclosure', 'answer wrapping', 'unchanged FAQ/history background continuity', 'all four questions retained'] }));
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); server.close(); process.exitCode = 1; });
