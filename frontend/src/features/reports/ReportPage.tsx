import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router';
import { AGENTS, type Agent } from '../analysis/progress';
import { PARTIAL_KEYS } from '../analysis/partialQuery';
import { dimensionTitles, pdfStatusQuery, pdfUrl, reportQuery } from './reportQueries';
import { ReportMarkdown } from './ReportMarkdown';
import styles from './ReportPage.module.css';

function pdfFilename(response: Response) {
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const encoded = disposition.match(/filename\*=utf-8'[^']*'([^;]+)/i)?.[1];
  if (encoded) {
    try { return decodeURIComponent(encoded); } catch { /* use the plain filename */ }
  }
  return disposition.match(/filename="([^"]+)"/i)?.[1] ?? 'FINEX_研报.pdf';
}

function PdfDownload({ id }: { id: string }) {
  const pdf = useQuery(pdfStatusQuery(id));
  const request = useRef<AbortController | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => () => request.current?.abort(), []);

  async function download() {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setDownloading(true);
    setError('');
    try {
      const response = await fetch(pdfUrl(id), { signal: controller.signal, cache: 'no-store' });
      if (!response.ok || !response.headers.get('Content-Type')?.includes('application/pdf')) {
        await response.body?.cancel();
        throw new Error('PDF 下载暂不可用，请稍后重试。');
      }
      const file = await response.blob();
      if (controller.signal.aborted) return;
      const downloadUrl = URL.createObjectURL(file);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = pdfFilename(response);
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'PDF 下载失败');
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setDownloading(false);
    }
  }

  if (!pdf.isError && pdf.data === 'ready') return (
    <>
      <button className={styles.pdf} type="button" disabled={downloading} onClick={() => { void download(); }}>
        {downloading ? '正在下载…' : '下载 PDF 报告'}
      </button>
      {error && <span role="alert">{error}</span>}
    </>
  );
  const pending = !pdf.isError && (pdf.isPending || pdf.data === 'pending');
  return (
    <span className={styles.pdf} role="status" aria-disabled="true">
      {pending ? '正在生成 PDF...' : pdf.data === 'failed' ? 'PDF 生成失败' : 'PDF 暂不可用'}
    </span>
  );
}

function Report({ id }: { id: string }) {
  const report = useQuery(reportQuery(id));
  const analysisPath = `/app/analysis/${encodeURIComponent(id)}`;
  if (report.isPending || report.error || !report.data) {
    return (
      <div className={styles.shell}>
        <Link to={analysisPath}>返回研究工作台</Link>
        {report.error ? (
          <p role="alert">{report.error.message} <button type="button" onClick={() => { void report.refetch(); }}>重新加载报告</button></p>
        ) : <p role="status">正在加载报告…</p>}
      </div>
    );
  }
  const data = report.data;
  const sections = AGENTS.flatMap((agent) => {
    const source = agent === 'summary' ? data.final_report : data[PARTIAL_KEYS[agent]];
    return typeof source === 'string' && source.trim() ? [{ agent, source }] : [];
  });
  const missing = Array.isArray(data.missing_dimensions)
    ? data.missing_dimensions.filter((agent) => typeof agent === 'string')
      .map((agent) => Object.hasOwn(dimensionTitles, agent) ? dimensionTitles[agent as Agent] : agent) : [];
  return (
    <div className={styles.shell}>
      <Link to={analysisPath}>返回研究工作台</Link>
      <article className={styles.report}>
        <header className={styles.header}>
          <span>FINEX RESEARCH REPORT</span>
          <h1>{data.company_name ? `${data.company_name} 分析报告` : '分析报告'}</h1>
          <div className={styles.meta}><span>股票代码 <strong>{data.stock_code || '—'}</strong></span><span>分析日期 <strong>{data.analysis_date || '—'}</strong></span></div>
        </header>
        {sections.length > 0 && (
          <nav className={styles.toc} aria-label="报告章节">
            {sections.map(({ agent }) => <a key={agent} href={`#report-${agent}`}>{dimensionTitles[agent]}</a>)}
          </nav>
        )}
        <div className={styles.content} data-has-toc={sections.length > 0}>
          {missing.length > 0 && (
            <p className={styles.notice}>部分研究维度暂缺：{missing.join('、')}。<Link to={analysisPath}>返回协同台重试失败项</Link></p>
          )}
          {sections.map(({ agent, source }) => (
            <section key={agent} id={`report-${agent}`} className={styles.chapter}>
              <h2>{dimensionTitles[agent]}</h2>
              <ReportMarkdown source={source} />
            </section>
          ))}
          {sections.length === 0 && <p>暂无可阅读的报告正文。</p>}
        </div>
        <div className={styles.actions}>
          <Link to="/">← 返回首页</Link>
          <PdfDownload id={id} />
          <Link className={styles.primary} to="/">新分析 →</Link>
        </div>
      </article>
    </div>
  );
}

export default function ReportPage() {
  const { id } = useParams<'id'>();
  return id ? <Report key={id} id={id} /> : null;
}
