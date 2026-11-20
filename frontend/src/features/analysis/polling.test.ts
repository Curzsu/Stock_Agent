import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { POLL_LIMIT_MS, startStatusPolling, type PollEvent } from './polling';

const snapshot = (body: object) => Response.json(body);

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it('merges refreshes during a status read and continues past a stale terminal flag', async () => {
  let resolve!: (response: Response) => void;
  const fetch = vi.fn()
    .mockImplementationOnce(() => new Promise<Response>((finish) => { resolve = finish; }))
    .mockResolvedValueOnce(snapshot({ status: 'degraded' }));
  vi.stubGlobal('fetch', fetch);
  const receive = vi.fn<(event: PollEvent) => void>();
  const polling = startStatusPolling('example', Date.now() + POLL_LIMIT_MS, receive);
  polling.refresh();
  polling.refresh();
  expect(fetch).toHaveBeenCalledTimes(1);
  resolve(snapshot({ status: 'degraded', agent_details: { summary: { status: 'running' } } }));
  await vi.advanceTimersByTimeAsync(2000);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(receive.mock.calls.map(([event]) => event.type)).toEqual(['status', 'status']);
  await vi.advanceTimersByTimeAsync(4000);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('stops at the deadline even when a network read never settles', async () => {
  const fetch = vi.fn(() => new Promise<Response>(() => {}));
  vi.stubGlobal('fetch', fetch);
  const receive = vi.fn();
  const polling = startStatusPolling('example', Date.now() + 1000, receive);
  await vi.advanceTimersByTimeAsync(1000);
  expect(receive).toHaveBeenCalledExactlyOnceWith({ type: 'timeout' });
  polling.refresh();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it('aborts the old route and ignores a late status response', async () => {
  let signal: AbortSignal | undefined;
  let resolve!: (response: Response) => void;
  vi.stubGlobal('fetch', vi.fn((_, init: RequestInit) => {
    signal = init.signal!;
    return new Promise<Response>((finish) => { resolve = finish; });
  }));
  const receive = vi.fn();
  const polling = startStatusPolling('old', Date.now() + POLL_LIMIT_MS, receive);
  polling.stop();
  expect(signal?.aborted).toBe(true);
  resolve(snapshot({ status: 'completed' }));
  await vi.advanceTimersByTimeAsync(4000);
  expect(receive).not.toHaveBeenCalled();
});

it('retries a transient failure and stops when the task no longer exists', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockRejectedValueOnce(new TypeError('Network failure'))
    .mockResolvedValueOnce(Response.json({ detail: 'Analysis not found' }, { status: 404 })));
  const receive = vi.fn();
  startStatusPolling('missing', Date.now() + POLL_LIMIT_MS, receive);
  await vi.advanceTimersByTimeAsync(2000);
  expect(receive.mock.calls).toEqual([
    [{ type: 'error', message: 'Network failure', fatal: false }],
    [{ type: 'error', message: 'Analysis not found', fatal: true }],
  ]);
});
