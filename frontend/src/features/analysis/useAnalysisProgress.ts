import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { analysisPartialQuery } from './partialQuery';
import { POLL_LIMIT_MS, startStatusPolling, type PollCommand, type PollEvent } from './polling';
import { isTerminalStatus, type AnalysisSnapshot } from './progress';
import { analysisStatusKey, getAnalysisStatus } from './statusQuery';

function notifyCompletion(id: string, snapshot: AnalysisSnapshot) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  const key = `finex:completion:${id}`;
  const completedRun = snapshot.end_time ?? snapshot.status ?? 'completed';
  try {
    if (sessionStorage.getItem(key) === completedRun) return;
    sessionStorage.setItem(key, completedRun);
  } catch {
    // The subscription still sends at most one notice when storage is unavailable.
  }
  try {
    new Notification('股票分析完成', { body: `${snapshot.company_name || '股票'} 的分析报告已生成` });
  } catch {
    // Some browsers only support service-worker notifications.
  }
}

export function useAnalysisProgress(id: string, submitted = false) {
  const client = useQueryClient();
  const { data: snapshot } = useQuery({
    queryKey: analysisStatusKey(id),
    queryFn: ({ signal }) => getAnalysisStatus(id, signal),
    enabled: false,
  });
  const partial = useQuery(analysisPartialQuery(id, snapshot));
  const [issue, setIssue] = useState<Exclude<PollEvent, { type: 'status' }>>();
  const [refreshCycle, setRefreshCycle] = useState(0);

  useEffect(() => {
    const key = analysisStatusKey(id);
    const deadline = Date.now() + POLL_LIMIT_MS;
    let active = true;
    let ended = false;
    let sawActive = submitted;
    let worker: Worker | undefined;
    let fallback: ReturnType<typeof startStatusPolling> | undefined;

    function stop() {
      worker?.terminate();
      worker = undefined;
      fallback?.stop();
      fallback = undefined;
    }

    function receive(event: PollEvent) {
      if (!active || ended) return;
      if (event.type === 'status') {
        setIssue(undefined);
        const status = event.snapshot;
        client.setQueryData(key, status);
        if (isTerminalStatus(status)) {
          ended = true;
          stop();
          if (sawActive && (status.status === 'completed' || status.status === 'degraded')) notifyCompletion(id, status);
        } else {
          sawActive = true;
        }
        return;
      }
      setIssue(event);
      if (event.type === 'timeout' || event.fatal) {
        ended = true;
        stop();
      }
    }

    function startFallback() {
      stop();
      if (active && !ended) fallback = startStatusPolling(id, deadline, receive);
    }

    function refreshVisible() {
      if (document.visibilityState !== 'visible' || ended) return;
      if (worker) worker.postMessage({ type: 'refresh' } satisfies PollCommand);
      else fallback?.refresh();
    }

    // Strict Mode can clean up the first effect before opening a transport.
    queueMicrotask(() => {
      if (!active) return;
      try {
        const current = new Worker(new URL('./status.worker.ts', import.meta.url), { type: 'module' });
        worker = current;
        current.onmessage = ({ data }: MessageEvent<PollEvent>) => {
          if (worker === current) receive(data);
        };
        const failed = () => { if (worker === current) startFallback(); };
        current.onerror = failed;
        current.onmessageerror = failed;
        current.postMessage({ type: 'start', id, deadline } satisfies PollCommand);
      } catch {
        startFallback();
      }
    });
    document.addEventListener('visibilitychange', refreshVisible);

    return () => {
      active = false;
      stop();
      document.removeEventListener('visibilitychange', refreshVisible);
    };
  }, [id, submitted, client, refreshCycle]);

  return { snapshot, partial, issue, refresh: () => setRefreshCycle((current) => current + 1) };
}
