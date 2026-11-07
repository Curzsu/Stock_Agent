const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
let records = [];
const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); return res.end(JSON.stringify({ ok: false, history: records })); }
  const name = req.url === '/' ? 'index.html' : req.url.replace('/static/', '');
  const file = path.join(root, 'frontend', name);
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
    records = [{ company_name: '中信银行', stock_code: '601998', status: 'error', analysis_date: '2026-11-05', analysis_id: 'preview-only' }];
    await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
    await page.locator('#introOverlay').evaluate(el => el.remove());
    await page.waitForTimeout(4200);
    await page.evaluate(() => { if (window.__lenis) window.__lenis.stop(); });
    const section = page.locator('#historySection');
    const beforeScroll = await page.evaluate(() => {
      const history = document.querySelector('#historySection');
      history.classList.remove('visible');
      return history.getBoundingClientRect().top - document.querySelector('#faqSection').getBoundingClientRect().bottom;
    });
    assert(Math.abs(beforeScroll) <= 1, 'History background must touch FAQ before its entrance animation');
    for (const width of [1440, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      await section.scrollIntoViewIfNeeded();
      for (const delay of [0, 80, 250, 500]) {
        await page.waitForTimeout(delay);
        const gap = await page.evaluate(() => document.querySelector('#historySection').getBoundingClientRect().top - document.querySelector('#faqSection').getBoundingClientRect().bottom);
        assert(Math.abs(gap) <= 1, 'No gap during scroll entrance');
      }
      await page.waitForTimeout(1300);
      const info = await page.evaluate(() => {
        const history = document.querySelector('#historySection');
        const sections = Array.from(document.querySelectorAll('.landing-section'));
        const index = sections.indexOf(history);
        const header = history.querySelector('.section-header').getBoundingClientRect();
        const buttons = ['historyPrev', 'historyNext'].map(id => document.getElementById(id).getBoundingClientRect().toJSON());
        const grid = history.querySelector('#historyGrid').getBoundingClientRect();
        return { before: sections[index - 1].id, after: sections[index + 1].id, bg: getComputedStyle(history).backgroundColor, faqBg: getComputedStyle(document.querySelector('#faqSection')).backgroundColor, height: history.getBoundingClientRect().height, buttons, header: header.toJSON(), grid: grid.toJSON(), overflow: document.documentElement.scrollWidth > innerWidth };
      });
      assert.equal(info.before, 'faqSection');
      assert.equal(info.after, 'ctaSection');
      assert.equal(info.bg, info.faqBg, 'history background exactly matches FAQ');
      assert(info.height < 340, 'history section stays compact');
      assert(!info.overflow);
      assert(info.buttons.every(button => button.y >= info.header.y && button.y + button.height <= info.grid.y));
      assert(await page.locator('#historyPrev').isDisabled());
      assert(await page.locator('#historyNext').isDisabled());
      if ([1440, 390].includes(width)) await section.screenshot({ path: path.join(__dirname, `history-one-${width}.png`) });
    }
    records = Array.from({ length: 8 }, (_, i) => ({ company_name: `示例报告 ${i + 1}`, stock_code: '600519', status: 'completed', analysis_date: '2026-11-05', analysis_id: `preview-${i}` }));
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.evaluate(() => loadHistory());
      await page.waitForTimeout(500);
      assert(await page.locator('#historyNext').isEnabled());
      await page.locator('#historyNext').click();
      await page.waitForTimeout(150);
      assert(await page.locator('#historyGrid').evaluate(el => el.scrollLeft > 0));
      assert(await page.locator('#historyPrev').isEnabled());
      for (let i = 0; i < 10 && await page.locator('#historyNext').isEnabled(); i++) { await page.locator('#historyNext').click(); await page.waitForTimeout(100); }
      assert(await page.locator('#historyNext').isDisabled());
      await page.locator('#historyPrev').click();
      await page.waitForTimeout(150);
      assert(await page.locator('#historyNext').isEnabled());
      await section.screenshot({ path: path.join(__dirname, `history-many-${width}.png`) });
    }
    records = [];
    await page.evaluate(() => loadHistory());
    await page.waitForTimeout(100);
    assert(await page.locator('#historyNext').isDisabled());
    assert(await page.locator('#historyPrev').isDisabled());
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ errors, checkedWidths: [1440, 768, 390, 320], cases: ['single report', 'multiple reports', 'empty history', 'forward/backward navigation', 'disabled boundaries', 'FAQ-history-CTA order'] }));
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); server.close(); process.exitCode = 1; });
