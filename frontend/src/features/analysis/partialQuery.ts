import { queryOptions } from '@tanstack/react-query';
import { getJson } from '../../shared/api/getJson';
import type { components } from '../../shared/api/schema';
import { agentDetails, type AnalysisSnapshot } from './progress';

export const PARTIAL_KEYS = {
  fundamental: 'fundamental_analysis',
  technical: 'technical_analysis',
  value: 'value_analysis',
  news: 'news_analysis',
} as const;

type PartialAgent = keyof typeof PARTIAL_KEYS;
export type PartialResults = components['schemas']['AnalysisFragments'];

export function analysisPartialQuery(id: string, snapshot?: AnalysisSnapshot) {
  const completed = snapshot ? (Object.keys(PARTIAL_KEYS) as PartialAgent[])
    .filter((agent) => agentDetails(snapshot, agent).status === 'completed') : [];
  return queryOptions({
    queryKey: ['analysis', id, 'partial', ...completed],
    queryFn: async ({ signal }) => {
      const data = await getJson<components['schemas']['AnalysisPartial']>(`/api/analysis/${encodeURIComponent(id)}/partial`, signal);
      return data.results;
    },
    enabled: completed.length > 0,
    staleTime: Infinity,
    retry: 1,
    placeholderData: (previous, query) => query?.queryKey[1] === id ? previous : undefined,
  });
}
