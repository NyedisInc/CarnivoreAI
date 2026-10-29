import { isAgentKind } from './bucketing';

export interface AgentCounts {
  active: number;
  working: number;
  unread: number;
  offline: string[];
}

type CountRow = Readonly<Record<string, unknown>> & { readonly name: string };

export type CountKind = 'active' | 'working' | 'unread';

interface RowCounts {
  active: boolean;
  working: boolean;
  unread: boolean;
}

export function rowCounts(row: CountRow): RowCounts | null {
  if (!isAgentKind(row as never)) return null;
  const hostState = typeof row.host_state === 'string' ? row.host_state : 'up';
  if (hostState !== 'up') return null;
  const status = typeof row.status === 'string' ? row.status : 'unknown';
  if (row.asleep === true || row.archived === true || row.closed === true || status === 'asleep') return null;
  const unread = row.unread === true;
  if (status === 'dead' || status === 'stopped') return { active: false, working: false, unread };
  return { active: true, working: status === 'working' || status === 'working_subagent', unread };
}

export function rowCountsAs(row: CountRow, kind: CountKind): boolean {
  return rowCounts(row)?.[kind] === true;
}

export function countAgents(rows: readonly CountRow[]): AgentCounts {
  const out: AgentCounts = { active: 0, working: 0, unread: 0, offline: [] };
  for (const row of rows) {
    if (!isAgentKind(row as never)) continue;
    const hostState = typeof row.host_state === 'string' ? row.host_state : 'up';
    if (hostState !== 'up') {
      const label = String(row.host_label ?? row.host_key ?? '');
      if (label && !out.offline.includes(label)) out.offline.push(label);
      continue;
    }
    const counted = rowCounts(row);
    if (!counted) continue;
    if (counted.unread) out.unread += 1;
    if (counted.active) out.active += 1;
    if (counted.working) out.working += 1;
  }
  return out;
}
