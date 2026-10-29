
import { subscribe } from '../../opscenter/api/events.svelte';
import type { EventFrame } from '../../opscenter/api/types';
import { t } from '../i18n/index.svelte';

export const TRIPWIRE_FRAME = 'stats.tripwire';

export const TRIPWIRE_KIND = 'StatsTripwire';

interface TripwireFrame {
  id?: string;
  name?: string;
  state?: string;
  value?: number | null;
  threshold?: number;
  comparator?: string;
}

interface ToastSurface {
  add(toast: Record<string, unknown>): void;
}

let started = false;

export function toastFor(frame: TripwireFrame, now: number = Date.now()): Record<string, unknown> | null {
  if (!frame.id || !frame.name || (frame.state !== 'firing' && frame.state !== 'ok')) return null;
  const firing = frame.state === 'firing';
  return {
    id: `tripwire:${frame.id}:${now}`,
    session_id: null,
    kind: TRIPWIRE_KIND,
    title: t(firing ? 'stats_tripwire.toast.title_firing' : 'stats_tripwire.toast.title_resolved'),
    body: t('stats_tripwire.toast.body', {
      name: frame.name,
      value: frame.value ?? '',
      comparator: frame.comparator ?? '',
      threshold: frame.threshold ?? '',
    }),
    session_label: t('stats_tripwire.toast.surface'),
    local: true,
  };
}

export function startTripwireToasts(): void {
  if (started) return;
  started = true;
  subscribe(TRIPWIRE_FRAME, (frame: EventFrame) => {
    const toast = toastFor(frame as unknown as TripwireFrame);
    const surface = (globalThis as { ToastManager?: ToastSurface }).ToastManager;
    if (!toast || !surface || typeof surface.add !== 'function') return;
    surface.add(toast);
  });
}
