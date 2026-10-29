import { authFetch } from '../../opscenter/api/auth.svelte';
import { subscribe } from '../../opscenter/api/events.svelte';
import { listPollers } from '../../opscenter/api/poll.svelte';
import { mountPanel } from '../mount';
import PerfOverlay from './PerfOverlay.svelte';
import type { PerfProbeApi } from './types';

export const PERF_OVERLAY_CONTAINER = 'perf-overlay-container';

export function probe(): PerfProbeApi | null {
  const found = (globalThis as { PerfProbe?: PerfProbeApi }).PerfProbe;
  return found ?? null;
}

export async function startPerfOverlay(): Promise<boolean> {
  const api = probe();
  if (!api) return false;
  let enabled = false;
  try {
    enabled = (await authFetch<{ enabled: boolean }>('/dev/perf')).enabled === true;
  } catch {
    enabled = false;
  }
  api.remember(enabled);
  if (!enabled) {
    api.uninstall();
    return false;
  }
  api.install();
  api.registerPollerSource(listPollers);
  subscribe('perf.sample', (frame) => api.acceptServerSample(frame));
  mountPanel(PERF_OVERLAY_CONTAINER, PerfOverlay, {});
  return true;
}
