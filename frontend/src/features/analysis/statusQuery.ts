import { queryOptions } from '@tanstack/react-query';
import { getJson } from '../../shared/api/getJson';
import type { AnalysisSnapshot } from './progress';

export function analysisStatusQuery(id: string) {
  return queryOptions({
    queryKey: ['analysis', id, 'status'],
    queryFn: ({ signal }) => getJson<AnalysisSnapshot>(`/api/status/${encodeURIComponent(id)}`, signal),
    retry: false,
    refetchOnWindowFocus: false,
  });
}
