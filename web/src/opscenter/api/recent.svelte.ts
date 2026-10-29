/* and the three */

import { authFetch } from './auth.svelte';
import { pushedMeta, pushedRows, resource, type Resource } from './poll.svelte';
import type { RecentSessionsResponse } from './types';
import { closed as demoClosed } from '../data/sessions';
import { t } from '../../lib/i18n/index.svelte';

export const RECENT_POLL_MS = 5000;

export type RecentOutcome = 'rows' | 'empty' | 'could-not-determine';

export const RECENT_NOTICE_KEYS: Readonly<Record<string, string>> = {
  probe_unavailable: 'opscenter.recent.notice.probe_unavailable',
  never_probed: 'opscenter.recent.notice.never_probed',
};

export function outcome(value: RecentSessionsResponse | null): RecentOutcome {
  if (!value) return 'could-not-determine';
  if (value.state !== 'ok') return 'could-not-determine';
  return value.sessions.length ? 'rows' : 'empty';
}

function demoRecent(): RecentSessionsResponse {
  const now = Date.now();
  return {
    state: 'ok',
    sessions: demoClosed.map((row, index) => ({
      session_uuid: row.id,
      origin: 'created',
      owned: true,
      lifecycle: 'stopped',
      title: row.task,
      working_dir: null,
      agent_type: 'claude',
      agent_family: 'claude',
      archived_at: null,
      created_at: new Date(now - (index + 1) * 3600_000).toISOString(),
      last_work_at: new Date(now - (index + 1) * 3600_000 + row.durationSeconds * 1000).toISOString(),
      project_id: null,
      tmux_name: row.id,
    })),
  };
}

export const recent: Resource<RecentSessionsResponse> = resource<RecentSessionsResponse>(
  async () => {
    const rows = pushedRows<RecentSessionsResponse['sessions'][number]>('recent');
    const meta = pushedMeta('recent');
    if (rows && meta) return { ...meta, sessions: rows } as RecentSessionsResponse;
    return authFetch<RecentSessionsResponse>('/sessions/recent');
  },
  { intervalMs: RECENT_POLL_MS, name: 'recent', demo: demoRecent, pushed: ['recent'] },
);
