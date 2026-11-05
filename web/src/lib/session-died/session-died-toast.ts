
import { subscribe } from '../../opscenter/api/events.svelte';
import type { EventFrame } from '../../opscenter/api/types';
import { t } from '../i18n/index.svelte';
import { addLocalToast } from '../toast-surface';

export const DIED_FRAME = 'session.died';

export const DIED_KIND = 'SessionDied';

interface DiedFrame {
  session_id?: string;
  session_name?: string | null;
}

let started = false;

export function toastFor(frame: DiedFrame, now: number = Date.now()): Record<string, unknown> | null {
  if (!frame.session_id) return null;
  const name = frame.session_name || frame.session_id;
  return {
    id: `sessiondied:${frame.session_id}:${now}`,
    session_id: null,
    kind: DIED_KIND,
    notify_type: 'session.died',
    title: t('session_died.toast.title'),
    body: t('session_died.toast.body', { name }),
    session_label: t('session_died.toast.surface'),
    local: true,
  };
}

export function startSessionDiedFrames(): void {
  if (started) return;
  started = true;
  subscribe(DIED_FRAME, (frame: EventFrame) => {
    const toast = toastFor(frame as unknown as DiedFrame);
    if (toast) addLocalToast(toast);
  });
}
