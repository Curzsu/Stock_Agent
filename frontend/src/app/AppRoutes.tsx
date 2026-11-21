import { lazy, Suspense, useEffect, useState } from 'react';
import { Link, Route, Routes, useLocation, useParams } from 'react-router';
import { AnalysisForm } from '../features/analysis/AnalysisForm';
import { WorkbenchPage } from '../features/analysis/WorkbenchPage';
import { HistoryPanel } from '../features/history/HistoryPanel';
import { MarketPanel } from '../features/market/MarketPanel';
import { INTRO_LOCK_MS, usePageScroll } from './usePageScroll';
import styles from './Preview.module.css';

const legacyHome = import.meta.env.DEV ? 'http://127.0.0.1:8100/' : '/';
const ReportPage = lazy(() => import('../features/reports/ReportPage'));

function WorkbenchPreview() {
  const { id } = useParams<'id'>();
  const { state } = useLocation();
  const submittedQuery = typeof state?.submittedQuery === 'string' ? state.submittedQuery : undefined;
  return id ? <WorkbenchPage key={id} id={id} submittedQuery={submittedQuery} /> : null;
}

function Opening() {
  return (
    <div className={styles.opening} aria-hidden="true">
      <div>
        <div className={styles.openingLogo}>{[...'FINEX'].map((letter) => <span key={letter}>{letter}</span>)}</div>
        <div className={styles.openingLine} />
        <p>金融分析智能体系统</p>
        <div className={styles.openingDots}>{[...'FINEX'].map((letter) => <span key={letter} />)}</div>
      </div>
    </div>
  );
}

export function AppRoutes() {
  const { pathname } = useLocation();
  const [intro, setIntro] = useState(() => pathname === '/' && typeof window !== 'undefined'
    && !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [opening, setOpening] = useState(intro);
  usePageScroll(pathname, opening);
  useEffect(() => {
    if (!intro) return;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    function skipIfReduced() {
      if (reducedMotion.matches) {
        setOpening(false);
        setIntro(false);
      }
    }
    const ready = window.setTimeout(() => setOpening(false), INTRO_LOCK_MS);
    const done = window.setTimeout(() => setIntro(false), 3900);
    reducedMotion.addEventListener('change', skipIfReduced);
    return () => {
      window.clearTimeout(ready);
      window.clearTimeout(done);
      reducedMotion.removeEventListener('change', skipIfReduced);
    };
  }, [intro]);

  return (
    <main className={styles.main}>
      <Routes>
        <Route path="/" element={(
          <>
            {intro && <Opening />}
            <section className={styles.hero} data-intro={intro || undefined} inert={opening || undefined}>
              <header className={styles.heroHeader}>
                <div className={styles.brand}><span>FX</span> FINEX</div>
                <span className={styles.tagline}>金融分析智能体系统</span>
                <a href={legacyHome}>打开 FINEX 工作台</a>
              </header>
              <div className={styles.heroContent}>
                <h1><span>智能</span><span>金融分析</span></h1>
                <p>输入股票代码或公司名称，获取多维度深度分析报告</p>
                <AnalysisForm />
              </div>
            </section>
            <HistoryPanel />
            <MarketPanel variant="index" />
          </>
        )} />
        <Route path="/app/analysis/:id" element={<WorkbenchPreview />} />
        <Route path="/app/analysis/:id/report" element={<Suspense fallback={<p role="status">正在加载报告…</p>}><ReportPage /></Suspense>} />
        <Route path="/app/history" element={<HistoryPanel standalone />} />
        <Route path="*" element={(
          <>
            <h1>页面未找到</h1>
            <Link to="/">返回预览</Link>
          </>
        )} />
      </Routes>
    </main>
  );
}
