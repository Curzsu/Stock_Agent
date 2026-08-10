const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  derivePhase,
  normalizeAgentDetails,
  buildMarketSeries,
  completedResultKeys,
  createController,
  nextRequests,
  resolveChartSize,
  stripLeadingMarkdownHeading,
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
});

test('normalizeAgentDetails supplies safe waiting defaults', () => {
  const details = normalizeAgentDetails({ fundamental: { status: 'completed', summary: '稳健' } });
  assert.equal(details.fundamental.summary, '稳健');
  assert.equal(details.news.status, 'waiting');
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

test('worker failures keep polling through a foreground fallback', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  assert.match(html, /function startFallbackPolling\(\)\s*\{\s*stopBackgroundPolling\(false\)/s);
  assert.match(html, /_fallbackPollTimer\s*=\s*setInterval\(pollOnceNow,\s*2000\)/);
  assert.match(html, /_statusWorker\.onerror\s*=\s*startFallbackPolling/);
});

test('initial status polling does not restart after a terminal response', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  assert.match(html, /await pollOnceNow\(\);\s*if \(_pollDeadline > 0 && !_completionHandled\) startBackgroundPolling\(\);/s);
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
