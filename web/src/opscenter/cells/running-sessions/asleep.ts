
import type { SessionInfo, SessionRecord } from '../../api/types';

export type AsleepInfo = SessionInfo & { asleep: true; session_uuid: string };

export const ASLEEP_KEY_PREFIX = 'asleep:';

export function isAsleepRow(row: SessionInfo): row is AsleepInfo {
  return (row as Partial<AsleepInfo>).asleep === true;
}

export function asleepRows(records: SessionRecord[], liveNames: Set<string>): AsleepInfo[] {
  const out: AsleepInfo[] = [];
  for (const rec of records) {
    if (rec.asleep === false || rec.archived_at || !rec.tmux_name || liveNames.has(rec.tmux_name)) continue;
    out.push({
      asleep: true,
      session_uuid: rec.session_uuid,
      session: {
        id: ASLEEP_KEY_PREFIX + rec.session_uuid,
        pty_pid: null,
        working_dir: rec.working_dir ?? '',
        status: 'asleep',
        created_at: rec.created_at ?? '',
        last_activity: rec.last_work_at ?? '',
        agent_type: rec.agent_type,
        pinned_theme: rec.pinned_theme ?? null,
        tmux_session: rec.tmux_name,
        model: null,
      },
      recent_logs: [],
      stats: { total_commands: 0, uptime_seconds: 0, log_lines: 0, local_servers: 0 },
      session_backend: 'tmux',
      tmux_session: rec.tmux_name,
      label: rec.title,
      agent_type: rec.agent_type,
      agent_family: rec.agent_family,
      agent_family_source: null,
      agent_wrapper_label: null,
      pinned_theme: rec.pinned_theme ?? null,
      activity_status: null,
      activity_hint: null,
      unread: rec.unread === true,
      startup_gate: null,
      status_source: null,
      project_id: rec.project_id,
    } as AsleepInfo);
  }
  return out;
}
