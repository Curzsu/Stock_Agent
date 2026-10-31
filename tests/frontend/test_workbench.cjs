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
} = require('../../frontend/workbench.js');

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

test('fundamental bars have a definite height for percentage bars', () => {
  const css = fs.readFileSync(path.join(__dirname, '../../frontend/workbench.css'), 'utf8');
  assert.match(css, /\.micro-bars\s*\{[^}]*height:\s*80px/s);
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
    'marketChart', 'marketSection', 'marketIndexChange', 'marketTradeDateLabel', 'marketDataStatus',
  ].map((id) => [id, {
    style: {}, textContent: '', hidden: false, clientWidth: 640, clientHeight: 400,
    addEventListener() {}, contains() { return false; },
  }]));
  const rendered = { candles: [], volume: [] };
  const chart = {
    addCandlestickSeries: () => ({ setData: (rows) => { rendered.candles = rows; }, applyOptions() {} }),
    addHistogramSeries: () => ({ setData: (rows) => { rendered.volume = rows; } }),
    priceScale: () => ({ applyOptions() {} }),
    timeScale: () => ({ fitContent() {} }), applyOptions() {},
  };
  const context = vm.createContext({
    API_BASE: '/api', console: { warn() {} },
    document: { getElementById: (id) => elements[id], addEventListener() {} },
    window: { matchMedia: () => ({ matches: true }) },
    LightweightCharts: { createChart: () => chart, CrosshairMode: { Normal: 0 } },
    ResizeObserver: class { observe() {} },
    fetch: async () => {
      if (response instanceof Error) throw response;
      return response;
    },
  });
  vm.runInContext(html.slice(start, html.indexOf('    // CTA 按钮', start)), context);
  context.initMarketChart();
  await new Promise((resolve) => setImmediate(resolve));
  return { elements, rendered };
}

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
