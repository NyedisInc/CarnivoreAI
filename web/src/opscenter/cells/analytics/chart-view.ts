/*  hidden  */
import { saveChartView } from './state.svelte';
import type { RangePreset, Resolution, StatsFilters } from './types';

export interface TimeWindow { from: string; to: string }

export function setZoom(id: string, next: TimeWindow | null): void {
  saveChartView(id, (chart) => ({ ...chart, range: { ...chart.range, zoom: next } }));
}

/*  hidden  */
export function setHidden(id: string, hidden: string[]): void {
  saveChartView(id, (chart) => ({ ...chart, display: { ...chart.display, hidden_series: hidden } }));
}

export function setPreset(id: string, value: string): void {
  saveChartView(id, (chart) => ({ ...chart, range: { ...chart.range, preset: (value || null) as RangePreset | null, zoom: null } }));
}

export function setResolution(id: string, value: string): void {
  saveChartView(id, (chart) => ({ ...chart, resolution: value as Resolution }));
}

export function setWidgetFilter(id: string, key: keyof StatsFilters, value: string): void {
  saveChartView(id, (chart) => ({ ...chart, filters: { ...chart.filters, [key]: value || undefined } }));
}

export function zoomStep(range: TimeWindow, base: TimeWindow, scale: number, pan = 0): TimeWindow {
  const low = new Date(range.from).getTime();
  const high = new Date(range.to).getTime();
  const span = Math.max(60_000, high - low);
  const nextSpan = span * scale;
  const center = (low + high) / 2 + pan * span;
  const baseLow = new Date(base.from).getTime();
  const baseHigh = new Date(base.to).getTime();
  const from = Math.max(baseLow, Math.min(center - nextSpan / 2, baseHigh - nextSpan));
  return { from: new Date(from).toISOString(), to: new Date(Math.min(baseHigh, from + nextSpan)).toISOString() };
}
