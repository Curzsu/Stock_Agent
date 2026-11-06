const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {
  derivePhase,
  normalizeAgentDetails,
  buildMarketSeries,
  completedResultKeys,
  createController,
  nextRequests,
  resolveChartSize,
  stripLeadingMarkdownHeading,
  agentSummaryForStatus,
  canRetryAgent,
  formatAnalysisMarkdown,
} = require('../../frontend/workbench.js');

test('one-page summary renders the conclusion as a quote and preserves evidence bullets safely', () => {
  const html = formatAnalysisMarkdown('## 摘要\n\n**研究对象：** 示例公司（600000）\n\n> **核心判断：** <script>alert(1)</script>\n> 仍需验证。\n\n- **风险：** 现金流走弱。\n- **观察：** 下期财报。');
  assert.ok(html.includes('<h3>摘要</h3>'));
  assert.ok(html.includes('<blockquote>'));
  assert.ok(html.includes('<strong>核心判断：</strong>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('&gt; <strong>核心判断'));
  assert.ok(html.includes('<li><strong>风险：</strong> 现金流走弱。</li>'));
});

test('report source TOC markers are hidden without deleting literal code examples', () => {
  const html = formatAnalysisMarkdown('[TOC]\n\n## 摘要\n\n内容。\n\n```text\n[TOC]\n```');
  assert.equal((html.match(/\[TOC\]/g) || []).length, 1);
  assert.ok(html.includes('<h3>摘要</h3>'));
  assert.ok(html.includes('内容。'));
});

test('financial Markdown tables render semantic cells and preserve values and alignment', () => {
  const html = formatAnalysisMarkdown('## 财务指标\n| 指标 | 数值 | 解读 |\n| :--- | ---: | :---: |\n| **ROE** | **15.99%** | 保持稳健 |\n| 净利润 | 349.49亿元 | 同比改善 |');
  assert.match(html, /<h3>财务指标<\/h3>/);
  assert.match(html, /<table>/);
  assert.match(html, /<th scope="col"[^>]*>数值<\/th>/);
  assert.match(html, /<td class="align-right"><strong>15.99%<\/strong><\/td>/);
  assert.match(html, /349\.49亿元/);
  assert.doesNotMatch(html, /<br>\|/);
});

test('headings, ordered risks and wrapped nested lists do not require blank lines', () => {
  const html = formatAnalysisMarkdown('### 风险因素\n1. **来水风险**：发电量下降。\n   需持续关注流域来水。\n2. 利率上行。\n   - 观察国债收益率。\n   - 观察分红变化。\n\n后续观察。\n---\n#### 数据来源\n公开财报。');
  assert.match(html, /<h4>风险因素<\/h4><ol/);
  assert.match(html, /来水风险<\/strong>：发电量下降。.*需持续关注流域来水。/);
  assert.match(html, /<li>利率上行。<ul><li>观察国债收益率。<\/li><li>观察分红变化。<\/li><\/ul><\/li>/);
  assert.match(html, /<p>后续观察。<\/p><hr><h4>数据来源<\/h4><p>公开财报。<\/p>/);
});

test('report links are readable but HTML and unsafe link protocols stay inert', () => {
  const html = formatAnalysisMarkdown('[财报](https://example.com/report?a=1&b=2) 与 [危险链接](javascript:alert(1))\n\n<img src=x onerror=alert(1)>');
  assert.match(html, /<a href="https:\/\/example.com\/report\?a=1&amp;b=2"[^>]*>财报<\/a>/);
  assert.doesNotMatch(html, /href="javascript:|<img|<script/);
  assert.match(html, /&lt;img/);
});

test('fenced and inline code preserve literal Markdown and table pipes', () => {
  const html = formatAnalysisMarkdown('```text\n## 标题\n**ROE** <script>\n[TOC]\n```\n\n`**peTTM**`\n\n| 指标 | 说明 |\n| --- | --- |\n| `a|b` | A\\|B |');
  assert.match(html, /<pre><code>## 标题\n\*\*ROE\*\* &lt;script&gt;\n\[TOC\]<\/code><\/pre>/);
  assert.match(html, /<code>\*\*peTTM\*\*<\/code>/);
  assert.match(html, /<td><code>a\|b<\/code><\/td><td>A\|B<\/td>/);
});

test('empty headings in a generated response do not abort report rendering', () => {
  const html = formatAnalysisMarkdown('## \n\n后续内容。');
  assert.match(html, /<p>后续内容。<\/p>/);
});

test('derivePhase distinguishes partial and summarizing states', () => {
  assert.equal(derivePhase({
    status: 'running',
    progress: { fundamental: 'completed', technical: 'running', value: 'waiting', news: 'waiting', summary: 'waiting' },
  }), 'partial');
  assert.equal(derivePhase({
    status: 'running',
    progress: { fundamental: 'completed', technical: 'completed', value: 'completed', news: 'completed', summary: 'running' },
  }), 'summarizing');
  assert.equal(derivePhase({
    status: 'degraded',
    progress: { fundamental: 'failed', technical: 'failed', value: 'running', news: 'failed', summary: 'completed' },
  }), 'running');
});

test('normalizeAgentDetails supplies safe waiting defaults', () => {
  const details = normalizeAgentDetails({ fundamental: { status: 'completed', summary: '稳健' } });
  assert.equal(details.fundamental.summary, '稳健');
  assert.equal(details.news.status, 'waiting');
});

test('running agents show active research copy before a partial result exists', () => {
  assert.equal(
    agentSummaryForStatus('technical', { status: 'running', summary: '', error: null }),
    '正在核对价格趋势、成交动能与关键压力区。',
  );
  assert.equal(
    agentSummaryForStatus('technical', { status: 'completed', summary: '阶段结论', error: null }),
    '阶段结论',
  );
  assert.equal(
    agentSummaryForStatus('technical', { status: 'failed', summary: '', error: '模型不可用' }),
    '模型不可用',
  );
});

test('buildMarketSeries preserves real candles and skips missing moving averages', () => {
  const series = buildMarketSeries({ candles: [
    { time: 1, open: 1, high: 2, low: 0.5, close: 1.5, volume: 100, ma5: null, ma20: null },
    { time: 2, open: 1.5, high: 3, low: 1, close: 2.5, volume: 200, ma5: 2, ma20: null },
  ] });
  assert.equal(series.candles.length, 2);
  assert.deepEqual(series.ma5, [{ time: 2, value: 2 }]);
  assert.equal(series.volume[1].value, 200);
});

test('completedResultKeys returns only newly available completed dimensions', () => {
  assert.deepEqual(
    completedResultKeys({ fundamental: 'completed', technical: 'running' }, new Set()),
    ['fundamental'],
  );
});

test('index contains one in-place workbench and all five agent cards', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  assert.match(html, /id="analysisWorkbench"/);
  assert.match(html, /id="workbenchMarketChart"/);
  assert.match(html, /data-agent="fundamental"/);
  assert.match(html, /data-agent="technical"/);
  assert.match(html, /data-agent="value"/);
  assert.match(html, /data-agent="news"/);
  assert.match(html, /data-agent="summary"/);
  assert.doesNotMatch(html, /id="goToReportBtn"/);
});

test('index declares an inline favicon to avoid a noisy 404', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  assert.match(html, /rel="icon" href="data:image\/svg\+xml/);
});

test('workbench exposes a DOM controller factory', () => {
  assert.equal(typeof createController, 'function');
});

test('history treats untrusted names, codes and dates as text', async () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  const functionSource = html.slice(html.indexOf('    async function loadHistory()'), html.indexOf('    // 恢复正在进行的分析视图'));
  const cards = [];
  const context = vm.createContext({
    API_BASE: '/api', console, window: {},
    document: {
      getElementById: (id) => id === 'historyGrid' ? { appendChild: (card) => cards.push(card) } : {},
      createElement: () => ({ style: {}, addEventListener() {} }),
    },
    fetch: async () => ({ json: async () => ({ history: [{
      company_name: '<img src=x onerror=alert(1)>', stock_code: '<svg/onload=alert(1)>',
      analysis_date: '<img src=x', status: 'error', analysis_id: 'probe',
    }] }) }),
  });
  const escapeStart = html.indexOf('    function escapeReportHtml(value)');
  vm.runInContext(html.slice(escapeStart, html.indexOf('    function formatAnalysisMarkdown', escapeStart)), context);
  vm.runInContext(functionSource, context);
  await context.loadHistory();
  assert.equal(cards.length, 1);
  assert.doesNotMatch(cards[0].innerHTML, /<img|<svg/);
  assert.match(cards[0].innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

test('history navigation follows card width and disables unavailable directions', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  const start = html.indexOf('    // 历史轮播按钮');
  const listeners = {};
  const prev = { disabled: false, addEventListener: (_, fn) => { listeners.prev = fn; } };
  const next = { disabled: false, addEventListener: (_, fn) => { listeners.next = fn; } };
  let onResize, onMutation;
  const grid = {
    clientWidth: 360, scrollWidth: 980, scrollLeft: 0,
    querySelector: () => ({ getBoundingClientRect: () => ({ width: 284 }) }),
    addEventListener: (_, fn) => { listeners.scroll = fn; },
    scrollBy({ left }) {
      this.scrollLeft = Math.max(0, Math.min(this.scrollWidth - this.clientWidth, this.scrollLeft + left));
      listeners.scroll();
    },
  };
  const context = vm.createContext({
    document: { getElementById: id => ({ historyGrid: grid, historyPrev: prev, historyNext: next }[id]) },
    getComputedStyle: () => ({ columnGap: '24px' }),
    window: { matchMedia: () => ({ matches: true }) },
    ResizeObserver: class { constructor(fn) { onResize = fn; } observe() {} },
    MutationObserver: class { constructor(fn) { onMutation = fn; } observe() {} },
  });
  vm.runInContext(html.slice(start, html.indexOf('    // 配置 API Key 按钮', start)), context);
  assert.equal(prev.disabled, true);
  assert.equal(next.disabled, false);
  listeners.next();
  assert.equal(grid.scrollLeft, 308);
  assert.equal(prev.disabled, false);
  listeners.next(); listeners.next();
  assert.equal(next.disabled, true);
  listeners.prev();
  assert.equal(next.disabled, false);
  grid.scrollWidth = 300; grid.scrollLeft = 0;
  onMutation();
  assert.equal(prev.disabled, true);
  assert.equal(next.disabled, true);
  grid.scrollWidth = 1100;
  onResize();
  assert.equal(next.disabled, false);
});

test('nextRequests fetches partials only when a dimension newly completes', () => {
  const requests = nextRequests(
    { fundamental: 'running', technical: 'running' },
    { progress: { fundamental: 'completed', technical: 'running' } },
  );
  assert.deepEqual(requests, { partial: true, result: false });
});

test('nextRequests fetches final result for completed or degraded sessions', () => {
  assert.deepEqual(
    nextRequests({}, { status: 'degraded', progress: {} }),
    { partial: false, result: true },
  );
});

test('a stale terminal status does not finish while a retry is running', () => {
  assert.deepEqual(
    nextRequests({}, { status: 'degraded', progress: { value: 'running' } }),
    { partial: false, result: false },
  );
});

test('retry actions are enabled only when the session is terminal and idle', () => {
  assert.equal(canRetryAgent({ status: 'running', progress: {} }, 'failed'), false);
  assert.equal(canRetryAgent({ status: 'degraded', progress: { value: 'running' } }, 'failed'), false);
  assert.equal(canRetryAgent({ status: 'degraded', progress: { value: 'failed' } }, 'failed'), true);
});

test('failed synthesis can be retried without restarting completed analysis', () => {
  assert.equal(canRetryAgent({ status: 'error', progress: { summary: 'failed' } }, 'failed', 'summary'), true);
  assert.equal(canRetryAgent({ status: 'error', progress: { summary: 'running' } }, 'failed', 'summary'), false);
  const source = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  const summaryCard = source.slice(source.indexOf('data-agent="summary"'), source.indexOf('data-agent="summary"') + 2200);
  assert.match(summaryCard, /class="agent-retry"/);
});

test('resolveChartSize supplies a visible fallback while the workbench is hidden', () => {
  assert.deepEqual(resolveChartSize(0, 0), { width: 640, height: 430 });
  assert.deepEqual(resolveChartSize(360, 500), { width: 360, height: 500 });
});

test('stripLeadingMarkdownHeading removes only the report source heading', () => {
  assert.equal(
    stripLeadingMarkdownHeading('# 基本面分析\n\n盈利能力稳健。'),
    '盈利能力稳健。',
  );
  assert.equal(stripLeadingMarkdownHeading('盈利能力稳健。'), '盈利能力稳健。');
});

test('completed cards keep the warm workbench surface', () => {
  const css = fs.readFileSync(path.join(__dirname, '../../frontend/workbench.css'), 'utf8');
  assert.match(css, /\.agent-card\.complete\s*\{[^}]*background:/s);
});

test('workbench columns can shrink to a mobile viewport', () => {
  const css = fs.readFileSync(path.join(__dirname, '../../frontend/workbench.css'), 'utf8');
  assert.match(css, /\.agent-workspace\s*\{[^}]*min-width:\s*0/s);
  assert.match(css, /\.market-overview\s*\{[^}]*min-width:\s*0/s);
});

test('starting the worker preserves the active polling deadline', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  assert.match(html, /function stopBackgroundPolling\(resetDeadline = true\)/);
  assert.match(html, /function startBackgroundPolling\(\)\s*\{\s*stopBackgroundPolling\(false\)/s);
});

test('obsolete worker messages and errors cannot affect the active analysis', () => {
  const { context } = pollingHarness(0);
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  Object.assign(context, {
    Blob, URL: { createObjectURL: () => 'blob:probe' },
    Worker: class { postMessage() {} },
  });
  const start = html.indexOf('    function startBackgroundPolling()');
  vm.runInContext(html.slice(start, html.indexOf('    // 启动/恢复轮询', start)), context);
  let fallbacks = 0;
  const delivered = [];
  context.startFallbackPolling = () => fallbacks++;
  context.handlePollStatus = (status) => delivered.push(status);
  context.startBackgroundPolling();
  const oldWorker = context._statusWorker;
  context.currentAnalysisId = 'second';
  context._analysisViewVersion++;
  context.startBackgroundPolling();
  oldWorker.onmessage({ data: { type: 'status', status: { analysis_id: 'probe' } } });
  oldWorker.onerror();
  assert.equal(delivered.length, 0);
  assert.equal(fallbacks, 0);
  context._statusWorker.onmessage({ data: { type: 'status', status: { analysis_id: 'second' } } });
  context._statusWorker.onerror();
  assert.equal(delivered[0].analysis_id, 'second');
  assert.equal(fallbacks, 1);
});

test('initial polling never restarts after terminal status or a session switch', async () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  for (const switchSession of [false, true]) {
    let started = 0;
    let finishPoll;
    const context = vm.createContext({
      currentAnalysisId: 'A', _analysisViewVersion: 0, _completionHandled: false,
      _pollDeadline: 0, POLL_MAX_MS: 10000,
      pollOnceNow: () => new Promise((resolve) => { finishPoll = resolve; }),
      startBackgroundPolling: () => started++,
    });
    const start = html.indexOf('    async function pollAnalysisStatus()');
    vm.runInContext(html.slice(start, html.indexOf('    // 切回前台', start)), context);
    const pending = context.pollAnalysisStatus();
    if (switchSession) { context.currentAnalysisId = 'B'; context._analysisViewVersion++; }
    else context._pollDeadline = 0;
    finishPoll();
    await pending;
    assert.equal(started, 0);
  }
});

test('analysis startup rejects an unsuccessful API response', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  assert.match(html, /if \(!response\.ok \|\| !data\.analysis_id\) throw new Error/);
});

test('real analysis startup errors never switch to fabricated demo data', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  const functionSource = html.match(/async function startRealAnalysis[\s\S]+?(?=\n    async function loadWorkbenchMarket)/)[0];
  assert.match(functionSource, /workbench\.renderError/);
  assert.doesNotMatch(functionSource, /runDemoSimulation/);
});

test('opening a degraded report restores its agent lifecycle states', async () => {
  const { context, rendered } = navigationHarness();
  const statuses = [];
  context.workbench.updateStatus = (status) => statuses.push(status);
  context.fetch = async (url) => ({ ok: true, json: async () => url.includes('/status/')
    ? { status: 'degraded', progress: { news: 'failed' }, stock_code: '600519' }
    : { final_report: 'partial report', missing_dimensions: ['news'] } });
  await context.viewCompletedReport('probe');
  assert.equal(statuses[0].progress.news, 'failed');
  assert.equal(context.currentMarketCode, '600519');
  assert.equal(rendered[0].final_report, 'partial report');
});

test('PDF pending response keeps polling until the file is ready', async () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  const start = html.indexOf('    async function pollPdfAvailability()');
  const outcomes = [];
  const scheduled = [];
  const responses = [
    { ok: false, json: async () => ({ detail: { status: 'pending' } }) },
    { ok: true },
  ];
  const context = vm.createContext({
    API_BASE: '/api', currentAnalysisId: 'probe', pdfPollingTimer: null,
    fetch: async () => responses.shift(), clearTimeout() {},
    setTimeout: (fn, ms) => { scheduled.push({ fn, ms }); return 1; },
    enablePdfButton: () => outcomes.push('ready'),
    pdfGenerationFailed: () => outcomes.push('failed'),
  });
  vm.runInContext(html.slice(start, html.indexOf('    // PDF download button', start)), context);
  await context.pollPdfAvailability();
  assert.deepEqual(outcomes, []);
  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].ms, 3000);
  await scheduled[0].fn();
  assert.deepEqual(outcomes, ['ready']);
});

function pollingHarness(deadline, completionHandled = false) {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  const start = html.indexOf('    function handlePollStatus(status)');
  const errors = [];
  const rendered = [];
  const timers = [];
  const retryButton = { hidden: true, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } };
  const context = vm.createContext({
    _pollDeadline: deadline, _completionHandled: completionHandled,
    _resultLoad: null, _analysisViewVersion: 0, AbortController,
    previousProgress: {}, currentMarketCode: null, elapsedInterval: null,
    currentAnalysisId: 'probe', currentQuery: 'stock', API_BASE: '/api', console: { error() {} },
    document: { getElementById: () => retryButton },
    window: { FinexWorkbench: require('../../frontend/workbench.js') },
    workbench: { updateStatus() {}, renderError: (message) => errors.push(message) },
    stopBackgroundPolling() {}, clearInterval() {}, fetchPartialResults() {},
    setTimeout(fn, ms) { const timer = { fn, ms, active: true }; timers.push(timer); return timer; },
    clearTimeout(timer) { if (timer) timer.active = false; },
    fetch: async () => ({ ok: true, json: async () => ({ final_report: 'report' }) }),
    displayResults: (result) => rendered.push(result),
  });
  vm.runInContext(html.slice(start, html.indexOf('    // 立即补一次轮询', start)), context);
  return { context, errors, rendered, timers, retryButton };
}

test('refreshing an already completed report does not report a timeout', () => {
  const { context, errors } = pollingHarness(0, true);
  context.handlePollStatus({ status: 'completed', progress: {} });
  assert.deepEqual(errors, []);
});

test('a terminal status received after the polling deadline still shows its result', async () => {
  const { context, errors, rendered } = pollingHarness(1);
  context.handlePollStatus({ status: 'completed', progress: {} });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(errors, []);
  assert.equal(rendered[0].final_report, 'report');
});

test('an active analysis still times out after its polling deadline', () => {
  const { context, errors } = pollingHarness(1);
  context.handlePollStatus({ status: 'running', progress: { news: 'running' } });
  assert.equal(errors.length, 1);
  assert.match(errors[0], /超时/);
});

test('completed report retrieval recovers from a transient network failure', async () => {
  const { context, rendered, timers } = pollingHarness(0);
  let calls = 0;
  context.fetch = async () => {
    if (++calls === 1) throw new Error('temporary network failure');
    return { ok: true, json: async () => ({ final_report: 'recovered report' }) };
  };
  context.handlePollStatus({ status: 'completed', progress: {} });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(context._completionHandled, false);
  assert.equal(rendered.length, 0);
  const retry = timers.find((timer) => timer.active && timer.ms === 2000);
  assert.ok(retry, 'a failed result fetch must schedule another attempt');
  await retry.fn();
  assert.equal(calls, 2);
  assert.equal(rendered[0].final_report, 'recovered report');
  assert.equal(context._completionHandled, true);
});

test('HTTP errors and invalid report payloads are retried instead of rendered', async () => {
  for (const response of [
    { ok: false, status: 503, json: async () => ({ detail: 'unavailable' }) },
    { ok: true, json: async () => ({ final_report: ' \n ' }) },
    { ok: true, json: async () => { throw new SyntaxError('invalid JSON'); } },
  ]) {
    const { context, rendered, timers } = pollingHarness(0);
    context.fetch = async () => response;
    context.handlePollStatus({ status: 'completed', progress: {} });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(rendered.length, 0);
    assert.equal(context._completionHandled, false);
    assert.ok(timers.some((timer) => timer.active && timer.ms === 2000));
  }
});

test('concurrent completed statuses retrieve and notify only once', async () => {
  const { context, rendered } = pollingHarness(0);
  const notifications = [];
  context.window.Notification = true;
  context.Notification = class {
    static permission = 'granted';
    constructor(...args) { notifications.push(args); }
  };
  let resolve;
  let calls = 0;
  context.fetch = () => { calls++; return new Promise((done) => { resolve = done; }); };
  context.handlePollStatus({ status: 'completed', progress: {} });
  context.handlePollStatus({ status: 'completed', progress: {} });
  assert.equal(calls, 1);
  assert.equal(context._completionHandled, false);
  resolve({ ok: true, json: async () => ({ final_report: 'report' }) });
  await new Promise((done) => setImmediate(done));
  context.handlePollStatus({ status: 'completed', progress: {} });
  assert.equal(calls, 1);
  assert.equal(rendered.length, 1);
  assert.equal(notifications.length, 1);
});

test('a completed result arriving after switching analyses is ignored', async () => {
  const { context, rendered } = pollingHarness(0);
  const pending = [];
  context.fetch = () => new Promise((resolve) => pending.push(resolve));
  context.handlePollStatus({ status: 'completed', progress: {} });
  context.currentAnalysisId = 'second';
  context._completionHandled = false;
  context.handlePollStatus({ status: 'completed', progress: {} });
  assert.equal(pending.length, 2);
  pending[0]({ ok: true, json: async () => ({ final_report: 'old report' }) });
  await new Promise((done) => setImmediate(done));
  assert.equal(rendered.length, 0);
  assert.equal(context._completionHandled, false);
  pending[1]({ ok: true, json: async () => ({ final_report: 'new report' }) });
  await new Promise((done) => setImmediate(done));
  assert.equal(rendered.length, 1);
  assert.equal(rendered[0].final_report, 'new report');
});

test('report retries are bounded and a user can retry after recovery', async () => {
  const { context, rendered, errors, timers, retryButton } = pollingHarness(0);
  let calls = 0;
  context.fetch = async () => { calls++; throw new Error('offline'); };
  context.handlePollStatus({ status: 'completed', progress: {} });
  await new Promise((done) => setImmediate(done));
  for (let attempt = 0; attempt < 2; attempt++) {
    const retry = timers.find((timer) => timer.active && timer.ms === 2000);
    assert.ok(retry);
    retry.active = false;
    await retry.fn();
  }
  assert.equal(calls, 3);
  assert.equal(rendered.length, 0);
  assert.equal(retryButton.hidden, false);
  assert.match(errors.at(-1), /重新加载/);
  assert.equal(timers.filter((timer) => timer.active && timer.ms === 2000).length, 0);
  context.fetch = async () => ({ ok: true, json: async () => ({ final_report: 'available again' }) });
  await retryButton.listeners.click();
  assert.equal(rendered[0].final_report, 'available again');
  assert.equal(retryButton.hidden, true);
});

test('a result request that never responds times out and can be retried', async () => {
  const { context, timers } = pollingHarness(0);
  context.fetch = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('aborted')));
  });
  context.handlePollStatus({ status: 'completed', progress: {} });
  const timeout = timers.find((timer) => timer.active && timer.ms === 15000);
  assert.ok(timeout, 'a stalled report request must have a deadline');
  timeout.fn();
  await new Promise((done) => setImmediate(done));
  assert.equal(context._completionHandled, false);
  assert.ok(timers.some((timer) => timer.active && timer.ms === 2000));
});

function navigationHarness() {
  const harness = pollingHarness(0);
  const { context, rendered } = harness;
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  Object.assign(context, {
    currentResult: null, currentMarketFrequency: 'd', seconds: 0,
    heroSection: { style: {} }, historySection: { style: {} },
    analysisSection: { classList: { add() {} } },
    setLandingVisible() {}, loadWorkbenchMarket() {}, updateTimer() {}, setInterval() {},
    pollAnalysisStatus: async () => context.pollOnceNow(),
    goToReport: () => rendered.push(context.currentResult),
  });
  context.workbench.reset = () => {};
  context.window.scrollTo = () => {};
  const resume = html.indexOf('    async function resumeAnalysis(');
  vm.runInContext(html.slice(resume, html.indexOf('    // Demo mode flag', resume)), context);
  const poll = html.indexOf('    async function pollOnceNow()');
  vm.runInContext(html.slice(poll, html.indexOf('    function startFallbackPolling()', poll)), context);
  return harness;
}

test('opening failed synthesis restores partials without fetching a failed final report', async () => {
  const { context, rendered, errors } = navigationHarness();
  const requests = [];
  const partials = [];
  context.workbench.updatePartialResults = (data) => partials.push(data);
  context.fetch = async (url) => {
    requests.push(url);
    return { ok: true, json: async () => url.endsWith('/partial')
      ? { results: { fundamental_analysis: 'saved analysis' } }
      : { status: 'error', error: 'summary truncated', progress: { summary: 'failed' } } };
  };
  await context.viewCompletedReport('failed');
  assert.equal(partials[0].fundamental_analysis, 'saved analysis');
  assert.equal(errors.at(-1), 'summary truncated');
  assert.equal(rendered.length, 0);
  assert.equal(requests.some((url) => url.includes('/result/')), false);
});

test('out-of-order historical report responses cannot switch back to the previous session', async () => {
  const { context, rendered } = navigationHarness();
  const pendingA = [];
  context.fetch = (url) => url.endsWith('/A') ? new Promise((resolve) => pendingA.push(resolve))
    : Promise.resolve({ ok: true, json: async () => ({ final_report: 'B', status: 'completed', progress: {} }) });
  const requestA = context.viewCompletedReport('A');
  await context.viewCompletedReport('B');
  assert.equal(context.currentAnalysisId, 'B');
  for (const resolve of pendingA) resolve({ ok: true, json: async () => ({ final_report: 'A', status: 'completed', progress: {} }) });
  await requestA;
  assert.equal(context.currentAnalysisId, 'B');
  assert.deepEqual(rendered.map((report) => report.final_report), ['B']);
});

test('a late status response for an old session cannot start retrieval for the new session', async () => {
  const { context, rendered } = navigationHarness();
  const requests = [];
  let resolveStatus;
  context.currentAnalysisId = 'A';
  context.fetch = (url) => {
    requests.push(url);
    if (url.endsWith('/status/A')) return new Promise((resolve) => { resolveStatus = resolve; });
    return Promise.resolve({ ok: true, json: async () => ({ final_report: 'premature B' }) });
  };
  const pending = context.pollOnceNow();
  context.currentAnalysisId = 'B';
  context._analysisViewVersion++;
  resolveStatus({ ok: true, json: async () => ({ status: 'completed', progress: {} }) });
  await pending;
  await new Promise((done) => setImmediate(done));
  assert.deepEqual(requests, ['/api/status/A']);
  assert.equal(rendered.length, 0);
});

test('a late resume response cannot replace the current stock or restart its timers', async () => {
  const { context } = navigationHarness();
  const polled = [];
  context.pollAnalysisStatus = () => polled.push(context.currentAnalysisId);
  let resolveA;
  context.fetch = (url) => url.endsWith('/A') ? new Promise((resolve) => { resolveA = resolve; })
    : Promise.resolve({ ok: true, json: async () => ({ status: 'running', progress: {}, stock_code: 'sz.000001' }) });
  const requestA = context.resumeAnalysis('A', 'A');
  await context.resumeAnalysis('B', 'B');
  resolveA({ ok: true, json: async () => ({ status: 'running', progress: {}, stock_code: 'sh.600519' }) });
  await requestA;
  assert.equal(context.currentMarketCode, 'sz.000001');
  assert.deepEqual(polled, ['B']);
});

test('a late analysis-start response cannot activate an obsolete query', async () => {
  const { context } = navigationHarness();
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  const start = html.indexOf('    async function startRealAnalysis(');
  vm.runInContext(html.slice(start, html.indexOf('    async function loadWorkbenchMarket', start)), context);
  const polled = [];
  context.pollAnalysisStatus = () => polled.push(context.currentAnalysisId);
  let resolveA;
  context.fetch = (_url, options) => JSON.parse(options.body).query === 'A'
    ? new Promise((resolve) => { resolveA = resolve; })
    : Promise.resolve({ ok: true, json: async () => ({ analysis_id: 'B' }) });
  const requestA = context.startRealAnalysis('A');
  context._analysisViewVersion++;
  await context.startRealAnalysis('B');
  resolveA({ ok: true, json: async () => ({ analysis_id: 'A' }) });
  await requestA;
  assert.equal(context.currentAnalysisId, 'B');
  assert.deepEqual(polled, ['B']);
});

test('successful report recovery clears the actual workbench error phase and status', async () => {
  const { context, timers } = pollingHarness(0);
  const status = { textContent: '' };
  const stockTitle = { textContent: '正在加载历史报告' };
  const root = {
    dataset: {}, querySelector: (selector) => selector === '#statusText' ? status
      : selector === '#analyzingStock' ? stockTitle : null,
    querySelectorAll: () => [], ownerDocument: { defaultView: null },
  };
  context.workbench = createController(root);
  context.displayResults = (result) => context.workbench.renderReport(result);
  let calls = 0;
  context.fetch = async () => {
    if (++calls === 1) throw new Error('temporary');
    return { ok: true, json: async () => ({ final_report: 'ready', company_name: '恢复标的' }) };
  };
  context.handlePollStatus({ status: 'completed', progress: {} });
  await new Promise((done) => setImmediate(done));
  assert.equal(root.dataset.phase, 'error');
  await timers.find((timer) => timer.active && timer.ms === 2000).fn();
  assert.equal(root.dataset.phase, 'completed');
  assert.equal(status.textContent, '研究报告已完成');
  assert.equal(stockTitle.textContent, '恢复标的');
});

async function homepageMarketHarness(response) {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  const start = html.indexOf('    function initMarketChart()');
  const elements = Object.fromEntries([
    'marketChart', 'marketSection', 'marketIndexChange', 'marketTradeDateLabel', 'marketDataStatus', 'marketHistoryLoading', 'marketSelection', 'marketYearLabels', 'marketMAControls',
  ].map((id) => [id, {
    style: {}, textContent: '', hidden: id === 'marketHistoryLoading' || id === 'marketSelection', clientWidth: 640, clientHeight: 400, children: [], replaceChildren(...items) { this.children = items; },
    listeners: {}, addEventListener(type, fn, options) { this.listeners[type + (options && options.capture ? ':capture' : '')] = fn; }, contains() { return false; },
  }]));
  const rendered = { candles: [], volume: [] };
  const documentListeners = {};
  const maButtons = [5, 10, 20].map(period => ({ dataset: { period: String(period) }, attributes: { 'aria-pressed': 'true' }, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; }, getAttribute(name) { return this.attributes[name]; }, setAttribute(name, value) { this.attributes[name] = value; } }));
  const periodButtons = ['day', 'week', 'month'].map(period => ({ dataset: { period }, attributes: { 'aria-pressed': String(period === 'day') }, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; }, getAttribute(name) { return this.attributes[name]; }, setAttribute(name, value) { this.attributes[name] = value; } }));
  rendered.ma = {};
  let rangeHandler, clickHandler;
  const scale = { fitContent() {}, subscribeVisibleLogicalRangeChange(fn) { rangeHandler = fn; }, getVisibleLogicalRange() { return rendered.range; }, setVisibleLogicalRange(range) { rendered.range = range; }, timeToCoordinate() { return 200; }, height() { return 26; } };
  const chart = {
    addCandlestickSeries: () => ({ setData: (rows) => { rendered.candles = rows; }, applyOptions() {} }),
    addHistogramSeries: () => ({ setData: (rows) => { rendered.volume = rows; } }),
    addLineSeries: (options) => { const series = { options, data: [], setData(rows) { this.data = rows; }, applyOptions(next) { Object.assign(this.options, next); } }; rendered.ma[Object.keys(rendered.ma).length === 0 ? 5 : Object.keys(rendered.ma).length === 1 ? 10 : 20] = series; return series; },
    priceScale: () => ({ applyOptions() {} }),
    timeScale: () => scale, applyOptions() {}, subscribeClick(fn) { clickHandler = fn; },
  };
  const context = vm.createContext({
    API_BASE: '/api', console: { warn() {} },
    document: { getElementById: (id) => elements[id], querySelectorAll: (selector) => selector === '[data-market-period]' ? periodButtons : maButtons, addEventListener(type, fn) { documentListeners[type] = fn; }, createElement() { return { style: {}, textContent: '' }; } },
    window: { matchMedia: () => ({ matches: true }) },
    LightweightCharts: { createChart: (_, options) => { rendered.chartOptions = options; return chart; }, CrosshairMode: { Normal: 0 } },
    ResizeObserver: class { observe() {} },
    fetch: async (url) => {
      if (typeof response === 'function') return response(url);
      if (response instanceof Error) throw response;
      return response;
    },
  });
  vm.runInContext(html.slice(start, html.indexOf('    // CTA 按钮', start)), context);
  context.initMarketChart();
  await new Promise((resolve) => setImmediate(resolve));
  return { elements, rendered, maButtons, periodButtons, documentListeners, changeRange: (range) => { rendered.range = range; rangeHandler(range); }, click: (time) => clickHandler({ time }) };
}

test('switching daily, weekly and monthly candles aggregates OHLC and volume by Shanghai calendar', async () => {
  const row = (date, open, high, low, close, volume) => ({ time: Date.parse(date + 'T00:00:00+08:00') / 1000, open, high, low, close, volume });
  const rows = [row('2026-01-02', 10, 12, 9, 11, 10), row('2026-01-05', 11, 15, 10, 14, 20), row('2026-01-06', 14, 16, 12, 13, 30), row('2026-01-12', 13, 20, 11, 19, 40), row('2026-02-02', 19, 22, 18, 21, 50), row('2026-02-03', 21, 23, 20, 22, 60)];
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: rows }) });
  harness.periodButtons[1].listeners.click();
  assert.equal(harness.periodButtons[1].getAttribute('aria-pressed'), 'true');
  assert.equal(harness.periodButtons[0].getAttribute('aria-pressed'), 'false');
  const week = harness.rendered.candles.find(item => item.time === rows[1].time);
  assert.deepEqual({ open: week.open, high: week.high, low: week.low, close: week.close }, { open: 11, high: 16, low: 10, close: 13 });
  assert.equal(harness.rendered.volume.find(item => item.time === rows[1].time).value, 50);
  harness.periodButtons[2].listeners.click();
  const month = harness.rendered.candles.find(item => item.time === rows[4].time);
  assert.deepEqual({ open: month.open, high: month.high, low: month.low, close: month.close }, { open: 19, high: 23, low: 18, close: 22 });
  assert.equal(harness.rendered.volume.find(item => item.time === rows[4].time).value, 110);
  harness.periodButtons[0].listeners.click();
  assert.equal(harness.rendered.candles.length, rows.length);
});

test('changing periods while older history is loading retains the last selected period', async () => {
  const row = (date, close) => ({ time: Date.parse(date + 'T00:00:00+08:00') / 1000, open: close, high: close, low: close, close, volume: 10 });
  const recent = [row('2026-01-05', 10), row('2026-01-06', 11), row('2026-02-02', 12), row('2026-02-03', 13)];
  let resolveHistory;
  let calls = 0;
  const harness = await homepageMarketHarness(async () => {
    if (++calls === 1) return { ok: true, json: async () => ({ ok: true, data: recent }) };
    return new Promise(resolve => { resolveHistory = resolve; });
  });
  harness.periodButtons[1].listeners.click();
  harness.periodButtons[2].listeners.click();
  resolveHistory({ ok: true, json: async () => ({ ok: true, data: [row('2025-12-01', 9), ...recent] }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.periodButtons[2].getAttribute('aria-pressed'), 'true');
  assert.equal(harness.rendered.candles.length, 2);
  assert.equal(harness.rendered.candles[1].close, 13);
  assert.equal(harness.rendered.volume[1].value, 20);
});

test('using a moving average control activates chart wheel zoom even over the controls', async () => {
  const rows = Array.from({ length: 120 }, (_, i) => ({ time: i + 1, open: i + 1, high: i + 1, low: i + 1, close: i + 1, volume: 1 }));
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: rows }) });
  harness.rendered.range = { from: 30, to: 100 };
  harness.maButtons[0].listeners.click();
  let prevented = false;
  const event = { deltaY: 100, deltaX: 0, deltaMode: 0, preventDefault() { prevented = true; }, stopPropagation() {} };
  harness.elements.marketMAControls.listeners.wheel(event);
  assert(prevented);
  assert(harness.rendered.range.from < 30);
  assert.equal(harness.rendered.range.to, 100);
  harness.documentListeners.pointerdown({ target: {} });
  prevented = false;
  harness.elements.marketMAControls.listeners.wheel(event);
  assert.equal(prevented, false);
});

test('a wheel gesture started outside the chart keeps scrolling the page when it enters the chart', async () => {
  const rows = Array.from({ length: 120 }, (_, i) => ({ time: i + 1, open: i + 1, high: i + 1, low: i + 1, close: i + 1, volume: 1 }));
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: rows }) });
  const chartTarget = {};
  harness.elements.marketChart.contains = target => target === chartTarget;
  harness.rendered.range = { from: 30, to: 100 };
  harness.elements.marketChart.listeners.pointerdown();
  let prevented = false;
  const event = (target, timeStamp) => ({ target, timeStamp, deltaY: 100, deltaX: 0, deltaMode: 0, preventDefault() { prevented = true; }, stopPropagation() {} });
  harness.documentListeners.wheel(event({}, 1000));
  const entering = event(chartTarget, 1050);
  harness.documentListeners.wheel(entering);
  harness.elements.marketChart.listeners['wheel:capture'](entering);
  harness.elements.marketChart.listeners.wheel(entering);
  assert.equal(prevented, false);
  assert.equal(harness.rendered.range.from, 30);
  const fresh = event(chartTarget, 1400);
  harness.documentListeners.wheel(fresh);
  harness.elements.marketChart.listeners['wheel:capture'](fresh);
  assert.equal(prevented, true);
  assert(harness.rendered.range.from < 30);
});

test('volume colors reflect the change versus previous close, including flat and missing previous closes', async () => {
  const closes = [100, 110, 105, 105];
  const rows = closes.map((close, i) => ({ time: i + 1, open: i === 1 ? 120 : 90, high: 120, low: 90, close, volume: 100 + i }));
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: rows }) });
  const colors = Array.from(harness.rendered.volume, item => item.color);
  assert.equal(colors[0], colors[3]);
  assert.notEqual(colors[1], colors[2]);
  assert.notEqual(colors[1], colors[0]);
  assert.notEqual(colors[2], colors[0]);
  assert.match(colors[1], /176,\s*58,\s*46/);
  assert.match(colors[2], /30,\s*142,\s*90/);
});

test('volume colors update when earlier data supplies the previous close', async () => {
  const row = (time, close) => ({ time, open: close, high: close, low: close, close, volume: 100 });
  let calls = 0;
  const harness = await homepageMarketHarness(async () => ({ ok: true, json: async () => ({ ok: true, data: ++calls === 1 ? [row(2, 110), row(3, 100)] : [row(1, 100), row(2, 110), row(3, 100)] }) }));
  const initial = harness.rendered.volume[0].color;
  harness.changeRange({ from: 0, to: 1 });
  await new Promise(resolve => setImmediate(resolve));
  assert.notEqual(harness.rendered.volume[1].color, initial);
  assert.match(harness.rendered.volume[1].color, /176,\s*58,\s*46/);
});

test('moving averages use complete trading-day windows and each line can be toggled', async () => {
  const rows = Array.from({ length: 20 }, (_, i) => ({ time: i + 1, open: i + 1, high: i + 1, low: i + 1, close: i + 1, volume: 1 }));
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: rows }) });
  assert.equal(harness.rendered.ma[5].data.length, 16);
  assert.equal(harness.rendered.ma[5].data[0].value, 3);
  assert.equal(harness.rendered.ma[10].data[0].value, 5.5);
  assert.equal(harness.rendered.ma[20].data[0].value, 10.5);
  const toggle = harness.maButtons[0];
  toggle.listeners.click();
  assert.equal(toggle.getAttribute('aria-pressed'), 'false');
  assert.equal(harness.rendered.ma[5].options.visible, false);
  assert.notEqual(harness.rendered.ma[10].options.visible, false);
  toggle.listeners.click();
  assert.equal(toggle.getAttribute('aria-pressed'), 'true');
  assert.equal(harness.rendered.ma[5].options.visible, true);
});

test('loading older candles recalculates moving averages without changing visibility', async () => {
  const rows = Array.from({ length: 25 }, (_, i) => ({ time: i + 1, open: i + 1, high: i + 1, low: i + 1, close: i + 1, volume: 1 }));
  let calls = 0;
  const harness = await homepageMarketHarness(async () => ({ ok: true, json: async () => ({ ok: true, data: ++calls === 1 ? rows.slice(5) : rows }) }));
  harness.maButtons[2].listeners.click();
  assert.equal(harness.rendered.ma[20].data[0].value, 15.5);
  harness.changeRange({ from: 0, to: 19 });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.rendered.ma[20].data[0].time, 20);
  assert.equal(harness.rendered.ma[20].data[0].value, 10.5);
  assert.equal(harness.rendered.ma[20].options.visible, false);
});

test('market timeline distinguishes month and year labels from days', async () => {
  const row = { time: 1792627200, open: 1, high: 2, low: 1, close: 2, volume: 1 };
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: [row] }) });
  const format = harness.rendered.chartOptions.timeScale.tickMarkFormatter;
  assert.equal(format(row.time, 0), '');
  assert.equal(format(row.time, 1), '10月');
  assert.equal(format(row.time, 2), null);
});

test('visible year boundary is displayed in a separate label without brackets', async () => {
  const row = time => ({ time, open: 1, high: 2, low: 1, close: 2, volume: 1 });
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: [row(1767110400), row(1767283200)] }) });
  harness.changeRange({ from: 0, to: 1 });
  assert.equal(harness.elements.marketYearLabels.children[0].textContent, '2026年');
});

test('clicking a candle shows its daily change versus the previous close', async () => {
  const rows = [
    { time: 1792627200, open: 100, high: 103, low: 98, close: 100, volume: 1 },
    { time: 1792713600, open: 104, high: 110, low: 100, close: 105, volume: 1 },
    { time: 1792800000, open: 105, high: 106, low: 99, close: 102, volume: 1 },
  ];
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: rows }) });
  harness.click(rows[1].time);
  assert.equal(harness.elements.marketSelection.hidden, false);
  assert.match(harness.elements.marketSelection.textContent, /2026-10-23.*\+5\.00%/);
  harness.click(rows[2].time);
  assert.match(harness.elements.marketSelection.textContent, /-2\.86%/);
  harness.click(rows[0].time);
  assert.match(harness.elements.marketSelection.textContent, /涨跌幅暂缺/);
});

test('focused wheel zoom out keeps the right edge fixed and expands toward earlier dates', async () => {
  const row = (time) => ({ time, open: 1, high: 2, low: 1, close: 2, volume: 1 });
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: [row(1), row(2)] }) });
  harness.rendered.range = { from: 20, to: 100 };
  harness.elements.marketChart.listeners.pointerdown();
  let prevented = false, stopped = false;
  harness.elements.marketChart.listeners['wheel:capture']({ deltaY: 100, deltaX: 0, deltaMode: 0, preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } });
  assert.equal(harness.rendered.range.to, 100);
  assert(harness.rendered.range.from < 20);
  assert(prevented && stopped);
});

test('panning into the future is clamped while panning toward history remains possible', async () => {
  const row = (time) => ({ time, open: 1, high: 2, low: 1, close: 2, volume: 1 });
  const harness = await homepageMarketHarness({ ok: true, json: async () => ({ ok: true, data: Array.from({ length: 100 }, (_, i) => row(i + 1)) }) });
  harness.changeRange({ from: 70, to: 120 });
  assert.equal(harness.rendered.range.to, 99.5);
  assert.equal(harness.rendered.range.from, 49.5);
  harness.changeRange({ from: 30, to: 80 });
  assert.equal(harness.rendered.range.to, 80);
  assert.equal(harness.rendered.range.from, 30);
});

test('zooming out near the oldest candle loads older history and preserves the visible dates', async () => {
  const row = (time) => ({ time, open: 1, high: 2, low: 1, close: 2, volume: 1 });
  const calls = [];
  const harness = await homepageMarketHarness(async (url) => {
    calls.push(url);
    return { ok: true, json: async () => ({ ok: true, data: calls.length === 1 ? [row(3), row(4)] : [row(1), row(2), row(3), row(4)] }) };
  });
  harness.changeRange({ from: -2, to: 2 });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls.length, 2);
  assert.deepEqual(Array.from(harness.rendered.candles, row => row.time), [1, 2, 3, 4]);
  assert.equal(harness.rendered.range.from, -0.5);
  assert.equal(harness.rendered.range.to, 3.5);
});

test('older history requests do not overlap and stop when the provider has no earlier data', async () => {
  const row = (time) => ({ time, open: 1, high: 2, low: 1, close: 2, volume: 1 });
  let resolveHistory;
  let calls = 0;
  const harness = await homepageMarketHarness(async () => {
    calls++;
    if (calls === 1) return { ok: true, json: async () => ({ ok: true, data: [row(3), row(4)] }) };
    return new Promise(resolve => { resolveHistory = resolve; });
  });
  harness.changeRange({ from: -1, to: 2 });
  harness.changeRange({ from: -2, to: 2 });
  assert.equal(calls, 2);
  assert.equal(harness.elements.marketHistoryLoading.hidden, false);
  resolveHistory({ ok: true, json: async () => ({ ok: true, data: [row(3), row(4)] }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.elements.marketHistoryLoading.hidden, true);
  harness.changeRange({ from: -3, to: 2 });
  assert.equal(calls, 2);
  assert.equal(harness.rendered.range.from, -0.5);
  assert.equal(harness.rendered.range.to, 1.5);
});

test('a failed older history request keeps current candles and retries on the next interaction', async () => {
  const row = (time) => ({ time, open: 1, high: 2, low: 1, close: 2, volume: 1 });
  let calls = 0;
  const harness = await homepageMarketHarness(async () => {
    calls++;
    if (calls === 2) throw new Error('offline');
    return { ok: true, json: async () => ({ ok: true, data: calls === 1 ? [row(3), row(4)] : [row(1), row(2), row(3), row(4)] }) };
  });
  harness.changeRange({ from: -1, to: 2 });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2);
  assert.match(harness.elements.marketDataStatus.textContent, /无法加载/);
  assert.equal(harness.elements.marketHistoryLoading.hidden, true);
  assert.equal(harness.rendered.candles.length, 2);
  harness.changeRange({ from: -1, to: 2 });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 3);
  assert.equal(harness.rendered.candles.length, 4);
});

test('homepage market failures show an unavailable state without fabricated candles', async () => {
  for (const response of [
    new Error('network unavailable'),
    { ok: false, status: 503 },
    { ok: true, json: async () => ({ ok: true, data: [] }) },
    { ok: true, json: async () => ({ ok: false, error: 'provider unavailable' }) },
  ]) {
    const { elements, rendered } = await homepageMarketHarness(response);
    assert.equal(rendered.candles.length, 0);
    assert.equal(rendered.volume.length, 0);
    assert.match(elements.marketDataStatus.textContent, /不可用/);
    assert.equal(elements.marketChart.hidden, true);
  }
});

test('homepage market quote derives the change and trade date from actual returned candles', async () => {
  const { elements, rendered } = await homepageMarketHarness({
    ok: true,
    json: async () => ({ ok: true, data: [
      { time: 1792627200, open: 3000, high: 3030, low: 2980, close: 3000, volume: 100 },
      { time: 1792713600, open: 3000, high: 3090, low: 2990, close: 3060, volume: 120 },
    ] }),
  });
  assert.equal(rendered.candles.length, 2);
  assert.equal(rendered.candles[1].close, 3060);
  assert.equal(elements.marketIndexChange.textContent, '沪指 +2.00%');
  assert.match(elements.marketTradeDateLabel.textContent, /2026-10-23/);
  assert.match(elements.marketDataStatus.textContent, /收盘/);
  assert.equal(elements.marketChart.hidden, false);
});
