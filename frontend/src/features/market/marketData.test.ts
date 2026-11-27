import { expect, it } from 'vitest';
import { aggregateIndex, indexSeries, readIndex, readStock, stockSeries } from './marketData';
import { constrainRange, zoomFromRight } from './chartRange';

const row = (time: number, open: number, close: number, volume: number) => ({
  time, open, close, high: Math.max(open, close), low: Math.min(open, close), volume,
});
const utc = (date: string) => Date.parse(date) / 1000;

it('aggregates index OHLC and volume by the Shanghai trading week and month', () => {
  const rows = readIndex({ ok: true, data: [
    row(utc('2026-08-30T17:00Z'), 100, 105, 17),
    row(utc('2026-08-31T17:00Z'), 105, 103, 21),
    row(utc('2026-09-06T17:00Z'), 103, 107, 28),
  ] });
  expect(aggregateIndex(rows, 'w', true)[0]).toEqual({
    time: '2026-08-31', open: 100, high: 105, low: 100, close: 103, volume: 38,
  });
  expect(aggregateIndex(rows, 'm', true).map(({ time, close }) => [time, close])).toEqual([
    ['2026-08-31', 105], ['2026-09-01', 107],
  ]);
  expect(aggregateIndex(rows, 'w', false)).toHaveLength(1);
});

it('uses the previous index close for volume color and real daily windows for averages', () => {
  const rows = readIndex({ ok: true, data: [
    row(utc('2026-09-01'), 10, 11, 25),
    row(utc('2026-09-02'), 12, 11, 22),
    row(utc('2026-09-03'), 12, 13, 28),
    row(utc('2026-09-04'), 14, 15, 31),
    row(utc('2026-09-07'), 15, 15, 30),
  ] });
  const series = indexSeries(rows);
  expect(series.volume.slice(0, 3).map(({ color }) => color)).toEqual([
    'rgba(120, 120, 120, 0.35)', 'rgba(120, 120, 120, 0.35)', 'rgba(176, 58, 46, 0.38)',
  ]);
  expect(series.averages[5]).toEqual([{ time: '2026-09-07', value: 13 }]);
  expect(series.averages[10]).toEqual([]);
});

it('uses the individual-stock candles, quote and available moving averages', () => {
  const market = readStock({
    ok: true, code: 'sh.600519', latest_trade_date: '2026-09-02',
    candles: [
      { ...row(0, 120, 130, 25), time: '2026-09-01', ma5: null },
      { ...row(0, 130, 125, 28), time: '2026-09-02', ma5: 126 },
    ],
    quote: { close: 125, pct_change: -3.85 },
  });
  const series = stockSeries(market.candles);
  expect(market.quote.close).toBe(125);
  expect(series.averages[5]).toEqual([{ time: '2026-09-02', value: 126 }]);
  expect(series.volume[1]).toEqual({ time: '2026-09-02', value: 28, color: '#a0473e' });
});

it('reports provider failures and empty candles without fabricating data', () => {
  expect(() => readIndex({ ok: false, error: '指数查询超时' })).toThrow('指数查询超时');
  expect(() => readStock({ ok: false, error: '个股行情暂不可用' })).toThrow('个股行情暂不可用');
  expect(() => readStock({ ok: true, candles: [] })).toThrow('未获取到个股行情数据');
});

it('keeps the latest edge fixed during wheel zoom and bounds panning to real history', () => {
  expect(constrainRange({ from: 80, to: 110 }, 100)).toEqual({ from: 69.5, to: 99.5 });
  expect(constrainRange({ from: -20, to: 10 }, 100)).toEqual({ from: -0.5, to: 29.5 });
  const zoomed = zoomFromRight({ from: 70, to: 99.5 }, 180, 100);
  expect(zoomed.to).toBe(99.5);
  expect(zoomed.from).toBeLessThan(70);
});
