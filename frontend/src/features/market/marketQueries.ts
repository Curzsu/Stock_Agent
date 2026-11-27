import { queryOptions } from '@tanstack/react-query';
import { getJson } from '../../shared/api/getJson';
import type { paths } from '../../shared/api/schema';
import { readIndex, readStock, type MarketPeriod } from './marketData';

const cacheOptions = { staleTime: 5 * 60_000, retry: false, refetchOnWindowFocus: false };
type IndexResponse = paths['/api/market-kline']['get']['responses'][200]['content']['application/json'];
type StockResponse = paths['/api/stock-market']['get']['responses'][200]['content']['application/json'];

export function indexMarketQuery(days: number) {
  return queryOptions({
    ...cacheOptions,
    queryKey: ['market', 'index', 'sh.000001', 'd', days],
    queryFn: async ({ signal }) => readIndex(await getJson<IndexResponse>(`/api/market-kline?days=${days}`, signal)),
  });
}

export function stockMarketQuery(code: string, period: MarketPeriod, days: number) {
  const params = new URLSearchParams({ code, days: String(days), frequency: period });
  return queryOptions({
    ...cacheOptions,
    queryKey: ['market', 'stock', code, period, days],
    queryFn: async ({ signal }) => readStock(await getJson<StockResponse>(`/api/stock-market?${params}`, signal)),
  });
}
