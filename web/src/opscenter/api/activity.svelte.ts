
import { ApiError, auth, authFetch } from './auth.svelte';
import { isDemo } from './demo';
import type { ResourceStatus } from './poll.svelte';
import { subscribe } from './events.svelte';
import { sessions } from './sessions.svelte';
import type { EventFrame, Toast } from './types';
import { activity as demoLines } from '../data/activity';
import { parseServerTime } from '../lib/format';
import { derivedDisplayName } from '../../lib/sessions/session-label';
import { t } from '../../lib/i18n/index.svelte';

export const CAPACITY = 200;

interface ToastHistory {
  toasts: Toast[];
  total: number;
  storage: string;
}

export interface ActivityEntry {
  id: string;
  time: string;
  tag: string;
  message: string;
  source: string;
}

export const activity = $state<{ lines: ActivityEntry[] }>({ lines: [] });

export const seeded = $state<{
  count: number;
  loaded: boolean;
  status: ResourceStatus;
  error: string | null;
  storage: string;
}>({
  count: 0,
  loaded: false,
  status: 'loading',
  error: null,
  storage: '',
});

let serial = 0;

function clockOf(value: string | null | undefined): string {
  const at = value ? parseServerTime(value) : Number.NaN;
  const when = Number.isFinite(at) ? new Date(at) : new Date();
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${pad(when.getHours())}:${pad(when.getMinutes())}:${pad(when.getSeconds())}`;
}

function push(entry: Omit<ActivityEntry, 'id'>): void {
  serial += 1;
  activity.lines = [...activity.lines, { ...entry, id: `a${serial}` }].slice(-CAPACITY);
}

function tagForToast(kind: string): string {
  if (kind === 'PermissionRequest') return 'session';
  if (kind === 'Stop') return 'session';
  return 'agent';
}

function sourceOf(toast: Toast): string {
  return toast.session_label ?? toast.session_name ?? '';
}

export function sourceForHandle(handle: string | null | undefined): string {
  const key = handle ?? '';
  if (!key) return '';
  const row = (sessions.data ?? []).find((r) => r.tmux_session === key || r.session.id === key);
  if (row) return row.label ?? row.tmux_session ?? row.session.id;
  return derivedDisplayName(key);
}

function lineForToast(toast: Toast): Omit<ActivityEntry, 'id'> {
  const body = toast.body
    ? t('opscenter.activity.toast_line', { title: toast.title, body: toast.body })
    : toast.title;
  return {
    time: clockOf(toast.created_at),
    tag: tagForToast(toast.kind),
    message: body,
    source: sourceOf(toast),
  };
}

function isSignedOut(): boolean {
  return auth.state === 'signed-out';
}

export async function backfill(): Promise<void> {
  if (isDemo()) {
    seeded.status = 'ok';
    return;
  }
  if (isSignedOut()) {
    seeded.status = 'signed-out';
    seeded.error = null;
    seeded.loaded = true;
    return;
  }
  try {
    const history = await authFetch<ToastHistory>('/toasts/history?limit=100');
    const rows = history.toasts ?? [];
    for (const toast of rows.slice().reverse()) push(lineForToast(toast));
    seeded.count = rows.length;
    seeded.storage = history.storage ?? '';
    seeded.status = 'ok';
    seeded.error = null;
  } catch (failure) {
    seeded.count = 0;
    if (failure instanceof ApiError && failure.status === 404) {
      seeded.status = 'unavailable';
      seeded.error = null;
    } else if (isSignedOut()) {
      seeded.status = 'signed-out';
      seeded.error = null;
    } else {
      seeded.status = 'error';
      seeded.error =
        failure instanceof Error ? failure.message : t('opscenter.activity.history_unreadable');
    }
  } finally {
    seeded.loaded = true;
  }
}

export function startActivity(): () => void {
  if (isDemo()) {
    const lines = demoLines.map((line, index) => ({
      id: `d${index}`,
      time: line.time,
      tag: line.tag,
      message: line.message,
      source: line.source,
    }));
    activity.lines = lines;
    seeded.count = lines.length;
    seeded.status = 'ok';
    seeded.loaded = true;
    return () => {
    };
  }

  const offs = [
    subscribe('events.hello', () => {
      push({
        time: clockOf(null),
        tag: 'system',
        message: t('opscenter.activity.channel_connected'),
        source: t('opscenter.activity.source_host'),
      });
    }),
    subscribe('toast.new', (frame: EventFrame) => {
      if (frame.toast) push(lineForToast(frame.toast));
    }),
    subscribe('toast.ack', () => {
      push({
        time: clockOf(null),
        tag: 'system',
        message: t('opscenter.activity.toast_dismissed'),
        source: t('opscenter.activity.source_host'),
      });
    }),
    subscribe('session.status', (frame: EventFrame) => {
      const name = sourceForHandle(frame.tmux_session ?? frame.session_id);
      const status = frame.activity_status ?? t('opscenter.value.not_measured');
      push({
        time: clockOf(null),
        tag: 'session',
        message: t('opscenter.activity.session_status', { name, status }).trim(),
        source: name,
      });
    }),
    subscribe('sessions.changed', (frame: EventFrame) => {
      push({
        time: clockOf(null),
        tag: 'session',
        message: t('opscenter.activity.session_list', {
          reason: frame.reason ?? t('opscenter.activity.session_list_changed'),
        }),
        source: t('opscenter.activity.source_host'),
      });
    }),
    subscribe('session.renamed', (frame: EventFrame) => {
      const source = sourceForHandle(frame.tmux_session ?? frame.session_id);
      push({
        time: clockOf(null),
        tag: 'project',
        message: t('opscenter.activity.renamed', { name: frame.new_name ?? source }),
        source,
      });
    }),
  ];
  void backfill();
  return () => {
    for (const off of offs) off();
  };
}
