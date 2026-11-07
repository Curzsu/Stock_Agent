const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
const server = http.createServer((req, res) => {
  if (req.url === '/v2-reference') {
    res.setHeader('Content-Type', 'text/html');
    return res.end(fs.readFileSync(path.join(root, 'output/v2-index.html'), 'utf8').replace('/static/workbench.css', '/v2-reference.css'));
  }
  if (req.url === '/v2-reference.css') {
    res.setHeader('Content-Type', 'text/css');
    return res.end(fs.readFileSync(path.join(root, 'output/v2-workbench.css')));
  }
  if (req.url.startsWith('/api/')) {
    res.setHeader('Content-Type', 'application/json');
    return res.end(JSON.stringify({ ok: false, history: [], analyses: [], configured: false }));
  }
  const name = req.url === '/' ? 'index.html' : req.url.replace('/static/', '');
  const file = path.join(root, 'frontend', name);
  if (!fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  const types = { '.css': 'text/css', '.js': 'application/javascript', '.html': 'text/html', '.svg': 'image/svg+xml', '.woff': 'font/woff' };
  res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(r => server.listen(8765, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Users/Lukesu/AppData/Local/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    // The preview never submits a model request. Market samples are local fixtures only.
    await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
    const original = await browser.newPage({ viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce' });
    await original.goto('http://127.0.0.1:8765/v2-reference', { waitUntil: 'networkidle' });
    // Authorized transition between the two unchanged original section colors.
    await original.addStyleTag({ content: '.how-section { background: linear-gradient(to bottom, var(--warm-bg) calc(100% - 160px), var(--cream) 100%); }' });
    const readPalette = async (target) => target.evaluate(() => {
      document.querySelectorAll('.intro-dot').forEach(el => el.classList.add('active'));
      const card = document.createElement('article');
      card.className = 'history-card';
      document.querySelector('#historyGrid').append(card);
      const selectors = ['body', '.intro-overlay', '.intro-content', '.intro-logo', '.intro-line', '.intro-tagline', '.intro-dot.active', '.hero-section', '.hero-bg', '.hero-bg::before', '.hero-bg::after', '.glass-blob-1', '.logo-mark', '.logo-text', '.tagline', '.hero-title', '.title-line.accent', '.hero-subtitle', '.search-wrapper', '.search-input', '.search-btn', '.search-btn::before', '.hint-tag', '.market-section', '.market-title', '.market-sub', '.market-card', '.history-section', '.history-section::before', '.history-section::after', '.history-card', '.history-card::before', '.how-section', '.how-step', '.how-title', '.faq-section', '.faq-item', '.cta-section', '.cta-title', '.cta-sub', '.cta-btn', '.config-modal', '.config-modal-title', '.config-input', '.config-save-btn', '.config-cancel-btn'];
      const palette = {};
      for (const selector of selectors) {
        const [query, pseudo] = selector.split('::');
        const el = document.querySelector(query);
        if (!el) continue;
        const style = getComputedStyle(el, pseudo ? '::' + pseudo : null);
        for (const property of ['color', 'backgroundColor', 'backgroundImage']) palette[selector + ':' + property] = style[property];
        palette[selector + ':shadowColors'] = JSON.stringify(style.boxShadow.match(/rgba?\([^)]*\)/g) || []);
      }
      card.remove();
      return palette;
    });
    const expectedPalette = await readPalette(original);
    // User-requested history section shares the FAQ's original cream color.
    expectedPalette['.history-section:backgroundColor'] = expectedPalette['.faq-section:backgroundColor'];
    expectedPalette['.history-section:backgroundImage'] = 'none';
    // FAQ surface now belongs to the shared list, not each disclosure row.
    expectedPalette['.faq-item:backgroundColor'] = 'rgba(0, 0, 0, 0)';
    expectedPalette['.faq-item:shadowColors'] = '[]';
    // The authorized seam fix uses the next section's original color as a
    // continuous backing surface; all original gradient colors stay intact.
    expectedPalette['.hero-section:backgroundColor'] = expectedPalette['.market-section:backgroundColor'];
    const actualPalette = await readPalette(page);
    const paletteDiff = Object.entries(expectedPalette).filter(([key, expected]) => actualPalette[key] !== expected).map(([key, expected]) => ({ key, expected, actual: actualPalette[key] }));
    fs.writeFileSync(path.join(__dirname, 'v2-palette-audit.json'), JSON.stringify({ checkedProperties: Object.keys(expectedPalette).length, differences: paletteDiff }, null, 2));
    console.log('v2 palette audit', JSON.stringify(paletteDiff));
    assert.deepEqual(paletteDiff, [], 'Landing and loading colors must exactly match v2.0');
    const readWorkbenchPalette = async (target) => target.evaluate(() => {
      document.querySelectorAll('.landing-section').forEach(el => el.classList.add('hide-landing'));
      document.querySelector('#analysisSection').classList.add('active');
      const result = {};
      for (const state of ['waiting', 'running', 'completed', 'failed']) {
        document.querySelectorAll('[data-agent]').forEach(card => {
          card.dataset.status = state;
          card.classList.toggle('active', state === 'running');
          card.classList.toggle('complete', state === 'completed');
        });
        for (const selector of ['.workbench-section', '.workbench-back', '.workbench-eyebrow', '.workbench-heading h1', '.workbench-heading h1 span', '.workbench-heading p', '.workbench-time', '.workbench-status', '.workspace-intro h2', '.workspace-caption', '[data-agent="fundamental"]', '[data-agent="summary"]', '.agent-number', '.agent-status', '.agent-card-title h3', '.agent-card-title p', '.agent-summary', '.market-overview', '#marketTradeDate', '.market-quote strong', '.market-quote span', '.market-periods button', '.workbench-market-chart', '.market-legend', '.market-metrics', '.market-metrics div', '.market-metrics dt', '.market-metrics dd', '.market-footnote']) {
          const el = document.querySelector(selector);
          if (!el) continue;
          const style = getComputedStyle(el);
          for (const property of ['color', 'backgroundColor', 'backgroundImage']) result[state + ':' + selector + ':' + property] = style[property];
        }
      }
      document.querySelectorAll('[data-agent]').forEach(card => { card.dataset.status = 'waiting'; card.classList.remove('active', 'complete'); });
      document.querySelectorAll('.landing-section').forEach(el => el.classList.remove('hide-landing'));
      document.querySelector('#analysisSection').classList.remove('active');
      return result;
    });
    const expectedWorkbench = await readWorkbenchPalette(original);
    const actualWorkbench = await readWorkbenchPalette(page);
    const workbenchDiff = Object.entries(expectedWorkbench).filter(([key, expected]) => actualWorkbench[key] !== expected).map(([key, expected]) => ({ key, expected, actual: actualWorkbench[key] }));
    fs.writeFileSync(path.join(__dirname, 'v2-workbench-palette-audit.json'), JSON.stringify({ checkedProperties: Object.keys(expectedWorkbench).length, differences: workbenchDiff }, null, 2));
    console.log('v2 workbench palette audit', JSON.stringify(workbenchDiff));
    assert.deepEqual(workbenchDiff, [], 'Workbench palette must match v2.0 in every agent lifecycle state');
    await original.close();
    await page.locator('#introOverlay').evaluate(el => el.remove());
    await page.waitForTimeout(4200);
    await page.evaluate(() => document.fonts.ready);
    assert(await page.evaluate(() => document.fonts.check('20px "FINEX Round"', '综合研判')));
    await page.screenshot({ path: path.join(__dirname, 'home-desktop.png') });
    await page.evaluate(() => {
      document.querySelectorAll('.landing-section').forEach(el => el.classList.add('hide-landing'));
      document.querySelector('#analysisSection').classList.add('active');
      workbench.reset('中信银行');
      workbench.updateStatus({ status: 'running', progress: { fundamental: 'completed', technical: 'completed', value: 'failed', news: 'running', summary: 'waiting' }, agent_details: {
        fundamental: { status: 'completed', summary: '盈利能力保持平稳，持续关注资产质量与现金流。', execution_time_ms: 42000 },
        technical: { status: 'completed', summary: '价格处于近期震荡区间，关注成交量与关键支撑。', execution_time_ms: 38000 },
        value: { status: 'failed', error: '行情服务暂时繁忙，请稍后重试。', execution_time_ms: 16000 },
        news: { status: 'running' }, summary: { status: 'waiting' }
      }});
      const candles = Array.from({ length: 90 }, (_, i) => {
        const close = 8 + i / 85 + Math.sin(i / 7) * .2;
        return { time: 1782864000 + i * 86400, open: close - Math.sin(i) * .08, high: close + .12, low: close - .1, close, volume: 30000000 + i * 100000, ma5: close - .05, ma20: close - .13 };
      });
      workbench.renderMarket({ ok: true, code: 'sh.601998', latest_trade_date: '2026-11-05', candles, quote: { close: 9.07, pct_change: .55, pe_ttm: 6.96, pb_mrq: .67, turnover: .11, volume: 45630794 } });
      window.scrollTo(0, 0);
    });
    assert.equal(await page.locator('#workbenchRunningState > .market-overview').count(), 1);
    assert.equal(await page.locator('#analysisWorkbench svg').count(), 0);
    const checkDesktopLayout = async (width) => {
      await page.setViewportSize({ width, height: 1100 });
      const market = await page.locator('.market-overview').boundingBox();
      const summary = await page.locator('[data-agent="summary"]').boundingBox();
      const analysts = await page.locator('#agentGrid').boundingBox();
      const news = await page.locator('[data-agent="news"]').boundingBox();
      assert(summary.x >= analysts.x + analysts.width, 'summary sits to the right of the analysts');
      assert(Math.abs(summary.y - analysts.y) <= 1, 'research cards align at the top');
      assert(Math.abs(summary.y + summary.height - news.y - news.height) <= 1, 'summary and the bottom analysts align');
      assert(market.y >= summary.y + summary.height, 'market is below both research columns');
      assert(Math.abs(market.x) <= 1 && Math.abs(market.width - width) <= 1, `edge-to-edge market at ${width}`);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
    };
    for (const width of [1920, 1440, 1280, 1024]) await checkDesktopLayout(width);
    await checkDesktopLayout(1440);
    await page.screenshot({ path: path.join(__dirname, 'workbench-desktop.png'), fullPage: true });
    await page.screenshot({ path: path.join(__dirname, 'workbench-detail.png'), clip: { x: 0, y: 0, width: 1440, height: 1000 } });
    await page.locator('[data-frequency="w"]').click();
    assert.equal(await page.locator('[data-frequency="w"]').getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('[data-frequency="d"]').getAttribute('aria-pressed'), 'false');
    for (const width of [900, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
      const sidebar = await page.locator('[data-agent="summary"]').boundingBox();
      const workspace = await page.locator('.agent-workspace').boundingBox();
      const market = await page.locator('.market-overview').boundingBox();
      assert(sidebar.y >= workspace.y + workspace.height, 'mobile summary follows the analysts');
      assert(market.y >= sidebar.y + sidebar.height, 'mobile market remains at the bottom');
      assert(Math.abs(market.x) <= 1 && Math.abs(market.width - width) <= 1, `edge-to-edge market at ${width}`);
      if (width === 390) await page.screenshot({ path: path.join(__dirname, 'workbench-mobile.png'), fullPage: true });
    }
    // A terminal failure must still expose its existing retry action after relocation.
    await page.evaluate(() => workbench.updateStatus({ status: 'error', progress: { summary: 'failed' }, agent_details: { summary: { status: 'failed', error: '汇总暂时不可用。' } } }));
    assert(await page.locator('[data-agent="summary"] .agent-retry').isVisible());
    await checkDesktopLayout(1440);
    await page.evaluate(() => workbench.renderReport({
      company_name: '预览标的', stock_code: '600000', analysis_date: '2026-11-05',
      final_report: '## 摘要\n\n> **核心判断：** 这是用于界面验证的示例报告。\n\n- **风险：** 关注经营与市场变化。\n\n| 指标 | 数值 |\n| --- | ---: |\n| ROE | 12.5% |',
    }));
    assert(await page.locator('#workbenchReport').isVisible());
    assert(await page.locator('#workbenchReport table').isVisible());
    assert.equal(await page.locator('#reportNavigation a').count(), 1);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: path.join(__dirname, 'report-desktop.png'), fullPage: true });
    console.log(JSON.stringify({ errors, chartLoaded: await page.evaluate(() => !!window.LightweightCharts), checkedWidths: [1920, 1440, 1280, 1024, 900, 768, 390, 320], screenshots: __dirname }));
    assert.deepEqual(errors, []);
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); server.close(); process.exitCode = 1; });
