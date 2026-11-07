const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
const records = [
  { company_name: 'qq' + '8'.repeat(100), stock_code: '-', status: 'error' },
  { company_name: '很长的中文公司名称'.repeat(15), stock_code: '6'.repeat(100), status: 'running' },
  { company_name: '中信银行', stock_code: '601998', status: 'completed' },
  { company_name: '<img src=x onerror=alert(1)>" & test', stock_code: '-', status: 'error' },
].map((record, i) => ({ ...record, analysis_date: '2026-11-06', analysis_id: 'preview-' + i }));
const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) {
    res.setHeader('Content-Type', 'application/json');
    return res.end(JSON.stringify({ ok: false, history: records }));
  }
  const file = path.join(root, 'frontend', req.url === '/' ? 'index.html' : req.url.replace('/static/', ''));
  if (!fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', ({ '.css': 'text/css', '.js': 'application/javascript', '.html': 'text/html', '.woff': 'font/woff' })[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(8766, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: 'C:/Users/Lukesu/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe' });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, route => route.abort());
    await page.goto('http://127.0.0.1:8766', { waitUntil: 'networkidle' });
    await page.locator('#introOverlay').evaluate(el => el.remove());
    await page.locator('.history-card').first().waitFor();
    for (const width of [1440, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.locator('#historySection').scrollIntoViewIfNeeded();
      const boxes = await page.locator('.history-card').evaluateAll(cards => cards.map(card => {
        const rect = selector => card.querySelector(selector).getBoundingClientRect().toJSON();
        const title = card.querySelector('.history-card-title');
        return {
          card: card.getBoundingClientRect().toJSON(),
          header: rect('.history-card-header'), title: rect('.history-card-title'),
          code: rect('.history-card-code'), status: rect('.history-card-date'),
          overflow: title.scrollWidth > title.clientWidth,
          ellipsis: getComputedStyle(title).textOverflow,
          name: title.textContent, tooltip: title.getAttribute('title'),
        };
      }));
      console.log(JSON.stringify({ width, first: boxes[0] }));
      for (const box of boxes) {
        assert(box.status.right <= box.header.right + 1, `${width}: status stays inside card`);
        assert(box.title.right + 4 <= box.status.left, `${width}: title leaves space for status`);
        assert(box.code.right <= box.status.left, `${width}: code stays inside its column`);
        assert.equal(box.tooltip, box.name, `${width}: tooltip preserves full name safely`);
      }
      const longName = boxes.find(box => box.name.startsWith('qq'));
      assert(longName.overflow, `${width}: long name is constrained`);
      assert.equal(longName.ellipsis, 'ellipsis');
      assert(longName.code.width < 60, `${width}: missing code badge stays compact`);
      assert.equal(await page.locator('.history-card img').count(), 0);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.locator('#historySection').screenshot({ path: path.join(__dirname, `history-overflow-fixed-${width}.png`) });
    }
    assert.deepEqual(errors, []);
    console.log('PASS: long English/Chinese names, long codes, all statuses, safe tooltips at 1440/768/390/320px');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
