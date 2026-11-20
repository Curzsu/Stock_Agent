import { expect, test, type Locator, type Page } from '@playwright/test';

function candles(count: number) {
  const result = [];
  for (let elapsed = 0; result.length < count; elapsed += 1) {
    const date = new Date(Date.UTC(2026, 8, 25 - elapsed));
    if (date.getUTCDay() === 0 || date.getUTCDay() === 6) continue;
    const close = 3300 - elapsed * .75 + Math.sin(elapsed) * 10;
    result.push({ time: date.getTime() / 1000, open: close - 4, high: close + 6, low: close - 8, close, volume: 1000 + elapsed });
  }
  return result.reverse();
}

async function mockMarket(page: Page) {
  const requests: string[] = [];
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.pathname + url.search);
    if (url.pathname === '/api/market-kline') {
      const days = Number(url.searchParams.get('days'));
      await route.fulfill({ json: { ok: true, data: candles(Math.min(days, 360)) } });
    } else if (url.pathname === '/api/status/fixture') {
      await route.fulfill({ json: {
        status: 'running',
        company_name: '测试标的',
        stock_code: 'sh.600519',
        progress: { fundamental: 'completed', technical: 'running', value: 'failed' },
        agent_details: { fundamental: { status: 'completed', summary: '已核对财务数据' } },
      } });
    } else if (url.pathname === '/api/stock-market') {
      const frequency = url.searchParams.get('frequency');
      if (frequency === 'm') {
        await route.fulfill({ json: { ok: false, error: '个股月线暂不可用' } });
      } else {
        const close = frequency === 'w' ? 1400 : 1450;
        const offset = 3300 - close;
        await route.fulfill({ json: {
          ok: true,
          code: url.searchParams.get('code'),
          latest_trade_date: '2026-09-25',
          quote: { close, pct_change: -1.2, pe_ttm: 20.12 },
          candles: candles(45).map((row) => ({
            time: new Date(row.time * 1000).toISOString().slice(0, 10),
            open: row.open - offset, high: row.high - offset, low: row.low - offset, close: row.close - offset,
            volume: row.volume, ma5: row.close - offset - 3,
          })),
        } });
      }
    } else {
      await route.fulfill({ status: 404, json: { detail: 'Analysis not found' } });
    }
  });
  return requests;
}

async function chartPixels(chart: Locator) {
  return chart.locator('canvas').first().evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
}

test('index switches periods, toggles averages and pans or zooms only after chart focus', async ({ page }) => {
  const requests = await mockMarket(page);
  await page.goto('/react-preview/');
  const market = page.getByRole('region', { name: '上证指数行情' });
  await market.scrollIntoViewIfNeeded();
  const chart = market.getByRole('img', { name: '上证指数历史行情' });
  await expect(chart.locator('canvas').first()).toBeVisible();
  await expect(market.getByText('最新交易日 2026-09-25')).toBeVisible();

  expect(await chart.evaluate((node) => node.dispatchEvent(new WheelEvent('wheel', {
    deltaY: 120, bubbles: true, cancelable: true,
  })))).toBe(true);
  const daily = market.getByRole('button', { name: '日线' });
  await daily.click();
  const original = await chartPixels(chart);
  expect(await daily.evaluate((node) => node.dispatchEvent(new WheelEvent('wheel', {
    deltaY: -400, bubbles: true, cancelable: true,
  })))).toBe(false);
  await expect.poll(() => chartPixels(chart)).not.toBe(original);
  const zoomed = await chartPixels(chart);
  const bounds = (await chart.boundingBox())!;
  await page.mouse.move(bounds.x + bounds.width * .4, bounds.y + bounds.height * .3);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * .7, bounds.y + bounds.height * .3, { steps: 10 });
  await page.mouse.up();
  await expect.poll(() => chartPixels(chart)).not.toBe(zoomed);

  await market.getByRole('button', { name: '周线' }).click();
  await expect(market.getByRole('button', { name: '周线' })).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => requests).toContain('/api/market-kline?days=240');
  const average = market.getByRole('button', { name: 'MA10' });
  await average.click();
  await expect(average).toHaveAttribute('aria-pressed', 'false');
  await market.getByRole('button', { name: '月线' }).click();
  await expect(market.getByRole('button', { name: '月线' })).toHaveAttribute('aria-pressed', 'true');
});

test('workbench reads the task snapshot and caches stock periods without starting analysis', async ({ page }) => {
  const requests = await mockMarket(page);
  await page.goto('/react-preview/app/analysis/fixture');
  await expect(page.getByRole('heading', { name: '研究工作台' })).toBeVisible();
  await expect(page.getByText('1 / 5 已完成')).toBeVisible();
  await expect(page.getByText('阶段研究结果正在陆续返回')).toBeVisible();
  await expect(page.getByRole('heading', { name: '综合研判' })).toBeVisible();
  await expect(page.getByText('已核对财务数据')).toBeVisible();
  const market = page.getByRole('region', { name: '行情概览' });
  await market.scrollIntoViewIfNeeded();
  await expect(market.getByRole('img', { name: 'sh.600519 历史行情' }).locator('canvas').first()).toBeVisible();
  await expect(market.getByText('1450.00')).toBeVisible();
  await market.getByRole('button', { name: '周线' }).click();
  await expect(market.getByText('1400.00')).toBeVisible();
  await market.getByRole('button', { name: '月线' }).click();
  await expect(market.getByText('个股月线暂不可用')).toBeVisible();
  await expect(market.locator('canvas')).toHaveCount(0);
  await market.getByRole('button', { name: '日线' }).click();
  await expect(market.getByText('1450.00')).toBeVisible();
  expect(requests.filter((item) => item.includes('frequency=d'))).toHaveLength(1);
  expect(requests.some((item) => item.startsWith('/api/analyze'))).toBe(false);
  await page.setViewportSize({ width: 390, height: 740 });
  expect(await page.locator('body').evaluate((body) => body.scrollWidth)).toBeLessThanOrEqual(390);
});

test('index shows the upstream error instead of an empty chart', async ({ page }) => {
  await page.route('**/api/market-kline?*', (route) =>
    route.fulfill({ json: { ok: false, error: '指数查询超时' } }),
  );
  await page.goto('/react-preview/');
  const market = page.getByRole('region', { name: '上证指数行情' });
  await expect(market.getByRole('status')).toHaveText('指数查询超时');
  await expect(market.locator('canvas')).toHaveCount(0);
});
