const test = require('node:test');
const assert = require('node:assert/strict');
const { createController } = require('../../frontend/workbench.js');

function harness() {
  function element() {
    return {
      listeners: new Map(), children: [], clientWidth: 640, clientHeight: 430,
      addEventListener(type, handler, options) {
        const key = `${type}:${!!options?.capture}`;
        if (!this.listeners.has(key)) this.listeners.set(key, new Set());
        this.listeners.get(key).add(handler);
      },
      removeEventListener(type, handler, options) {
        this.listeners.get(`${type}:${!!options?.capture}`)?.delete(handler);
      },
      emit(type, event = {}, capture = false) {
        for (const handler of this.listeners.get(`${type}:${capture}`) || []) handler(event);
      },
      contains(target) { return target === this || this.children.includes(target); },
      replaceChildren(...children) { this.children = children; },
      append(...children) { this.children.push(...children); },
      setAttribute() {},
    };
  }
  const container = element(), controls = element(), document = element();
  document.createElement = element;
  document.defaultView = null;
  const charts = [];
  const library = { createChart(_container, options) {
    const rangeHandlers = new Set();
    const chart = {
      options, range: null, removed: false,
      applyOptions(next) { this.options = { ...this.options, ...next }; },
      remove() { this.removed = true; },
      addCandlestickSeries: series, addHistogramSeries: series, addLineSeries: series,
      timeScale() { return scale; },
    };
    function series() { return { setData() {}, priceScale: () => ({ applyOptions() {} }) }; }
    const scale = {
      fitContent() { this.setVisibleLogicalRange({ from: -0.5, to: 119.5 }); },
      getVisibleLogicalRange: () => chart.range,
      setVisibleLogicalRange(range) {
        chart.range = range;
        for (const handler of rangeHandlers) handler(range);
      },
      subscribeVisibleLogicalRangeChange: handler => rangeHandlers.add(handler),
      unsubscribeVisibleLogicalRangeChange: handler => rangeHandlers.delete(handler),
    };
    charts.push(chart);
    return chart;
  } };
  const controller = createController({
    ownerDocument: document,
    querySelector: selector => selector === '#workbenchMarketChart' ? container
      : selector === '.market-periods' ? controls : null,
    querySelectorAll: () => [],
  }, { LightweightCharts: library });
  const payload = { ok: true, candles: Array.from({ length: 120 }, (_, i) => ({
    time: i + 1, open: 10, high: 12, low: 9, close: 11, volume: 100,
  })) };
  controller.renderMarket(payload);
  function wheel(target, timeStamp, deltaY = 100, extra = {}) {
    const event = {
      target, timeStamp, deltaY, deltaX: 0, deltaMode: 0, prevented: false, stopped: false,
      preventDefault() { this.prevented = true; },
      stopPropagation() { this.stopped = true; }, ...extra,
    };
    document.emit('wheel', event, true);
    target.emit?.('wheel', event, true);
    if (!event.stopped) target.emit?.('wheel', event);
    return event;
  }
  function focus(target = container) {
    document.emit('pointerdown', { target });
    target.emit('pointerdown', { target });
  }
  return { container, controls, document, controller, charts, payload, wheel, focus,
    get chart() { return charts.at(-1); } };
}

test('research chart wheel only captures a gesture after clicking the chart', () => {
  const h = harness();
  h.chart.range = { from: 30, to: 100 };
  assert.equal(h.wheel(h.container, 1000).prevented, false);
  assert.deepEqual(h.chart.range, { from: 30, to: 100 });
  h.focus();
  const zoom = h.wheel(h.container, 1400);
  assert.equal(zoom.prevented, true);
  assert.equal(zoom.stopped, true);
  assert(h.chart.range.from < 30);
  assert.equal(h.chart.range.to, 100);
  h.document.emit('pointerdown', { target: {} });
  assert.equal(h.wheel(h.container, 1800).prevented, false);
  assert.equal(h.chart.options.handleScale.mouseWheel, false);
});

test('research chart lets a page scroll gesture pass through until a new gesture starts', () => {
  const h = harness();
  h.chart.range = { from: 30, to: 100 };
  h.focus();
  h.wheel({}, 1000);
  assert.equal(h.wheel(h.container, 1050).prevented, false);
  assert.deepEqual(h.chart.range, { from: 30, to: 100 });
  assert.equal(h.wheel(h.container, 1400).prevented, true);
  assert(h.chart.range.from < 30);
});

test('research chart clamps future and exhausted history while allowing historical panning', () => {
  const h = harness();
  h.chart.timeScale().setVisibleLogicalRange({ from: 90, to: 140 });
  assert.deepEqual(h.chart.range, { from: 69.5, to: 119.5 });
  h.chart.timeScale().setVisibleLogicalRange({ from: 30, to: 80 });
  assert.deepEqual(h.chart.range, { from: 30, to: 80 });
  h.chart.timeScale().setVisibleLogicalRange({ from: -20, to: 30 });
  assert.deepEqual(h.chart.range, { from: -0.5, to: 49.5 });
  h.chart.timeScale().setVisibleLogicalRange({ from: -200, to: 140 });
  assert.deepEqual(h.chart.range, { from: -0.5, to: 119.5 });
});

test('research period controls focus the chart and zoom with the same fixed right edge', () => {
  const h = harness();
  h.focus(h.controls);
  h.chart.range = { from: 30, to: 100 };
  assert.equal(h.wheel(h.controls, 1000).prevented, true);
  assert(h.chart.range.from < 30);
  assert.equal(h.chart.range.to, 100);
  const before = h.chart.range.from;
  h.wheel(h.controls, 1400, -3, { deltaMode: 1 });
  assert(h.chart.range.from > before);
  assert.equal(h.chart.range.to, 100);
});

test('research chart stops zooming out at the oldest candle without shifting the right edge', () => {
  const h = harness();
  h.chart.range = { from: 0, to: 100 };
  h.focus();
  for (let i = 0; i < 5; i++) h.wheel(h.container, 1000 + i * 300);
  assert.deepEqual(h.chart.range, { from: -0.5, to: 100 });
});

test('research chart recreates and removes interactions without retaining old charts', () => {
  const h = harness();
  h.focus();
  const first = h.chart;
  h.controller.renderMarket(h.payload);
  assert.equal(first.removed, true);
  first.timeScale().setVisibleLogicalRange({ from: 90, to: 140 });
  assert.deepEqual(first.range, { from: 90, to: 140 });
  h.chart.range = { from: 30, to: 100 };
  h.wheel(h.container, 1000);
  assert(h.chart.range.from < 30);
  h.controller.reset('new stock');
  assert.equal(h.chart.removed, true);
  assert.equal(h.wheel(h.container, 1400).prevented, false);
  h.controller.renderMarket(h.payload);
  assert.equal(h.wheel(h.container, 1800).prevented, false);
  h.controller.destroy();
  for (const target of [h.container, h.controls, h.document]) {
    assert.equal([...target.listeners.values()].reduce((sum, handlers) => sum + handlers.size, 0), 0);
  }
});
