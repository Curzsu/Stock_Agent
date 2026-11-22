import { expect, test, type Page, type Route } from '@playwright/test';

async function mockApi(page: Page, handle: (route: Route, path: string) => Promise<void>) {
  await page.context().route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith('/api/market-') || path === '/api/stock-market') {
      await route.fulfill({ json: { ok: false, error: '离线测试' } });
    } else if (path === '/api/history') {
      await route.fulfill({ json: { history: [] } });
    } else if (path === '/api/session') {
      await route.fulfill({ json: { user_id: 'fixture', username: 'alice', csrf_token: 'fixture-csrf' } });
    } else {
      await handle(route, path);
    }
  });
}

test('submits the old search form and resumes partial progress at the task URL', async ({ page }) => {
  let creates = 0;
  let partialReads = 0;
  await page.addInitScript(() => {
    const messages: string[] = [];
    Object.defineProperty(window, 'finexTestNotifications', { value: messages });
    Object.defineProperty(window, 'Notification', { value: class {
      static permission = 'granted';
      constructor(title: string) { messages.push(title); }
    } });
  });
  let reads = 0;
  await mockApi(page, async (route, path) => {
    if (path === '/api/analyze') {
      creates += 1;
      expect(route.request().method()).toBe('POST');
      expect(route.request().headers()['x-csrf-token']).toBe('fixture-csrf');
      expect(route.request().postDataJSON()).toEqual({ query: '600519' });
      await route.fulfill({ json: { analysis_id: 'research-1' } });
    } else if (path === '/api/status/research-1') {
      reads += 1;
      const completed = reads >= 3;
      await route.fulfill({ json: {
        company_name: '贵州茅台',
        status: completed ? 'completed' : reads === 2 ? 'degraded' : 'running',
        end_time: completed ? '2026-09-25T10:00:00' : undefined,
        progress: { fundamental: 'completed', summary: completed ? 'completed' : 'running' },
      } });
    } else if (path === '/api/analysis/research-1/partial') {
      partialReads += 1;
      await route.fulfill({ json: { results: { fundamental_analysis: '财务数据已核对。<script>bad</script>' } } });
    } else if (path === '/api/result/research-1') {
      await route.fulfill({ json: { company_name: '贵州茅台', final_report: '综合结论已生成。' } });
    } else {
      await route.fulfill({ status: 404, json: {} });
    }
  });

  await page.goto('/react-preview/');
  await page.getByRole('button', { name: '600519', exact: true }).click();
  await expect(page.getByRole('textbox')).toHaveValue('600519');
  expect(creates).toBe(0);
  await page.getByRole('textbox').press('Enter');
  await expect(page).toHaveURL(/\/app\/analysis\/research-1$/);
  await expect(page.getByRole('heading', { name: '正在研究 贵州茅台' })).toBeVisible();
  await page.getByText('查看阶段结果').click();
  await expect(page.getByText('财务数据已核对。<script>bad</script>')).toBeVisible();
  await expect(page).toHaveURL(/\/app\/analysis\/research-1\/report$/, { timeout: 8000 });
  await expect(page.getByText('综合结论已生成。')).toBeVisible();
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'finexTestNotifications'))).toEqual(['股票分析完成']);
  expect(partialReads).toBe(1);

  await page.getByRole('link', { name: '返回研究工作台' }).click();
  await page.reload();
  await page.getByText('查看阶段结果').click();
  await expect(page.getByText('财务数据已核对。<script>bad</script>')).toBeVisible();
  expect(creates).toBe(1);
  expect(partialReads).toBe(2);
  expect(await page.evaluate(() => Reflect.get(window, 'finexTestNotifications'))).toEqual([]);
});

test('shows a submission failure and waits for the user before sending another request', async ({ page }) => {
  let creates = 0;
  await page.addInitScript(() => {
    Object.defineProperty(window, 'Notification', { value: { permission: 'denied' } });
  });
  await mockApi(page, async (route) => {
    creates += 1;
    await route.fulfill({ status: 422, json: { detail: [{ msg: '测试：当前无法提交研究' }] } });
  });
  await page.goto('/react-preview/');
  await page.getByRole('textbox').fill('a');
  await page.getByRole('button', { name: '开始分析' }).click();
  await expect(page.getByRole('alert')).toHaveText('请输入至少2个字符的公司名称或股票代码');
  expect(creates).toBe(0);
  await page.getByRole('textbox').fill('贵州茅台');
  await page.getByRole('button', { name: '开始分析' }).click();
  await expect(page.getByRole('alert')).toHaveText('测试：当前无法提交研究');
  await expect(page.getByRole('button', { name: '开始分析' })).toBeEnabled();
  expect(creates).toBe(1);
});

test('reuses the submission key after a lost response and starts a new key after editing', async ({ page }) => {
  const keys: string[] = [];
  await mockApi(page, async (route, path) => {
    expect(path).toBe('/api/analyze');
    keys.push(route.request().headers()['idempotency-key']);
    await route.fulfill({ status: 503, json: { detail: '请求结果未知，请重试' } });
  });
  await page.goto('/react-preview/');
  const input = page.getByRole('textbox');
  const submit = page.getByRole('button', { name: '开始分析' });
  await input.fill('600519');
  await submit.click();
  await expect(page.getByRole('alert')).toHaveText('请求结果未知，请重试');
  expect(keys).toHaveLength(1);
  expect(keys[0]).toBeTruthy();
  await submit.click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[1]).toBe(keys[0]);
  await expect(submit).toBeEnabled();
  await input.fill('600900');
  await submit.click();
  await expect.poll(() => keys.length).toBe(3);
  expect(keys[2]).toBeTruthy();
  expect(keys[2]).not.toBe(keys[0]);
});

test('keeps completed research visible for an interrupted task', async ({ page }) => {
  let reads = 0;
  await mockApi(page, async (route, path) => {
    if (path.startsWith('/api/status/')) {
      reads++;
      await route.fulfill({ json: { status: 'interrupted', progress: { fundamental: 'completed' }, error: '请重新发起研究' } });
    } else {
      await route.fulfill({ json: { results: { fundamental_analysis: '仍可读的基本面结果' } } });
    }
  });
  await page.goto('/react-preview/app/analysis/interrupted-task');
  await expect(page.getByRole('alert')).toHaveText('请重新发起研究');
  await page.getByText('查看阶段结果').click();
  await expect(page.getByText('仍可读的基本面结果')).toBeVisible();
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  expect(reads).toBe(1);
});

test('falls back without Worker and refreshes immediately when the tab becomes visible', async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(window, 'Worker', { value: undefined }); });
  let reads = 0;
  await mockApi(page, async (route) => {
    reads += 1;
    await route.fulfill({ json: { status: 'running', current_task: `第 ${reads} 次状态读取` } });
  });
  await page.goto('/react-preview/app/analysis/fallback');
  await expect(page.getByText('第 1 次状态读取')).toBeVisible();
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.getByText('第 2 次状态读取')).toBeVisible({ timeout: 1500 });
});

test('discards late status from a previous task and stops waiting at 30 minutes', async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(window, 'Worker', { value: undefined }); });
  await page.clock.install();
  let finishOld!: () => void;
  const old = new Promise<void>((resolve) => { finishOld = resolve; });
  let oldStarted = false;
  await mockApi(page, async (route, path) => {
    if (path === '/api/status/old') {
      oldStarted = true;
      await old;
      await route.fulfill({ json: { status: 'completed', company_name: '迟到的旧任务' } }).catch(() => undefined);
    } else {
      await route.fulfill({ json: { status: 'running', company_name: '当前任务' } });
    }
  });
  await page.goto('/react-preview/app/analysis/old');
  await expect.poll(() => oldStarted).toBe(true);
  await page.evaluate(() => {
    history.pushState({ idx: history.state.idx + 1 }, '', '/react-preview/app/analysis/current');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  await expect(page.getByRole('heading', { name: '正在研究 当前任务' })).toBeVisible();
  finishOld();
  await page.clock.fastForward(30 * 60 * 1000);
  await expect(page.getByRole('alert')).toHaveText('分析超时，请稍后重试。');
  await expect(page.getByText('迟到的旧任务')).toHaveCount(0);
});

test('keeps the original inertial wheel behavior and supports reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await mockApi(page, (route) => route.fulfill({ status: 404, json: {} }));
  await page.goto('/react-preview/');
  await expect(page.locator('html')).toHaveClass(/lenis-stopped/);
  await expect(page.locator('html')).not.toHaveClass(/lenis-stopped/);
  await page.mouse.move(24, 250);
  await page.mouse.wheel(0, 400);
  const positions = await page.evaluate(async () => {
    const scrolls = [];
    for (let frame = 0; frame < 10; frame += 1) {
      await new Promise(requestAnimationFrame);
      scrolls.push(window.scrollY);
    }
    return scrolls;
  });
  expect(positions.at(-1)).toBeGreaterThan(positions[0]);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(page.locator('html')).not.toHaveClass(/\blenis\b/);
  await expect(page.getByRole('textbox')).toBeVisible();
});
