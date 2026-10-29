
import { subscribe } from '../../opscenter/api/events.svelte';
import type { EventFrame } from '../../opscenter/api/types';
import { t } from '../i18n/index.svelte';

export const SHAPE_FRAME = 'dev.shape_unrecognized';

export const SHAPE_KIND = 'ShapeUnrecognized';

const MAX_LISTED = 3;

interface ShapeFrame {
  file_kind?: string;
  contract_version?: number | null;
  problems?: unknown;
}

interface ToastSurface {
  add(toast: Record<string, unknown>): void;
}

let started = false;

export function toastFor(frame: ShapeFrame, now: number = Date.now()): Record<string, unknown> | null {
  if (!frame.file_kind) return null;
  const all = Array.isArray(frame.problems) ? frame.problems.filter((p): p is string => typeof p === 'string') : [];
  const listed = all.slice(0, MAX_LISTED).join('; ');
  const more = all.length > MAX_LISTED ? t('dev_shape_alert.toast.more', { count: all.length - MAX_LISTED }) : '';
  return {
    id: `shape:${frame.file_kind}:${now}`,
    session_id: null,
    kind: SHAPE_KIND,
    title: t('dev_shape_alert.toast.title'),
    body: t('dev_shape_alert.toast.body', {
      kind: frame.file_kind,
      version: frame.contract_version ?? '',
      problems: listed + more,
    }),
    session_label: t('dev_shape_alert.toast.surface'),
    local: true,
  };
}

export function startShapeAlertToasts(): void {
  if (started) return;
  started = true;
  subscribe(SHAPE_FRAME, (frame: EventFrame) => {
    const toast = toastFor(frame as unknown as ShapeFrame);
    const surface = (globalThis as { ToastManager?: ToastSurface }).ToastManager;
    if (!toast || !surface || typeof surface.add !== 'function') return;
    surface.add(toast);
  });
}
