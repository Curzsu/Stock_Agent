(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FinexWorkbench = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const AGENTS = ['fundamental', 'technical', 'value', 'news', 'summary'];

  function normalizeAgentDetails(input = {}) {
    return Object.fromEntries(AGENTS.map((key) => [key, {
      status: 'waiting',
      summary: '',
      error: null,
      result_available: false,
      execution_time_ms: null,
      ...(input[key] || {}),
    }]));
  }

  function derivePhase(payload = {}) {
    if (payload.status === 'completed') return 'completed';
    if (payload.status === 'degraded') return 'degraded';
    if (payload.status === 'error') return 'error';
    const values = payload.progress || {};
    if (values.summary === 'running') return 'summarizing';
    if (AGENTS.some((key) => values[key] === 'completed')) return 'partial';
    return payload.status === 'running' ? 'running' : 'starting';
  }

  function buildMarketSeries(payload = {}) {
    const candles = Array.isArray(payload.candles) ? payload.candles : [];
    return {
      candles: candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })),
      volume: candles.map(({ time, volume, close, open }) => ({
        time,
        value: Number(volume || 0),
        color: close >= open ? '#557a66' : '#a0473e',
      })),
      ma5: candles
        .filter((row) => row.ma5 != null)
        .map(({ time, ma5 }) => ({ time, value: ma5 })),
      ma20: candles
        .filter((row) => row.ma20 != null)
        .map(({ time, ma20 }) => ({ time, value: ma20 })),
    };
  }

  function completedResultKeys(progress = {}, seen = new Set()) {
    return AGENTS.filter(
      (key) => key !== 'summary' && progress[key] === 'completed' && !seen.has(key),
    );
  }

  return {
    AGENTS,
    normalizeAgentDetails,
    derivePhase,
    buildMarketSeries,
    completedResultKeys,
  };
});
