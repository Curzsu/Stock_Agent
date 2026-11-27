import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { HttpError } from '../../shared/api/getJson';
import type { components } from '../../shared/api/schema';
import { requestSessionWrite } from '../../shared/api/session';
import { pdfKey, reportKey } from '../reports/reportQueries';
import type { Agent, AnalysisSnapshot } from './progress';
import { analysisStatusKey } from './statusQuery';

export function useRetryAnalysis(id: string, refresh: () => void) {
  const client = useQueryClient();
  const request = useRef<AbortController | null>(null);
  const [pending, setPending] = useState<Agent>();
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => () => request.current?.abort(), []);

  async function retry(agent: Agent) {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(agent);
    setError('');
    try {
      await requestSessionWrite<components['schemas']['AnalysisRetry']>(`/api/analysis/${encodeURIComponent(id)}/retry/${agent}`, {
        method: 'POST',
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      const partialKey = ['analysis', id, 'partial'];
      for (const queryKey of [reportKey(id), pdfKey(id), partialKey]) {
        void client.cancelQueries({ queryKey });
        client.removeQueries({ queryKey });
      }
      client.setQueryData<AnalysisSnapshot>(analysisStatusKey(id), (previous) => ({
        ...previous, status: 'running', end_time: null, error: null, current_task: '正在重试研究…',
        progress: { ...previous?.progress, [agent]: 'running' },
        agent_details: { ...previous?.agent_details, [agent]: { status: 'running' } },
      }));
      void client.invalidateQueries({ queryKey: ['history'] });
      setAccepted(true);
      refresh();
    } catch (failure) {
      if (controller.signal.aborted) return;
      setError(failure instanceof Error ? failure.message : '该分析项暂时无法重试');
      if (failure instanceof HttpError && failure.status === 409) refresh();
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setPending(undefined);
    }
  }
  return { retry, pending, accepted, error };
}
