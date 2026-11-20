import { Link, Route, Routes, useParams } from 'react-router';
import styles from './Preview.module.css';

const legacyHome = import.meta.env.DEV ? 'http://127.0.0.1:8100/' : '/';

function WorkbenchPreview() {
  const { id } = useParams<'id'>();
  return (
    <>
      <h1>研究工作台</h1>
      <p>任务编号 {id}</p>
      <Link to="/">返回预览</Link>
    </>
  );
}

export function AppRoutes() {
  return (
    <main className={styles.main}>
      <Routes>
        <Route path="/" element={(
          <>
            <h1>FINEX 预览</h1>
            <a href={legacyHome}>打开 FINEX 工作台</a>
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
