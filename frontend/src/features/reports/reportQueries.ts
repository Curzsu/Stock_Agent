import { queryOptions } from '@tanstack/react-query';
import { getJson, HttpError } from '../../shared/api/getJson';
import type { PartialResults } from '../analysis/partialQuery';
import type { Agent } from '../analysis/progress';

export type ReportResult = PartialResults & {
  company_name?: string;
  stock_code?: string;
  analysis_date?: string;
  final_report?: string;
  missing_dimensions?: string[];
};

export const reportKey = (id: string) => ['analysis', id, 'result'] as const;
export const pdfKey = (id: string) => ['analysis', id, 'pdf'] as const;
export const pdfUrl = (id: string) => `/api/report-pdf/${encodeURIComponent(id)}`;

export const dimensionTitles: Record<Agent, string> = {
  fundamental: '基本面分析', technical: '技术面分析', value: '估值分析', news: '新闻分析', summary: '综合研判',
};

export function reportQuery(id: string) {
  return queryOptions({
    queryKey: reportKey(id),
    queryFn: async ({ signal }) => {
      const deadline = AbortSignal.any([signal, AbortSignal.timeout(15000)]);
      const result = await getJson<ReportResult>(`/api/result/${encodeURIComponent(id)}`, deadline);
      if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('报告响应格式无效');
      return result;
    },
    retry: (failures, error) => failures < 2 && (!(error instanceof HttpError) || error.status >= 500),
  });
}

type PdfStatus = 'ready' | 'pending' | 'failed' | 'unavailable';

async function fetchPdfStatus(id: string, signal: AbortSignal): Promise<PdfStatus> {
  const response = await fetch(pdfUrl(id), { signal, cache: 'no-store', headers: { Range: 'bytes=0-0' } });
  if (response.ok) {
    await response.body?.cancel();
    return response.headers.get('Content-Type')?.includes('application/pdf') ? 'ready' : 'unavailable';
  }
  const payload = await response.json().catch(() => null);
  if (response.status === 404 && payload?.detail?.status === 'pending') return 'pending';
  return payload?.detail?.status === 'failed' ? 'failed' : 'unavailable';
}

export function pdfStatusQuery(id: string) {
  return queryOptions({
    queryKey: pdfKey(id),
    queryFn: ({ signal }) => fetchPdfStatus(id, AbortSignal.any([signal, AbortSignal.timeout(15000)])),
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: (query) => query.state.data === 'pending' && query.state.status !== 'error' ? 3000 : false,
  });
}
