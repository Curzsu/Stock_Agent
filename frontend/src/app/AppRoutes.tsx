import { Link, Route, Routes, useParams } from 'react-router';
import { WorkbenchPage } from '../features/analysis/WorkbenchPage';
import { MarketPanel } from '../features/market/MarketPanel';
import styles from './Preview.module.css';

const legacyHome = import.meta.env.DEV ? 'http://127.0.0.1:8100/' : '/';

function WorkbenchPreview() {
  const { id } = useParams<'id'>();
  return id ? <WorkbenchPage id={id} /> : null;
}

export function AppRoutes() {
  return (
    <main className={styles.main}>
      <Routes>
        <Route path="/" element={(
          <>
            <header className={styles.hero}>
              <h1>FINEX 预览</h1>
              <a href={legacyHome}>打开 FINEX 工作台</a>
            </header>
            <MarketPanel variant="index" />
          </>
        )} />
        <Route path="/app/analysis/:id" element={<WorkbenchPreview />} />
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
