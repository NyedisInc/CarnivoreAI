import { analytics } from './state.svelte';
import { deleteChart } from './api';
import { tripwires } from '../../viz/tripwires.svelte';

export function tripwireCountFor(id: string): number {
  return tripwires.list.filter((wire) => wire.chart_id === id).length;
}

export async function deleteSavedChart(id: string): Promise<boolean> {
  const chart = analytics.charts[id];
  if (!chart) return false;
  await deleteChart(id, chart.revision);
  const next = { ...analytics.charts };
  delete next[id];
  analytics.charts = next;
  tripwires.list = tripwires.list.filter((wire) => wire.chart_id !== id);
  return true;
}
