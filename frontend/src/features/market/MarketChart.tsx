import { createChart, type LogicalRange } from 'lightweight-charts';
import { useEffect, useEffectEvent, useRef } from 'react';
import { constrainRange, zoomFromRight } from './chartRange';
import { AVERAGE_PERIODS, type AveragePeriod, type MarketPeriod, type MarketSeries } from './marketData';
import styles from './MarketPanel.module.css';

const chartPalettes = {
  index: { up: '#b03a2e', down: '#1e8e5a', averages: { 5: '#b07c16', 10: '#5979a8', 20: '#9964a5' } },
  stock: { up: '#496f5c', down: '#9b4d43', averages: { 5: '#806127', 10: '#5979a8', 20: '#687a82' } },
};

type Props = {
  variant: keyof typeof chartPalettes;
  label: string;
  data: MarketSeries;
  period: MarketPeriod;
  visibleAverages: readonly AveragePeriod[];
  onReachHistory?: () => void;
};

export default function MarketChart({ variant, label, data, period, visibleAverages, onReachHistory }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const update = useRef<((data: MarketSeries, period: MarketPeriod, averages: readonly AveragePeriod[]) => void) | null>(null);
  const reachHistory = useEffectEvent(() => onReachHistory?.());

  useEffect(() => {
    const host = container.current!;
    const section = host.closest('section');
    const document = host.ownerDocument;
    const palette = chartPalettes[variant];
    const chart = createChart(host, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: '#74695b', fontFamily: '"FINEX Round", sans-serif' },
      localization: { locale: 'zh-CN' },
      grid: { vertLines: { color: 'rgba(83,64,41,.06)' }, horzLines: { color: 'rgba(83,64,41,.06)' } },
      rightPriceScale: { borderColor: 'rgba(83,64,41,.16)' },
      timeScale: { borderColor: 'rgba(83,64,41,.16)', rightOffset: 0 },
      handleScroll: { mouseWheel: false, vertTouchDrag: false },
      handleScale: { mouseWheel: false },
    });
    const candles = chart.addCandlestickSeries({
      upColor: palette.up, downColor: palette.down, borderVisible: variant === 'index',
      borderUpColor: palette.up, borderDownColor: palette.down, wickUpColor: palette.up, wickDownColor: palette.down,
    });
    const volume = chart.addHistogramSeries({
      priceFormat: { type: 'volume' }, priceScaleId: '', lastValueVisible: false, priceLineVisible: false,
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const averages = AVERAGE_PERIODS.map((window) => ({
      window,
      line: chart.addLineSeries({
        color: palette.averages[window], lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
      }),
    }));
    const scale = chart.timeScale();
    let previous: MarketSeries | undefined;
    let previousPeriod: MarketPeriod | undefined;
    let updating = false;
    let focused = false;
    let inGesture = false;
    let lastWheelTime = -Infinity;
    let wheelEnabled = false;
    let interacted = false;

    const inChart = (target: EventTarget | null) => target instanceof Node && host.contains(target);
    const inControls = (target: EventTarget | null) => target instanceof Element
      && section?.contains(target) && Boolean(target.closest('[data-chart-control]'));

    function setWheel(enabled: boolean) {
      if (enabled === wheelEnabled) return;
      wheelEnabled = enabled;
      chart.applyOptions({ handleScroll: { mouseWheel: enabled }, handleScale: { mouseWheel: enabled } });
    }

    function focus(event: PointerEvent) {
      focused = Boolean(inChart(event.target) || inControls(event.target));
      if (focused) lastWheelTime = -Infinity;
      if (inChart(event.target)) interacted = true;
      setWheel(focused);
    }

    function trackWheel(event: WheelEvent) {
      if (event.timeStamp - lastWheelTime > 200 || event.timeStamp < lastWheelTime) {
        inGesture = Boolean(inChart(event.target) || inControls(event.target));
      }
      lastWheelTime = event.timeStamp;
      setWheel(focused && inGesture);
    }

    function zoom(event: WheelEvent) {
      if (!wheelEnabled || event.deltaY === 0 || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
      const range = scale.getVisibleLogicalRange();
      if (!range || !previous) return;
      interacted = true;
      if (!inControls(event.target) && event.deltaY < 0) return;
      event.preventDefault();
      event.stopPropagation();
      const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? host.clientHeight : 1;
      scale.setVisibleLogicalRange(zoomFromRight(range, event.deltaY * units, previous.candles.length));
      if (event.deltaY > 0 && range.from <= 10) reachHistory();
    }

    function boundRange(range: LogicalRange | null) {
      if (!range || !previous || updating) return;
      const bounded = constrainRange(range, previous.candles.length);
      if (Math.abs(bounded.from - range.from) > 0.001 || Math.abs(bounded.to - range.to) > 0.001) {
        updating = true;
        scale.setVisibleLogicalRange(bounded);
        updating = false;
      }
      if (interacted && range.from <= 10) reachHistory();
    }

    update.current = (next, nextPeriod, visible) => {
      averages.forEach(({ window, line }) => line.applyOptions({ visible: visible.includes(window) }));
      if (next === previous) return;
      const range = scale.getVisibleLogicalRange();
      const unchangedPeriod = previousPeriod === nextPeriod;
      const offset = previous ? next.candles.length - previous.candles.length : 0;
      previous = next;
      previousPeriod = nextPeriod;
      updating = true;
      candles.setData(next.candles);
      volume.setData(next.volume);
      averages.forEach(({ window, line }) => line.setData(next.averages[window]));
      if (unchangedPeriod && range && offset > 0) {
        scale.setVisibleLogicalRange(constrainRange({ from: range.from + offset, to: range.to + offset }, next.candles.length));
      } else {
        interacted = false;
        scale.fitContent();
      }
      updating = false;
    };

    scale.subscribeVisibleLogicalRangeChange(boundRange);
    document.addEventListener('pointerdown', focus);
    document.addEventListener('wheel', trackWheel, { passive: true, capture: true });
    section?.addEventListener('wheel', zoom, { passive: false, capture: true });
    return () => {
      update.current = null;
      document.removeEventListener('pointerdown', focus);
      document.removeEventListener('wheel', trackWheel, true);
      section?.removeEventListener('wheel', zoom, true);
      scale.unsubscribeVisibleLogicalRangeChange(boundRange);
      chart.remove();
    };
  }, [variant]);

  useEffect(() => update.current?.(data, period, visibleAverages), [variant, data, period, visibleAverages]);

  return <div ref={container} className={styles.chart} role="img" aria-label={label} />;
}
