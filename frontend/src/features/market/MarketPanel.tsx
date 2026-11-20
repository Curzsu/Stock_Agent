import { useQuery, useQueryClient } from '@tanstack/react-query';
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { ToggleButton } from '../../shared/ui/ToggleButton';
import { aggregateIndex, AVERAGE_PERIODS, indexSeries, stockSeries, type AveragePeriod, type Candle, type MarketPeriod } from './marketData';
import { indexMarketQuery, stockMarketQuery } from './marketQueries';
import styles from './MarketPanel.module.css';

const MarketChart = lazy(() => import('./MarketChart'));
const periods = [
  ['d', '日线'],
  ['w', '周线'],
  ['m', '月线'],
] as const;
const stockAverages = [5, 20] as const;
const BASE_INDEX_DAYS = 90;
const MAX_INDEX_DAYS = 10_000;
const stockQuoteFormat = new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 2 });

function LoadingChart({ children = '正在加载最近交易日行情…' }: { children?: string }) {
  return <p className={styles.placeholder} role="status">{children}</p>;
}

function PeriodPicker({ value, onChange }: { value: MarketPeriod; onChange: (value: MarketPeriod) => void }) {
  return (
    <div className={styles.controls} role="group" aria-label="K 线周期">
      {periods.map(([period, label]) => (
        <ToggleButton key={period} pressed={period === value} onClick={() => onChange(period)} data-chart-control>
          {label}
        </ToggleButton>
      ))}
    </div>
  );
}

function Change({ value }: { value?: number }) {
  if (value === undefined) return <span>最近交易日收盘</span>;
  return <span data-direction={value >= 0 ? 'up' : 'down'}>{value > 0 ? '+' : ''}{value.toFixed(2)}%</span>;
}

type IndexHistory = { candles: Candle[]; days: number; exhausted: boolean };

function IndexMarket() {
  const client = useQueryClient();
  const query = useQuery(indexMarketQuery(BASE_INDEX_DAYS));
  const [period, setPeriod] = useState<MarketPeriod>('d');
  const [history, setHistory] = useState<IndexHistory>();
  const [visibleAverages, setVisibleAverages] = useState<readonly AveragePeriod[]>(AVERAGE_PERIODS);
  const [olderStatus, setOlderStatus] = useState('');
  const loadingOlder = useRef(false);
  const queuedDays = useRef(0);
  const candles = history?.candles ?? query.data;
  const exhausted = history?.exhausted ?? false;
  const data = useMemo(() => candles && indexSeries(aggregateIndex(candles, period, exhausted)), [candles, period, exhausted]);

  async function loadEarlier(minDays = 0) {
    if (!candles || exhausted) return;
    if (loadingOlder.current) {
      queuedDays.current = Math.max(queuedDays.current, minDays);
      return;
    }
    let current: IndexHistory = { candles, days: history?.days ?? BASE_INDEX_DAYS, exhausted };
    let target = Math.min(MAX_INDEX_DAYS, Math.max(minDays, current.days * 2));
    loadingOlder.current = true;
    setOlderStatus('正在加载更早行情…');
    try {
      while (!current.exhausted && target > current.days) {
        const extended = await client.fetchQuery(indexMarketQuery(target));
        const earlier = extended.filter((row) => row.time < current.candles[0].time);
        current = {
          candles: earlier.length ? [...earlier, ...current.candles] : current.candles,
          days: target,
          exhausted: !earlier.length || target === MAX_INDEX_DAYS,
        };
        setHistory(current);
        target = queuedDays.current;
        queuedDays.current = 0;
      }
      setOlderStatus('');
    } catch {
      setOlderStatus('更早行情暂时无法加载，请稍后再次缩放重试。');
    } finally {
      loadingOlder.current = false;
      queuedDays.current = 0;
    }
  }

  function changePeriod(value: MarketPeriod) {
    setPeriod(value);
    const minimum = value === 'm' ? 1100 : value === 'w' ? 240 : BASE_INDEX_DAYS;
    if (minimum > (history?.days ?? BASE_INDEX_DAYS)) void loadEarlier(minimum);
  }

  if (query.error && !data) return <LoadingChart>{query.error.message}</LoadingChart>;
  if (!candles || !data) return <LoadingChart />;
  const latest = candles.at(-1)!;
  const previous = candles.at(-2);
  return (
    <>
      <div className={styles.toolbar}>
        <div className={styles.quote}>
          <strong>{latest.close.toFixed(2)}</strong>
          <Change value={previous?.close ? (latest.close / previous.close - 1) * 100 : undefined} />
        </div>
        <time dateTime={latest.time}>最新交易日 {latest.time}</time>
      </div>
      <div className={styles.toolbar}>
        <PeriodPicker value={period} onChange={changePeriod} />
        <div className={styles.controls} role="group" aria-label="均线显示设置">
          {AVERAGE_PERIODS.map((window) => (
            <ToggleButton
              key={window}
              pressed={visibleAverages.includes(window)}
              onClick={() => setVisibleAverages((visible) => visible.includes(window)
                ? visible.filter((item) => item !== window) : [...visible, window])}
              data-chart-control
            >
              MA{window}
            </ToggleButton>
          ))}
        </div>
      </div>
      <Suspense fallback={<LoadingChart />}>
        <MarketChart variant="index" label="上证指数历史行情" data={data} period={period} visibleAverages={visibleAverages}
          onReachHistory={() => void loadEarlier()} />
      </Suspense>
      {olderStatus && <p className={styles.footnote} role="status">{olderStatus}</p>}
    </>
  );
}

function StockMarket({ code }: { code: string }) {
  const [period, setPeriod] = useState<MarketPeriod>('d');
  const query = useQuery(stockMarketQuery(code, period, 120));
  const data = useMemo(() => query.data && stockSeries(query.data.candles), [query.data]);
  const quote = query.data?.quote;
  const tradeDate = query.data?.tradeDate;
  return (
    <>
      <div className={styles.toolbar}>
        <div className={styles.quote}>
          <strong>{quote?.close.toFixed(2) ?? '—'}</strong>
          <Change value={quote?.change} />
        </div>
        <PeriodPicker value={period} onChange={setPeriod} />
      </div>
      {tradeDate && <time dateTime={tradeDate}>最新交易日 {tradeDate}</time>}
      {data ? (
        <Suspense fallback={<LoadingChart />}>
          <MarketChart variant="stock" label={`${code} 历史行情`} data={data} period={period} visibleAverages={stockAverages} />
        </Suspense>
      ) : <LoadingChart>{query.error?.message}</LoadingChart>}
      {data && <ul className={styles.legend} aria-label="图表图例"><li>K 线</li><li>MA5</li><li>MA20</li><li>成交量</li></ul>}
      <dl className={styles.metrics}>
        <div><dt>市盈率 TTM</dt><dd>{quote?.pe?.toFixed(2) ?? '—'}</dd></div>
        <div><dt>市净率 MRQ</dt><dd>{quote?.pb?.toFixed(2) ?? '—'}</dd></div>
        <div><dt>换手率</dt><dd>{quote?.turnover === undefined ? '—' : `${quote.turnover.toFixed(2)}%`}</dd></div>
        <div><dt>成交量</dt><dd>{quote?.volume === undefined ? '—' : stockQuoteFormat.format(quote.volume)}</dd></div>
      </dl>
    </>
  );
}

type Props = { variant: 'index' } | { variant: 'stock'; code?: string | null };

export function MarketPanel(props: Props) {
  const section = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const isIndex = props.variant === 'index';
  const title = isIndex ? '上证指数行情' : '行情概览';
  useEffect(() => {
    if (!('IntersectionObserver' in window)) {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: '120px' });
    observer.observe(section.current!);
    return () => observer.disconnect();
  }, []);
  return (
    <section ref={section} className={styles.panel} data-variant={props.variant} aria-label={title}>
      <h2>{title}</h2>
      {visible && (isIndex ? <IndexMarket /> : props.code && <StockMarket key={props.code} code={props.code} />)}
      {!visible && <div className={styles.placeholder} aria-hidden="true" />}
      {visible && !isIndex && !props.code && <LoadingChart>识别股票后载入真实 K 线</LoadingChart>}
      <p className={styles.footnote}>数据来源：BaoStock · 最近交易日收盘数据，非实时行情</p>
    </section>
  );
}
