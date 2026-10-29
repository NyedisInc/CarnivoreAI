import { authFetch } from '../../api/auth.svelte';
import { dimensionLabel } from '../../viz/dimension-label';
import { t } from '../../../lib/i18n/index.svelte';
import { clockLabel } from './value-format';
import type { Annotation, ChartConfig, DimensionItem, MetricCatalogEntry } from './types';

export async function deleteChart(id: string, revision: number): Promise<void> {
  await authFetch<null>(`/stats/charts/${encodeURIComponent(id)}?revision=${revision}`, { method: 'DELETE' });
}

export async function listCharts(): Promise<ChartConfig[]> {
  const response = await authFetch<ChartConfig[] | { charts: ChartConfig[] }>('/stats/charts');
  return Array.isArray(response) ? response : response.charts;
}

export async function metricCatalog(): Promise<MetricCatalogEntry[]> {
  const response = await authFetch<MetricCatalogEntry[] | { metrics: MetricCatalogEntry[] }>('/stats/catalog');
  return Array.isArray(response) ? response : response.metrics;
}

export async function createChart(config: ChartConfig): Promise<ChartConfig> {
  const { id, title, enabled, series, filters, range, display, resolution, viz, options } = config;
  const body = { id, title, enabled, series, filters, range, display, resolution, viz, options };
  return authFetch<ChartConfig>('/stats/charts', { method: 'POST', body: JSON.stringify(body) });
}

export function getChart(id: string): Promise<ChartConfig> {
  return authFetch<ChartConfig>(`/stats/charts/${encodeURIComponent(id)}`);
}

export async function updateChart(config: ChartConfig): Promise<ChartConfig> {
  const { id, revision, title, enabled, series, filters, range, display, resolution, viz, options } = config;
  return authFetch<ChartConfig>(`/stats/charts/${encodeURIComponent(config.id)}`, {
    method: 'PATCH', body: JSON.stringify({ id, revision, title, enabled, series, filters, range, display, resolution, viz, options }),
  });
}

export function contributions(params: URLSearchParams): Promise<unknown> {
  return authFetch<unknown>(`/stats/contributions?${params.toString()}`);
}

export async function dimensionValues(dimension: string, from: string, to: string): Promise<DimensionItem[]> {
  const params = new URLSearchParams({ dimension, from, to, limit: '200' });
  const response = await authFetch<{ items: DimensionItem[] }>(`/stats/dimensions?${params.toString()}`);
  return response.items.map((item) => ({ ...item, label: item.through ? t('analytics.pack_through', { computer: item.label, time: clockLabel(item.through) }) : dimensionLabel('', dimension, item.filter_value, item.label) }));
}

export async function annotations(from: string, to: string, signal?: AbortSignal, filters: Record<string, string | undefined> = {}): Promise<Annotation[]> {
  const params = new URLSearchParams({ from, to, limit: '200', cursor: '0' });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const response = await authFetch<{ items: Annotation[] }>(`/stats/events?${params.toString()}`, { signal });
  return response.items;
}

export function createAnnotation(label: string, occurredAt: string, scope: Record<string, string | undefined>): Promise<Annotation> {
  return authFetch<Annotation>('/stats/annotations', { method: 'POST', body: JSON.stringify({
    occurred_at: occurredAt, kind: 'manual', label, scope, basis: 'manual',
  }) });
}

export function updateAnnotation(marker: Annotation, label: string): Promise<Annotation> {
  return authFetch<Annotation>(`/stats/annotations/${encodeURIComponent(marker.id)}`, { method: 'PATCH', body: JSON.stringify({
    revision: marker.revision, occurred_at: new Date(marker.occurred_at * 1000).toISOString(), kind: 'manual',
    label, scope: marker.scope || {}, basis: 'manual',
  }) });
}

export function deleteAnnotation(marker: Annotation): Promise<void> {
  return authFetch<void>(`/stats/annotations/${encodeURIComponent(marker.id)}?revision=${marker.revision}`, { method: 'DELETE' });
}
