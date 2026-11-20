import { HttpError } from '../../shared/api/getJson';
import { isTerminalStatus, type AnalysisSnapshot } from './progress';
import { getAnalysisStatus } from './statusQuery';

const POLL_INTERVAL_MS = 2000;
const REQUEST_LIMIT_MS = 12_000;
export const POLL_LIMIT_MS = 30 * 60 * 1000;

export type PollEvent =
  | { type: 'status'; snapshot: AnalysisSnapshot }
  | { type: 'error'; message: string; fatal: boolean }
  | { type: 'timeout' };

export type PollCommand = { type: 'start'; id: string; deadline: number } | { type: 'refresh' };

export function startStatusPolling(id: string, deadline: number, receive: (event: PollEvent) => void) {
  let stopped = false;
  let attempt: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let requestTimer: ReturnType<typeof setTimeout> | undefined;
  const limit = setTimeout(timedOut, Math.max(0, deadline - Date.now()));

  function stop() {
    stopped = true;
    clearTimeout(limit);
    clearTimeout(timer);
    clearTimeout(requestTimer);
    attempt?.abort();
  }

  function timedOut() {
    stop();
    receive({ type: 'timeout' });
  }

  async function poll() {
    if (stopped || attempt) return;
    if (Date.now() >= deadline) { timedOut(); return; }
    clearTimeout(timer);
    const started = Date.now();
    const controller = new AbortController();
    attempt = controller;
    requestTimer = setTimeout(() => controller.abort(), REQUEST_LIMIT_MS);
    try {
      const snapshot = await getAnalysisStatus(id, controller.signal);
      if (stopped) return;
      if (isTerminalStatus(snapshot)) stop();
      receive({ type: 'status', snapshot });
    } catch (error) {
      if (stopped) return;
      const fatal = error instanceof HttpError && [401, 403, 404].includes(error.status);
      if (fatal) stop();
      receive({
        type: 'error',
        fatal,
        message: controller.signal.aborted && !fatal ? '读取任务状态超时' : error instanceof Error ? error.message : '读取任务状态失败',
      });
    } finally {
      clearTimeout(requestTimer);
      attempt = undefined;
      if (!stopped) timer = setTimeout(poll, Math.max(0, POLL_INTERVAL_MS - (Date.now() - started)));
    }
  }

  void poll();
  return { stop, refresh: () => { void poll(); } };
}
