import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { dimensionTitles } from '../reports/reportQueries';
import { MarketPanel } from '../market/MarketPanel';
import { PARTIAL_KEYS, type PartialResults } from './partialQuery';
import { AGENTS, agentDetails, agentSummary, derivePhase, isTerminalStatus, type Agent, type AgentStatus, type AnalysisSnapshot } from './progress';
import { useAnalysisProgress } from './useAnalysisProgress';
import { useRetryAnalysis } from './useRetryAnalysis';
import styles from './WorkbenchPage.module.css';

const agentCopy: Record<Agent, [string, string]> = {
  fundamental: ['基本面分析师', '财务质量 · 盈利能力 · 经营韧性'],
  technical: ['技术面分析师', '价格趋势 · 成交动能 · 关键区间'],
  value: ['估值分析师', '历史分位 · 行业对照 · 安全边际'],
  news: ['新闻分析师', '市场叙事 · 事件追踪 · 风险信号'],
  summary: ['综合研判', '交叉验证 · 核心结论 · 风险边界'],
};
const phaseLabels: Record<ReturnType<typeof derivePhase>, string> = {
  starting: '正在识别股票标的',
  running: '五位分析师已进入研究流程',
  partial: '阶段研究结果正在陆续返回',
  summarizing: '正在生成综合研判',
  completed: '研究报告已完成',
  degraded: '报告已完成，部分维度待重试',
  error: '分析未完成',
  interrupted: '研究已中断',
};
const statusLabels: Record<AgentStatus, string> = { waiting: '等待', running: '分析中', completed: '已完成', failed: '需要重试' };

function AgentCard({ agent, detail, number, partial, onRetry, pending }: {
  agent: Agent;
  detail: ReturnType<typeof agentDetails>;
  number: number;
  partial?: string;
  onRetry?: () => void;
  pending?: Agent;
}) {
  const [title, description] = agentCopy[agent];
  const status = agent === 'summary' && detail.status === 'waiting' ? '等待前置研究' : statusLabels[detail.status];
  const elapsed = detail.execution_time_ms == null ? '' : ` · ${Math.max(1, Math.round(detail.execution_time_ms / 1000))} 秒`;
  return (
    <article className={styles.card} data-agent={agent} data-status={detail.status}>
      <div className={styles.cardMeta}>
        <span aria-hidden="true">{String(number).padStart(2, '0')}</span>
        <span className={styles.badge}>{status}{elapsed}</span>
      </div>
      <h3>{title}</h3>
      <p className={styles.description}>{description}</p>
      <p className={styles.summary} data-scroll-region>{agentSummary(agent, detail)}</p>
      {partial && (
        <details className={styles.partial}>
          <summary>查看阶段结果</summary>
          <div data-scroll-region>{partial}</div>
        </details>
      )}
      {onRetry && <button className={styles.retry} type="button" onClick={onRetry} disabled={Boolean(pending)}>
        {pending === agent ? '正在提交重试…' : `重试${dimensionTitles[agent]}`}
      </button>}
    </article>
  );
}

function ResearchGrid({ snapshot, partial, retry }: {
  snapshot: AnalysisSnapshot;
  partial?: PartialResults;
  retry: ReturnType<typeof useRetryAnalysis>;
}) {
  const phase = derivePhase(snapshot);
  const agents = AGENTS.map((agent, index) => {
    const detail = agentDetails(snapshot, agent);
    const retryable = detail.status === 'failed'
      && (phase === 'completed' || phase === 'degraded' || (phase === 'error' && agent === 'summary'));
    return {
      agent,
      detail,
      number: index + 1,
      partial: agent !== 'summary' && detail.status === 'completed' ? partial?.[PARTIAL_KEYS[agent]] : undefined,
      pending: retry.pending,
      onRetry: retryable ? () => { void retry.retry(agent); } : undefined,
    };
  });
  const completed = agents.filter(({ detail }) => detail.status === 'completed').length;
  const summary = agents.at(-1)!;
  return (
    <section className={styles.research} aria-labelledby="research-title">
      <div className={styles.researchHeader}>
        <h2 id="research-title">研究协同台</h2>
        <span>{completed} / {AGENTS.length} 已完成</span>
      </div>
      <div className={styles.cards}>
        {agents.slice(0, -1).map((item) => <AgentCard key={item.agent} {...item} />)}
      </div>
      <AgentCard {...summary} />
    </section>
  );
}

function ElapsedTime({ start, end, stopped }: { start?: string | null; end?: string | null; stopped: boolean }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!start || stopped) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [start, stopped]);
  const elapsed = Math.max(0, (end ? Date.parse(end) : now) - (start ? Date.parse(start) : now));
  const seconds = Number.isFinite(elapsed) ? Math.floor(elapsed / 1000) : 0;
  const label = [Math.floor(seconds / 60), seconds % 60].map((part) => String(part).padStart(2, '0')).join(':');
  return <time className={styles.timer} dateTime={`PT${seconds}S`} aria-label={`研究耗时 ${label}`}>{label}</time>;
}

export function WorkbenchPage({ id, submittedQuery }: { id: string; submittedQuery?: string }) {
  const { snapshot, partial, issue, refresh } = useAnalysisProgress(id, Boolean(submittedQuery));
  const retry = useRetryAnalysis(id, refresh);
  const navigate = useNavigate();
  const phase = derivePhase(snapshot);
  const reportReady = phase === 'completed' || phase === 'degraded';
  const reportPath = `/app/analysis/${encodeURIComponent(id)}/report`;
  useEffect(() => {
    if (reportReady && !retry.pending && (submittedQuery || retry.accepted)) {
      void navigate(reportPath, { replace: true });
    }
  }, [reportReady, retry.pending, submittedQuery, retry.accepted, navigate, reportPath]);
  const stopped = (snapshot && isTerminalStatus(snapshot)) || issue?.type === 'timeout' || (issue?.type === 'error' && issue.fatal);
  const label = snapshot?.company_name || submittedQuery;
  const pollMessage = issue?.type === 'timeout' ? '分析超时，请稍后重试。' : issue?.message;
  const activeSnapshot = snapshot ?? (!issue && submittedQuery ? {} : undefined);
  return (
    <div className={styles.page} data-phase={issue?.type === 'timeout' ? 'error' : activeSnapshot ? phase : undefined}>
      <header className={styles.masthead}>
        <Link to="/" className={styles.back} aria-label="返回首页"><span aria-hidden="true">←</span><span>返回</span></Link>
        <div className={styles.heading}>
          <span className={styles.eyebrow}>FINEX / 研究工作台</span>
          <h1>{label ? <>正在研究 <span>{label}</span></> : '研究工作台'}</h1>
          <p className={styles.meta}>任务编号 {id}{snapshot?.stock_code && ` · ${snapshot.stock_code}`}</p>
        </div>
        <div className={styles.mastheadStatus}>
          <ElapsedTime key={snapshot?.start_time} start={snapshot?.start_time} end={snapshot?.end_time} stopped={Boolean(stopped)} />
          {!pollMessage && <p className={styles.phase} role="status">{activeSnapshot ? snapshot?.current_task || phaseLabels[phase] : '正在读取任务状态…'}</p>}
          {pollMessage && <p className={styles.error} role="alert">{pollMessage}</p>}
          {snapshot?.error && <p className={styles.error} role="alert">{snapshot.error}</p>}
          {reportReady && <Link to={reportPath}>查看报告</Link>}
        </div>
      </header>
      {retry.error && <p className={styles.partialError} role="alert">{retry.error}</p>}
      {activeSnapshot && <ResearchGrid snapshot={activeSnapshot} partial={partial.data} retry={retry} />}
      {partial.error && (
        <p className={styles.partialError} role="status">
          {partial.error.message} <button type="button" onClick={() => { void partial.refetch(); }}>重新读取阶段结果</button>
        </p>
      )}
      <MarketPanel variant="stock" code={snapshot?.stock_code} />
    </div>
  );
}
