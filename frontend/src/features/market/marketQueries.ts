import { queryOptions } from '@tanstack/react-query';
import { getJson } from '../../shared/api/getJson';
import { readIndex, readStock, type MarketPeriod } from './marketData';

const cacheOptions = { staleTime: 5 * 60_000, retry: false, refetchOnWindowFocus: false };

export function indexMarketQuery(days: number) {
  return queryOptions({
    ...cacheOptions,
    queryKey: ['market', 'index', 'sh.000001', 'd', days],
    queryFn: async ({ signal }) => readIndex(await getJson(`/api/market-kline?days=${days}`, signal)),
  });
}

export function stockMarketQuery(code: string, period: MarketPeriod, days: number) {
  const params = new URLSearchParams({ code, days: String(days), frequency: period });
  return queryOptions({
    ...cacheOptions,
    queryKey: ['market', 'stock', code, period, days],
    queryFn: async ({ signal }) => readStock(await getJson(`/api/stock-market?${params}`, signal)),
  });
}
