import type { CandlestickData, HistogramData, LineData } from 'lightweight-charts';

export type MarketPeriod = 'd' | 'w' | 'm';
export type AveragePeriod = 5 | 10 | 20;
export const AVERAGE_PERIODS = [5, 10, 20] as const;
export type Candle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ma5?: number;
  ma20?: number;
};

export type MarketSeries = {
  candles: CandlestickData<string>[];
  volume: HistogramData<string>[];
  averages: Record<AveragePeriod, LineData<string>[]>;
};

function numberOrUndefined(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function readCandles(source: unknown, toDate: (value: unknown) => string | undefined): Candle[] {
  const candles = new Map<string, Candle>();
  for (const value of Array.isArray(source) ? source : []) {
    const row = record(value);
    const time = toDate(row.time);
    const [open, high, low, close, volume] = [row.open, row.high, row.low, row.close, row.volume]
      .map(numberOrUndefined);
    if (!time || open === undefined || high === undefined || low === undefined || close === undefined || volume === undefined) {
      throw new Error('行情数据格式无效');
    }
    candles.set(time, {
      time, open, high, low, close, volume,
      ...typeof row.ma5 === 'number' && { ma5: numberOrUndefined(row.ma5) },
      ...typeof row.ma20 === 'number' && { ma20: numberOrUndefined(row.ma20) },
    });
  }
  return [...candles.values()].sort((first, second) => first.time.localeCompare(second.time));
}

function providerError(payload: Record<string, unknown>, fallback: string) {
  return new Error(typeof payload.error === 'string' && payload.error ? payload.error : fallback);
}

export function readIndex(value: unknown) {
  const payload = record(value);
  if (payload.ok !== true) throw providerError(payload, '未获取到上证指数行情');
  const candles = readCandles(payload.data, (time) => {
    if (typeof time !== 'number') return;
    const date = new Date((time + 8 * 3600) * 1000);
    if (Number.isFinite(date.getTime())) return date.toISOString().slice(0, 10);
  });
  if (!candles.length) throw providerError(payload, '未获取到上证指数行情');
  return candles;
}

export function readStock(value: unknown) {
  const payload = record(value);
  if (payload.ok !== true) throw providerError(payload, '未获取到个股行情数据');
  const candles = readCandles(payload.candles, (time) =>
    typeof time === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(time) ? time : undefined,
  );
  if (!candles.length) throw providerError(payload, '未获取到个股行情数据');
  const quote = record(payload.quote);
  return {
    candles,
    tradeDate: typeof payload.latest_trade_date === 'string' ? payload.latest_trade_date : candles.at(-1)!.time,
    quote: {
      close: numberOrUndefined(quote.close) ?? candles.at(-1)!.close,
      change: numberOrUndefined(quote.pct_change),
      pe: numberOrUndefined(quote.pe_ttm),
      pb: numberOrUndefined(quote.pb_mrq),
      turnover: numberOrUndefined(quote.turnover),
      volume: numberOrUndefined(quote.volume),
    },
  };
}

function startOfWeek(time: string) {
  const date = new Date(time);
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
  return date.toISOString().slice(0, 10);
}

export function aggregateIndex(rows: Candle[], period: MarketPeriod, exhausted: boolean) {
  if (period === 'd') return rows;
  const groups: Candle[] = [];
  let lastKey: string | undefined;
  for (const row of rows) {
    const key = period === 'm' ? row.time.slice(0, 7) : startOfWeek(row.time);
    const group = groups.at(-1);
    if (!group || lastKey !== key) {
      groups.push({ ...row });
      lastKey = key;
      continue;
    }
    group.high = Math.max(group.high, row.high);
    group.low = Math.min(group.low, row.low);
    group.close = row.close;
    group.volume += row.volume;
  }
  return !exhausted && groups.length > 1 ? groups.slice(1) : groups;
}

function candlePoints(rows: Candle[]) {
  return rows.map(({ time, open, high, low, close }) => ({ time, open, high, low, close }));
}

function movingAverage(rows: Candle[], period: AveragePeriod) {
  const values: LineData<string>[] = [];
  let sum = 0;
  rows.forEach(({ time, close }, index) => {
    sum += close;
    if (index >= period) sum -= rows[index - period].close;
    if (index + 1 >= period) values.push({ time, value: sum / period });
  });
  return values;
}

export function indexSeries(rows: Candle[]): MarketSeries {
  return {
    candles: candlePoints(rows),
    volume: rows.map(({ time, volume, close }, index) => {
      const previous = rows[index - 1]?.close;
      const color = !previous || previous < 0 || close === previous
        ? 'rgba(120, 120, 120, 0.35)'
        : close > previous ? 'rgba(176, 58, 46, 0.38)' : 'rgba(30, 142, 90, 0.38)';
      return { time, value: volume, color };
    }),
    averages: { 5: movingAverage(rows, 5), 10: movingAverage(rows, 10), 20: movingAverage(rows, 20) },
  };
}

export function stockSeries(rows: Candle[]): MarketSeries {
  const average = (key: 'ma5' | 'ma20') => rows.flatMap((row) =>
    row[key] === undefined ? [] : [{ time: row.time, value: row[key] }],
  );
  return {
    candles: candlePoints(rows),
    volume: rows.map(({ time, volume, close, open }) => ({
      time, value: volume, color: close >= open ? '#557a66' : '#a0473e',
    })),
    averages: { 5: average('ma5'), 10: [], 20: average('ma20') },
  };
}
