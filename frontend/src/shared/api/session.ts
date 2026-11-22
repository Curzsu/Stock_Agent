import { getJson, requestJson } from './getJson';
import type { components } from './schema';

export async function requestSessionWrite<T>(path: string, init: RequestInit & { signal: AbortSignal }) {
  const session = await getJson<components['schemas']['SessionResponse']>('/api/session', init.signal);
  const headers = new Headers(init.headers);
  headers.set('X-CSRF-Token', session.csrf_token);
  return requestJson<T>(path, { ...init, headers });
}
