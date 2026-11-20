import { createRequire } from 'node:module';
import { expect, it } from 'vitest';
import { AGENTS, agentSummary, derivePhase, type AnalysisSnapshot } from './progress';

const legacy = createRequire(import.meta.url)('../../../workbench.js');

it('keeps the workbench order and phase decisions consistent with the current page', () => {
  expect(AGENTS).toEqual(legacy.AGENTS);
  const scenarios: AnalysisSnapshot[] = [
    {},
    { status: 'running' },
    { status: 'running', progress: { fundamental: 'completed' } },
    { status: 'running', progress: { summary: 'running' } },
    { status: 'completed' },
    { status: 'degraded' },
    { status: 'degraded', agent_details: { value: { status: 'running' } } },
    { status: 'error' },
  ];
  expect(scenarios.map(derivePhase)).toEqual([
    'starting', 'running', 'partial', 'summarizing', 'completed', 'degraded', 'running', 'error',
  ]);
  for (const scenario of scenarios) {
    expect(derivePhase(scenario)).toBe(legacy.derivePhase(scenario));
  }
});

it('shows the existing summary, execution error and waiting copy in that order', () => {
  for (const agent of AGENTS) {
    for (const detail of [
      {},
      { status: 'running' },
      { status: 'failed', error: '数据不可用' },
      { status: 'failed', summary: '已有摘要', error: '数据不可用' },
    ] as const) {
      expect(agentSummary(agent, detail)).toBe(legacy.agentSummaryForStatus(agent, detail));
    }
  }
});
