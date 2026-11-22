import type { components } from '../../shared/api/schema';

export const AGENTS = ['fundamental', 'technical', 'value', 'news', 'summary'] as const;
export type Agent = typeof AGENTS[number];
type StatusResponse = components['schemas']['AnalysisStatusResponse'];
export type AgentStatus = components['schemas']['AgentDetail']['status'];
export type AgentDetail = Partial<components['schemas']['AgentDetail']>;
export type AnalysisSnapshot = Partial<Omit<StatusResponse, 'progress' | 'agent_details'>> & {
  progress?: Partial<Record<Agent, AgentStatus>>;
  agent_details?: Partial<Record<Agent, AgentDetail>>;
};

const runningSummaries: Record<Agent, string> = {
  fundamental: '正在核对财务质量、盈利能力与经营韧性。',
  technical: '正在核对价格趋势、成交动能与关键压力区。',
  value: '正在计算历史估值分位，并与行业水平进行比较。',
  news: '正在检索公开信息、重要事件与潜在风险信号。',
  summary: '正在交叉验证四路研究，并生成综合研判。',
};

export function derivePhase({ status, progress, agent_details }: AnalysisSnapshot = {}) {
  const running = AGENTS.some((agent) =>
    progress?.[agent] === 'running' || agent_details?.[agent]?.status === 'running',
  );
  if (status === 'completed' && !running) return 'completed';
  if (status === 'degraded' && !running) return 'degraded';
  if (status === 'error') return 'error';
  if (progress?.summary === 'running') return 'summarizing';
  if (running && (status === 'completed' || status === 'degraded')) return 'running';
  if (AGENTS.some((agent) => progress?.[agent] === 'completed')) return 'partial';
  return status === 'running' || running ? 'running' : 'starting';
}

export function agentSummary(agent: Agent, detail: AgentDetail = {}) {
  if (detail.summary) return detail.summary;
  if (detail.status === 'failed' && detail.error) return detail.error;
  if (detail.status === 'running') return runningSummaries[agent];
  return agent === 'summary' ? '四路研究完成后，将在此生成综合结论。' : '等待研究任务进入队列。';
}

export function agentDetails(snapshot: AnalysisSnapshot, agent: Agent) {
  const detail = snapshot.agent_details?.[agent];
  const status = detail?.status;
  return { ...detail, status: status && status !== 'waiting' ? status : snapshot.progress?.[agent] ?? 'waiting' };
}

export function isTerminalStatus(snapshot: AnalysisSnapshot) {
  return ['completed', 'degraded', 'error'].includes(derivePhase(snapshot));
}
