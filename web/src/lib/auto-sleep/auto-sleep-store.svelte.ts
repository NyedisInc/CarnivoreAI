
import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';
import { errorMessageOr } from '../errors/failure-reason';

export interface AutoSleepState {
  enabled: boolean;
  idle_minutes: number;
  min_idle_minutes: number;
  max_idle_minutes: number;
  unread_blocks_sleep: boolean;
  unread_idle_minutes: number;
  keep_awake: string[];
  keep_awake_session_uuids: string[];
  mac_awake: boolean;
}

export const SLEEPABLE_FAMILIES: readonly string[] = ['claude', 'codex'];

export const AUTO_SLEEP_POLL_MS = 30000;

export const CHANGED_FRAME = 'auto_sleep.changed';

function demoState(): AutoSleepState {
  return {
    enabled: true,
    idle_minutes: 60,
    min_idle_minutes: 5,
    max_idle_minutes: 10080,
    unread_blocks_sleep: false,
    unread_idle_minutes: 60,
    keep_awake: [],
    keep_awake_session_uuids: [],
    mac_awake: false,
  };
}

export const autoSleep: Resource<AutoSleepState> = resource<AutoSleepState>(
  () => authFetch<AutoSleepState>('/auto-sleep'),
  { intervalMs: AUTO_SLEEP_POLL_MS, name: 'auto-sleep', demo: demoState, topics: ['auto_sleep'] },
);

export const autoSleepActivity = $state<{
  busy: string | null;
  error: string | null;
}>({ busy: null, error: null });

export function isKeptAwake(name: string | null): boolean | null {
  const data = autoSleep.data;
  if (!data || !name) return null;
  return data.keep_awake.includes(name);
}

export async function setKeepAwake(name: string, on: boolean): Promise<void> {
  if (autoSleepActivity.busy) return;
  autoSleepActivity.busy = name;
  autoSleepActivity.error = null;
  try {
    await authFetch<AutoSleepState>('/auto-sleep/keep-awake', {
      method: 'PUT',
      body: JSON.stringify({ tmux_name: name, keep_awake: on }),
    });
  } catch (error) {
    toastFailure(t('auto_sleep.error.keep_awake', { name, reason: errorMessageOr(error, t('opscenter.value.read_failed')) }));
  } finally {
    autoSleepActivity.busy = null;
    await autoSleep.refresh(true);
  }
}

function toastFailure(text: string): void {
  const surface = (globalThis as { ToastManager?: { add(toast: Record<string, unknown>): void } }).ToastManager;
  if (!surface || typeof surface.add !== 'function') {
    console.warn('[auto-sleep]', text);
    return;
  }
  surface.add({
    id: `autosleep-error:${Date.now()}`,
    session_id: null,
    kind: 'AutoSleepError',
    title: t('auto_sleep.toast.surface'),
    body: text,
    session_label: t('auto_sleep.toast.surface'),
    local: true,
  });
}

export async function saveAutoSleep(enabled: boolean, minutes: number): Promise<boolean> {
  if (autoSleepActivity.busy) return false;
  autoSleepActivity.busy = 'settings';
  autoSleepActivity.error = null;
  try {
    await authFetch<AutoSleepState>('/auto-sleep', {
      method: 'PUT',
      body: JSON.stringify({ enabled, idle_minutes: minutes }),
    });
    return true;
  } catch (error) {
    autoSleepActivity.error = t('auto_sleep.error.save', { reason: errorMessageOr(error, t('opscenter.value.read_failed')) });
    return false;
  } finally {
    autoSleepActivity.busy = null;
    await autoSleep.refresh(true);
  }
}

export const CHANGED_EVENT = 'cloude:auto-sleep-changed';

let announcing = false;

export function announceChanges(): void {
  if (announcing) return;
  announcing = true;
  let last: string | null = null;
  $effect.root(() => {
    $effect(() => {
      const data = autoSleep.data;
      const key = data ? JSON.stringify(data.keep_awake) : 'unknown';
      if (key === last) return;
      last = key;
      queueMicrotask(() => window.dispatchEvent(new CustomEvent(CHANGED_EVENT)));
    });
  });
}

export interface UnreadPolicy {
  unread_blocks_sleep?: boolean;
  unread_idle_minutes?: number;
}

export async function saveUnreadPolicy(policy: UnreadPolicy): Promise<boolean> {
  if (autoSleepActivity.busy) return false;
  autoSleepActivity.busy = 'settings';
  autoSleepActivity.error = null;
  try {
    await authFetch<AutoSleepState>('/auto-sleep', { method: 'PUT', body: JSON.stringify(policy) });
    return true;
  } catch (error) {
    autoSleepActivity.error = t('auto_sleep.error.save', { reason: errorMessageOr(error, t('opscenter.value.read_failed')) });
    return false;
  } finally {
    autoSleepActivity.busy = null;
    await autoSleep.refresh(true);
  }
}
