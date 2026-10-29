
import { resource, listingRows, type Resource } from './poll.svelte';
import type { SessionInfo } from './types';
import { running as demoRunning } from '../data/sessions';
import { parseServerTime } from '../lib/format';
import { t } from '../../lib/i18n/index.svelte';

export const SESSIONS_POLL_MS = 5000;

export const STATUS_KEYS: Readonly<Record<string, string>> = {
  dead: 'session.status.dead',
  question: 'session.status.question',
  notice: 'session.status.notice',
  working_subagent: 'session.status.working_subagent',
  working: 'session.status.working',
  finished_unread: 'session.status.finished_unread',
  idle: 'session.status.idle',
  stopped: 'session.status.stopped',
  unknown: 'session.status.unknown',
  running: 'session.status.working',
};

export type StatusHue = 'green' | 'yellow' | 'blue' | 'grey' | 'red';

export function normalizeStatus(status: unknown): string {
  return typeof status === 'string' && status in STATUS_KEYS ? status : 'unknown';
}

export function statusLabel(
  status: string | null,
  startupGate: string | null = null,
  unread: boolean | null = null,
  hostOffline: string | null = null,
  activityHint: string | null = null,
  usageLimit: string | null = null,
): string {
  if (hostOffline) return t('opscenter.status.host_offline', { host: hostOffline });
  const limitKey = normalizeStatus(status);
  if (usageLimit && limitKey !== 'dead' && limitKey !== 'stopped') return usageLimit;
  if (startupGate === 'awaiting_startup_prompt') {
    return t('opscenter.status.awaiting_startup_prompt');
  }
  const key = normalizeStatus(status);
  if (key === 'question' && typeof activityHint === 'string') {
    if (activityHint === 'question') return t('session.status.question_ask');
    const m = /^question:(\d+)\/(\d+)$/.exec(activityHint);
    if (m) return t('session.status.question_part', { n: m[1], m: m[2] });
  }
  if (unread === true && (key === 'idle' || key === 'unknown')) {
    return t(STATUS_KEYS['finished_unread'] as string);
  }
  return t(STATUS_KEYS[key] as string);
}

/* waiting on the user */
export function statusHue(
  status: string | null,
  startupGate: string | null = null,
  unread: boolean | null = null,
  hostOffline: string | null = null,
  usageLimit: string | null = null,
): StatusHue {
  if (hostOffline || usageLimit) return 'red';
  if (startupGate === 'awaiting_startup_prompt') return 'yellow';
  const key = normalizeStatus(status);
  if (key === 'dead' || key === 'stopped') return 'red';
  if (key === 'question') return 'yellow';
  if (key === 'notice') return 'blue';
  if (key === 'working' || key === 'working_subagent' || key === 'running') return 'green';
  if (key === 'finished_unread' || unread === true) return 'green';
  return 'grey';
}

export function elapsedSeconds(createdAt: string | null | undefined, now = Date.now()): number | null {
  if (!createdAt) return null;
  const started = parseServerTime(createdAt);
  if (!Number.isFinite(started)) return null;
  return Math.max(0, Math.round((now - started) / 1000));
}

function demoSessions(): SessionInfo[] {
  const now = Date.now();
  return demoRunning.map((row) => ({
    session: {
      id: row.id,
      pty_pid: null,
      working_dir: `~/Dev/${row.project}`,
      status: 'running',
      created_at: new Date(now - row.elapsedSeconds * 1000).toISOString(),
      last_activity: new Date(now).toISOString(),
      agent_type: 'claude',
      pinned_theme: null,
      tmux_session: row.id,
      model: row.agent,
    },
    recent_logs: [],
    stats: { total_commands: 0, uptime_seconds: row.elapsedSeconds, log_lines: 0, local_servers: 0 },
    session_backend: 'tmux',
    tmux_session: row.id,
    label: row.task,
    agent_type: 'claude',
    agent_family: 'claude',
    agent_family_source: 'wrapper',
    agent_wrapper_label: row.agent,
    pinned_theme: null,
    activity_status: 'working',
    activity_hint: null,
    unread: false,
    startup_gate: null,
    status_source: 'registry',
  }));
}

async function readSessions(): Promise<SessionInfo[]> {
  return listingRows<SessionInfo>('list', '/sessions/list');
}

export const sessions: Resource<SessionInfo[]> = resource<SessionInfo[]>(readSessions, {
  intervalMs: SESSIONS_POLL_MS,
  name: 'sessions',
  demo: demoSessions,
  pushed: ['list'],
});
