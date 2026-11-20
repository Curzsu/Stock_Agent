export class HttpError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'HttpError';
  }
}

export async function requestJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail[0]?.msg : detail?.message;
    throw new HttpError(response.status, typeof message === 'string' ? message : `请求失败（HTTP ${response.status}）`);
  }
  return response.json();
}

export function getJson<T = unknown>(path: string, signal: AbortSignal) {
  return requestJson<T>(path, { signal });
}
