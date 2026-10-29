import type { RunningElsewhere } from './switch-model';

export interface BulkPreview {
  name: string;
  pane_state: string;
  projected?: { kind?: string; actionable?: boolean; conversation?: string; detail?: string };
}

export interface BulkRestartHost {
  running(): Promise<RunningElsewhere[]>;
  preview(name: string): Promise<BulkPreview>;
  respawn(name: string): Promise<{ ok?: boolean; detail?: string | null }>;
}

export interface BulkFailure {
  row: RunningElsewhere;
  reason: 'changed' | 'preview' | 'unsafe' | 'restart';
  detail?: string;
}

export function runningKey(rows: RunningElsewhere[]): string {
  return JSON.stringify(rows.map(({ session_id, tmux_session, provider, account_id, active_account_id }) =>
    [session_id, tmux_session, provider, account_id, active_account_id]).sort((a, b) =>
      String(a[0]).localeCompare(String(b[0]))));
}

export async function resetAll(
  captured: RunningElsewhere[],
  host: BulkRestartHost,
): Promise<{ restarted: number; failures: BulkFailure[] }> {
  const failures: BulkFailure[] = [];
  let restarted = 0;
  const completed = new Set<string>();
  for (const row of captured) {
    let live: RunningElsewhere[];
    try {
      live = await host.running();
    } catch (error) {
      failures.push({ row, reason: 'changed', detail: error instanceof Error ? error.message : '' });
      break;
    }
    const remaining = captured.filter((item) => !completed.has(item.session_id));
    const expected = runningKey(remaining);
    const actual = runningKey(live.filter((item) => !completed.has(item.session_id)));
    if (actual !== expected) {
      failures.push({ row, reason: 'changed' });
      break;
    }
    let preview: BulkPreview;
    try {
      preview = await host.preview(row.tmux_session);
    } catch (error) {
      failures.push({ row, reason: 'preview', detail: error instanceof Error ? error.message : '' });
      continue;
    }
    const plan = preview.projected;
    if (preview.name !== row.tmux_session || preview.pane_state !== 'alive'
      || plan?.actionable !== true || !['agent', 'replay'].includes(plan.kind ?? '')
      || plan.conversation !== 'resumed') {
      failures.push({ row, reason: 'unsafe', detail: plan?.detail });
      continue;
    }
    try {
      const afterPreview = await host.running();
      if (runningKey(afterPreview.filter((item) => !completed.has(item.session_id))) !== expected) {
        failures.push({ row, reason: 'changed' });
        break;
      }
    } catch (error) {
      failures.push({ row, reason: 'changed', detail: error instanceof Error ? error.message : '' });
      break;
    }
    try {
      const result = await host.respawn(row.tmux_session);
      if (result?.ok !== true) {
        failures.push({ row, reason: 'restart', detail: result?.detail ?? '' });
      } else {
        completed.add(row.session_id);
        restarted += 1;
      }
    } catch (error) {
      failures.push({ row, reason: 'restart', detail: error instanceof Error ? error.message : '' });
    }
  }
  return { restarted, failures };
}
