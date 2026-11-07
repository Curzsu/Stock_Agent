const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1105-1297-0_26.1105.1297.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 850 } });
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<main id="analysisWorkbench"><h1>研究工作台 · K 线交互验证</h1><div class="market-periods"><button>日 K</button><button>周 K</button><button>月 K</button></div><div id="workbenchMarketChart" style="width:900px;height:430px"></div><p id="outside">图表外部</p></main>');
    await page.addScriptTag({ url: 'https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js' });
    await page.addScriptTag({ path: 'E:/Curzsu/Finance1/frontend/workbench.js' });
    await page.evaluate(() => {
      const original = LightweightCharts.createChart;
      window.controller = FinexWorkbench.createController(document.querySelector('main'), {
        LightweightCharts: { createChart(...args) { window.chart = original(...args); return window.chart; } },
      });
      window.payload = { ok: true, candles: Array.from({ length: 120 }, (_, i) => ({
        time: 1700000000 + i * 86400, open: 100 + i, high: 105 + i, low: 95 + i,
        close: 102 + i, volume: 1000 + i * 5,
      })) };
      controller.renderMarket(payload);
      chart.timeScale().setVisibleLogicalRange({ from: 40, to: 119.5 });
    });
    const range = () => page.evaluate(() => chart.timeScale().getVisibleLogicalRange());
    await page.locator('#workbenchMarketChart').hover({ position: { x: 450, y: 200 } });
    const initial = await range();
    await page.mouse.wheel(0, 100);
    await page.waitForTimeout(250);
    assert.deepEqual(await range(), initial);
    await page.locator('#workbenchMarketChart').click({ position: { x: 450, y: 200 } });
    await page.mouse.wheel(0, 100);
    await page.waitForTimeout(250);
    const out = await range();
    assert(out.from < initial.from);
    assert.equal(out.to, initial.to);
    await page.mouse.wheel(0, -100);
    await page.waitForTimeout(250);
    const inside = await range();
    assert(inside.to - inside.from < out.to - out.from);
    await page.locator('#outside').click();
    await page.locator('#workbenchMarketChart').hover({ position: { x: 450, y: 200 } });
    await page.mouse.wheel(0, 100);
    await page.waitForTimeout(250);
    assert.deepEqual(await range(), inside);
    await page.evaluate(() => chart.timeScale().setVisibleLogicalRange({ from: 90, to: 140 }));
    await page.waitForTimeout(100);
    assert.equal((await range()).to, 119.5);
    await page.evaluate(() => { controller.renderMarket(payload); chart.timeScale().setVisibleLogicalRange({ from: 20, to: 100 }); });
    await page.locator('.market-periods button').first().click();
    await page.locator('.market-periods button').first().hover();
    await page.mouse.wheel(0, 100);
    await page.waitForTimeout(250);
    assert((await range()).from < 20);
    assert.equal((await range()).to, 100);
    await page.setViewportSize({ width: 390, height: 850 });
    await page.evaluate(() => { document.querySelector('#workbenchMarketChart').style.width = '350px'; });
    await page.waitForTimeout(250);
    assert.equal(await page.evaluate(() => chart.options().width), 350);
    await page.screenshot({ path: 'E:/Curzsu/Finance1/output/playwright/research-kline-mobile.png' });
    await page.evaluate(() => controller.destroy());
    assert.deepEqual(errors, []);
    console.log('Browser PASS: click focus, page scrolling, anchored zoom out, native zoom in, future clamp, period controls, resize and teardown.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
