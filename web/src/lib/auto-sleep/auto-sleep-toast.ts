
import { subscribe } from '../../opscenter/api/events.svelte';
import { resourcePush } from '../resource-push/boot';
import type { EventFrame } from '../../opscenter/api/types';
import { t } from '../i18n/index.svelte';
import { CHANGED_FRAME, autoSleep } from './auto-sleep-store.svelte';

export const SLEPT_FRAME = 'session.auto_slept';

export const SLEPT_KIND = 'AutoSlept';

interface SleptFrame {
  session_id?: string;
  session_uuid?: string;
  session_name?: string | null;
  idle_minutes?: number;
}

interface ToastSurface {
  add(toast: Record<string, unknown>): void;
}

let started = false;

export function toastFor(frame: SleptFrame, now: number = Date.now()): Record<string, unknown> | null {
  if (!frame.session_id) return null;
  const name = frame.session_name || frame.session_id;
  return {
    id: `autoslept:${frame.session_uuid ?? frame.session_id}:${now}`,
    session_id: null,
    kind: SLEPT_KIND,
    title: t('auto_sleep.toast.title'),
    body: t('auto_sleep.toast.body', { name, minutes: frame.idle_minutes ?? '' }),
    session_label: t('auto_sleep.toast.surface'),
    local: true,
  };
}

export function startAutoSleepFrames(): void {
  if (started) return;
  started = true;
  subscribe(CHANGED_FRAME, () => {
    if (!resourcePush().isLive('auto_sleep')) void autoSleep.refresh(true);
  });
  subscribe(SLEPT_FRAME, (frame: EventFrame) => {
    const toast = toastFor(frame as unknown as SleptFrame);
    const surface = (globalThis as { ToastManager?: ToastSurface }).ToastManager;
    if (!toast || !surface || typeof surface.add !== 'function') return;
    surface.add(toast);
  });
}
