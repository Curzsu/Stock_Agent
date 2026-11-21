import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { getJson } from '../../shared/api/getJson';
import type { AnalysisSnapshot } from '../analysis/progress';
import styles from './HistoryPanel.module.css';

type HistoryItem = {
  analysis_id: string;
  company_name?: string;
  stock_code?: string;
  analysis_date?: string;
  status?: AnalysisSnapshot['status'];
  api_profile?: string | null;
};

const labels = {
  pending: '等待中', running: '分析中', completed: '已完成', degraded: '部分完成', error: '出错',
};

function HistoryCard({ item }: { item: HistoryItem }) {
  const report = item.status === 'completed' || item.status === 'degraded';
  const path = `/app/analysis/${encodeURIComponent(item.analysis_id)}${report ? '/report' : ''}`;
  return (
    <li className={styles.card}>
      <Link to={path} data-status={item.status}>
        <div className={styles.cardHeading}>
          <div>
            <h3>{item.company_name || '未知标的'}</h3>
            <span className={styles.code}>{item.stock_code || '—'}{item.api_profile && ` · 配置 ${item.api_profile}`}</span>
          </div>
          <span className={styles.status}>{item.status ? labels[item.status] : '待查询'}</span>
        </div>
        <p className={styles.date}>{item.analysis_date?.slice(0, 10) || '—'}</p>
      </Link>
    </li>
  );
}

export function HistoryPanel({ standalone = false }: { standalone?: boolean }) {
  const history = useQuery({
    queryKey: ['history'],
    queryFn: async ({ signal }) => {
      const data = await getJson<{ history: HistoryItem[] }>('/api/history', signal);
      return Array.isArray(data?.history) ? data.history.slice().reverse() : [];
    },
    retry: false,
  });
  const items = history.data;
  const grid = useRef<HTMLUListElement>(null);
  const [controls, setControls] = useState({ previous: false, next: false });

  useEffect(() => {
    const list = grid.current;
    if (!list || standalone) return;
    const update = () => setControls({
      previous: list.scrollLeft > 1,
      next: list.scrollLeft + list.clientWidth < list.scrollWidth - 1,
    });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(list);
    list.addEventListener('scroll', update, { passive: true });
    return () => { observer.disconnect(); list.removeEventListener('scroll', update); };
  }, [items, standalone]);

  function scroll(direction: number) {
    const list = grid.current;
    const card = list?.firstElementChild;
    if (!list || !card) return;
    const gap = Number.parseFloat(getComputedStyle(list).columnGap) || 0;
    list.scrollBy({
      left: direction * (card.getBoundingClientRect().width + gap),
      behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
    });
  }

  const Heading = standalone ? 'h1' : 'h2';
  return (
    <section className={styles.section} aria-label="历史报告">
      <div className={styles.container}>
        <header className={styles.header}>
          <Heading>历史报告</Heading>
          <div className={styles.controls}>
            {items && <span>{items.length} 份报告</span>}
            {standalone ? <Link to="/">返回首页</Link> : (
              <>
                <Link to="/app/history">查看全部</Link>
                {Boolean(items?.length) && (
                  <>
                    <button type="button" aria-label="上一份报告" disabled={!controls.previous} onClick={() => scroll(-1)}>‹</button>
                    <button type="button" aria-label="下一份报告" disabled={!controls.next} onClick={() => scroll(1)}>›</button>
                  </>
                )}
              </>
            )}
          </div>
        </header>
        {history.error ? <p role="alert">{history.error.message} <button type="button" onClick={() => { void history.refetch(); }}>重新加载历史</button></p>
          : !items ? <p role="status">正在读取历史…</p>
            : items.length ? <ul ref={grid} className={standalone ? styles.list : styles.carousel}>{items.map((item) => <HistoryCard key={item.analysis_id} item={item} />)}</ul>
              : <p className={styles.empty}>暂无分析记录</p>}
      </div>
    </section>
  );
}
