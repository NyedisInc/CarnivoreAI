import { faceFacts, type AgentMarkFacts, type FaceRow } from '../../lib/sessions/agent-marks';
import { bucket } from './noc';

export interface FleetSource extends FaceRow {
  label?: string | null;
  tmux_session?: string | null;
  project_name?: string | null;
  running_model?: string | null;
  running_context_used_pct?: number | null;
  subagents_state?: string | null;
  subagents_running?: number | null;
  session?: { id?: string };
}

export type FleetState = 'waiting' | 'working' | 'idle' | 'unknown';

export interface FleetRow {
  key: string;
  sessionId: string;
  tmuxSession: string | null;
  name: string;
  project: string | null;
  model: string | null;
  contextPct: number | null;
  subagents: number | null;
  state: FleetState;
  led: AgentMarkFacts;
}

export interface FleetModel {
  rows: FleetRow[];
  counts: Record<FleetState, number>;
  total: number | null;
}

const ORDER: Record<FleetState, number> = { waiting: 0, working: 1, idle: 2, unknown: 3 };

/* waiting on you */
export function fleetModel(rows: readonly FleetSource[] | null): FleetModel {
  const counts: Record<FleetState, number> = { waiting: 0, working: 0, idle: 0, unknown: 0 };
  const list: FleetRow[] = [];
  for (const row of rows ?? []) {
    if (row.activity_status === 'dead') continue;
    const state: FleetState = bucket(row) ?? 'unknown';
    counts[state]++;
    const id = row.session?.id ?? '';
    const context = row.running_context_used_pct;
    list.push({
      key: id || row.tmux_session || `row-${list.length}`,
      sessionId: id,
      tmuxSession: row.tmux_session ?? null,
      name: row.label || row.tmux_session || id,
      project: row.project_name ?? null,
      model: row.running_model ?? null,
      contextPct: typeof context === 'number' && Number.isFinite(context) ? Math.min(100, Math.max(0, context)) : null,
      subagents: row.subagents_state === 'ok' && typeof row.subagents_running === 'number' ? row.subagents_running : null,
      state,
      led: faceFacts(row, { transport: null }),
    });
  }
  list.sort((a, b) => ORDER[a.state] - ORDER[b.state] || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return { rows: list, counts, total: rows ? list.length : null };
}
