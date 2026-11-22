import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

const preview = '/react-preview';
const initial = {
  company_name: '贵州茅台',
  stock_code: '600519',
  analysis_date: '2026-09-25',
  fundamental_analysis: '# 原标题\n\n| 指标 | 数值 |\n| --- | ---: |\n| ROE | 15.99% |',
  final_report: '旧版综合结论',
  missing_dimensions: ['technical'],
};

async function stubApi(page: Page, handle: (route: Route, path: string) => Promise<void>) {
  await page.context().route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith('/api/market-') || path === '/api/stock-market') {
      return route.fulfill({ json: { ok: false, error: '离线行情' } });
    }
    if (path === '/api/session') {
      return route.fulfill({ json: { user_id: 'fixture', username: 'alice', csrf_token: 'fixture-csrf' } });
    }
    return handle(route, path);
  });
}

test('opens a degraded report from history and downloads the PDF after it becomes ready', async ({ page }) => {
  const pdf = Buffer.from('%PDF-1.4\n%%EOF\n');
  let probes = 0;
  await stubApi(page, async (route, path) => {
    if (path === '/api/history') {
      await route.fulfill({ json: { history: [
        { analysis_id: 'ongoing', company_name: '进行中标的', status: 'running' },
        { analysis_id: 'report-1', company_name: '贵州茅台', status: 'degraded', analysis_date: '2026-09-25' },
      ] } });
    } else if (path === '/api/result/report-1') {
      await route.fulfill({ json: initial });
    } else if (route.request().headers().range === 'bytes=0-0') {
      probes += 1;
      if (probes === 1) await route.fulfill({ status: 404, json: { detail: { status: 'pending' } } });
      else await route.fulfill({ status: 206, headers: { 'Content-Range': `bytes 0-0/${pdf.length}` }, contentType: 'application/pdf', body: pdf.subarray(0, 1) });
    } else {
      await route.fulfill({ contentType: 'application/pdf', headers: { 'Content-Disposition': 'attachment; filename="FINEX_600519.pdf"' }, body: pdf });
    }
  });
  await page.goto(`${preview}/`);
  const homeHistory = page.getByRole('region', { name: '历史报告' });
  await homeHistory.getByRole('link', { name: '查看全部' }).click();
  await expect(page).toHaveURL(/\/app\/history$/);
  await expect(page.getByRole('link', { name: /进行中标的/ })).toHaveAttribute('href', `${preview}/app/analysis/ongoing`);
  await page.getByRole('link', { name: /贵州茅台/ }).click();
  await expect(page).toHaveURL(/\/app\/analysis\/report-1\/report$/);
  await expect(page.getByRole('heading', { name: '贵州茅台 分析报告' })).toBeVisible();
  await expect(page.getByText('部分研究维度暂缺：技术面分析。')).toBeVisible();
  await expect(page.getByRole('cell', { name: '15.99%' })).toBeVisible();
  await expect(page.getByText('正在生成 PDF...')).toBeVisible();
  await page.getByRole('navigation', { name: '报告章节' }).getByRole('link', { name: /综合研判/ }).click();
  await expect(page).toHaveURL(/#report-summary$/);
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: '下载 PDF 报告' }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('FINEX_600519.pdf');
  expect(await readFile(await download.path())).toEqual(pdf);
  expect(probes).toBe(2);
});

test('retries a failed dimension and clears the previous report and PDF state', async ({ page }) => {
  let started = false;
  let statusReads = 0;
  let retries = 0;
  await stubApi(page, async (route, path) => {
    if (path.endsWith('/retry/technical')) {
      expect(route.request().method()).toBe('POST');
      expect(route.request().headers()['x-csrf-token']).toBe('fixture-csrf');
      started = true;
      retries += 1;
      await route.fulfill({ status: 202, json: { status: 'retrying' } });
    } else if (path.startsWith('/api/result/')) {
      await route.fulfill({ json: started ? { ...initial, final_report: '重试后的综合结论', missing_dimensions: [] } : initial });
    } else if (path.startsWith('/api/status/')) {
      const running = started && ++statusReads === 1;
      await route.fulfill({ json: {
        status: started ? running ? 'running' : 'completed' : 'degraded',
        company_name: initial.company_name,
        progress: { fundamental: 'completed', technical: started ? running ? 'running' : 'completed' : 'failed', summary: running ? 'waiting' : 'completed' },
      } });
    } else if (path.endsWith('/partial')) {
      await route.fulfill({ json: { results: { fundamental_analysis: '已有基本面结果' } } });
    } else if (started) {
      await route.fulfill({ status: 500, json: { detail: { status: 'failed' } } });
    } else {
      await route.fulfill({ contentType: 'application/pdf', body: '%' });
    }
  });
  await page.goto(`${preview}/app/analysis/retry-1/report`);
  await expect(page.getByText('旧版综合结论')).toBeVisible();
  await expect(page.getByRole('button', { name: '下载 PDF 报告' })).toBeVisible();
  await page.getByRole('link', { name: '返回协同台重试失败项' }).click();
  await page.getByRole('button', { name: '重试技术面分析' }).click();
  await expect(page.getByRole('button', { name: '重试技术面分析' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '查看报告' })).toHaveCount(0);
  await expect(page.getByText('重试后的综合结论')).toBeVisible({ timeout: 8000 });
  await expect(page.getByText('旧版综合结论')).toHaveCount(0);
  await expect(page.getByText('PDF 生成失败')).toBeVisible();
  await expect(page.getByRole('button', { name: '下载 PDF 报告' })).toHaveCount(0);
  expect(retries).toBe(1);
});

test('keeps partial results on synthesis failure and checks current state after a conflict', async ({ page }) => {
  let retry = false;
  let reportRequests = 0;
  await stubApi(page, async (route, path) => {
    if (path.endsWith('/retry/summary')) {
      retry = true;
      await route.fulfill({ status: 409, json: { detail: '另一项重试已经在运行' } });
    } else if (path.startsWith('/api/status/')) {
      await route.fulfill({ json: {
        status: retry ? 'running' : 'error',
        error: retry ? null : '综合研判生成失败',
        current_task: retry ? '正在重新汇总' : undefined,
        progress: { fundamental: 'completed', summary: retry ? 'running' : 'failed' },
      } });
    } else if (path.endsWith('/partial')) {
      await route.fulfill({ json: { results: { fundamental_analysis: '已有基本面证据' } } });
    } else {
      reportRequests += 1;
      await route.fulfill({ status: 404, json: {} });
    }
  });
  await page.goto(`${preview}/app/analysis/conflict`);
  await expect(page.getByRole('alert')).toHaveText('综合研判生成失败');
  await page.getByText('查看阶段结果').click();
  await expect(page.getByText('已有基本面证据')).toBeVisible();
  await page.getByRole('button', { name: '重试综合研判' }).click();
  await expect(page.getByText('另一项重试已经在运行')).toBeVisible();
  await expect(page.getByText('正在重新汇总')).toBeVisible();
  await expect(page.getByText('已有基本面证据')).toBeVisible();
  expect(reportRequests).toBe(0);
});

for (const width of [1280, 390]) {
  test(`keeps legacy report and history card surfaces at ${width}px`, async ({ context, page }) => {
    const legacy = await context.newPage();
    for (const tab of [legacy, page]) await tab.setViewportSize({ width, height: 900 });
    const source = await readFile(resolve(__dirname, '../index.html'), 'utf8');
    const css = await readFile(resolve(__dirname, '../workbench.css'), 'utf8');
    await legacy.route('**/legacy-visual-baseline', (route) => route.fulfill({ contentType: 'text/html', body: source
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
      .replace(/<link\b[^>]*href="https:[^"]+"[^>]*>/gi, '')
      .replace('id="workbenchReport" hidden', 'id="workbenchReport"')
      .replace('id="historyGrid">', 'id="historyGrid"><div class="history-card">贵州茅台</div>'),
    }));
    await legacy.route('**/static/workbench.css', (route) => route.fulfill({ contentType: 'text/css', body: css }));
    await legacy.goto('/legacy-visual-baseline');
    await legacy.locator('#analysisSection').evaluate((element) => { element.classList.add('active'); });
    await stubApi(page, async (route, path) => {
      if (path === '/api/history') {
        await route.fulfill({ json: { history: [{ analysis_id: 'visual', company_name: '贵州茅台', status: 'completed' }] } });
      } else if (path.startsWith('/api/result/')) {
        await route.fulfill({ json: initial });
      } else {
        await route.fulfill({ status: 404, json: {} });
      }
    });
    const surface = (element: Element) => {
      const style = getComputedStyle(element);
      return [style.backgroundColor, style.borderTopWidth, style.borderRadius, style.boxShadow];
    };
    await page.goto(`${preview}/`);
    const card = page.getByRole('region', { name: '历史报告' }).getByRole('listitem');
    expect(await card.evaluate(surface)).toEqual(await legacy.locator('.history-card').evaluate(surface));
    await card.getByRole('link').click();
    const report = page.getByRole('article');
    expect(await report.evaluate(surface)).toEqual(await legacy.locator('#workbenchReport').evaluate(surface));
    expect(await page.locator('body').evaluate((body) => body.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
