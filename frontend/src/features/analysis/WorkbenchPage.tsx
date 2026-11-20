import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { MarketPanel } from '../market/MarketPanel';
import { AGENTS, agentDetails, agentSummary, derivePhase, type Agent, type AgentStatus, type AnalysisSnapshot } from './progress';
import { analysisStatusQuery } from './statusQuery';
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
};
const statusLabels: Record<AgentStatus, string> = { waiting: '等待', running: '分析中', completed: '已完成', failed: '需要重试' };

function AgentCard({ agent, detail, number }: { agent: Agent; detail: ReturnType<typeof agentDetails>; number: number }) {
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
      <p className={styles.summary}>{agentSummary(agent, detail)}</p>
    </article>
  );
}

function ResearchGrid({ snapshot }: { snapshot: AnalysisSnapshot }) {
  const agents = AGENTS.map((agent, index) => ({ agent, detail: agentDetails(snapshot, agent), number: index + 1 }));
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

export function WorkbenchPage({ id }: { id: string }) {
  const snapshot = useQuery(analysisStatusQuery(id));
  const phase = derivePhase(snapshot.data);
  return (
    <div className={styles.page} data-phase={snapshot.data ? phase : undefined}>
      <Link to="/">返回预览</Link>
      <header className={styles.masthead}>
        <h1>研究工作台</h1>
        {snapshot.data?.company_name && <p className={styles.company}>{snapshot.data.company_name} {snapshot.data.stock_code}</p>}
        <p className={styles.meta}>任务编号 {id}</p>
        {snapshot.data && <p className={styles.badge} role="status">{snapshot.data.current_task || phaseLabels[phase]}</p>}
        {snapshot.isPending && <p className={styles.meta} role="status">正在读取任务状态…</p>}
        {snapshot.error && <p className={styles.error} role="alert">{snapshot.error.message}</p>}
        {snapshot.data?.error && <p className={styles.error} role="alert">{snapshot.data.error}</p>}
      </header>
      {snapshot.data && <ResearchGrid snapshot={snapshot.data} />}
      <MarketPanel variant="stock" code={snapshot.data?.stock_code} />
    </div>
  );
}
