const test = require('node:test');
const assert = require('node:assert/strict');
const {
  derivePhase,
  normalizeAgentDetails,
  buildMarketSeries,
  completedResultKeys,
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
