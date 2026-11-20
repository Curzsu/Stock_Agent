import { getJson } from '../../shared/api/getJson';
import type { AnalysisSnapshot } from './progress';

export function analysisStatusKey(id: string) {
  return ['analysis', id, 'status'] as const;
}

export async function getAnalysisStatus(id: string, signal: AbortSignal) {
  const snapshot = await getJson<AnalysisSnapshot>(`/api/status/${encodeURIComponent(id)}`, signal);
  if (!snapshot?.status || !['pending', 'running', 'completed', 'degraded', 'error'].includes(snapshot.status)) {
    throw new Error('任务状态格式无效');
  }
  return snapshot;
}
