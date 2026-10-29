import { ApiError, authFetch } from '../../api/auth.svelte';

export interface CompanionShell {
  agent_session_id: string;
  agent_row_id: number;
  session_id: string;
  session_row_id: number;
  tmux_session: string | null;
  working_dir: string;
  state: 'created' | 'existing' | 'restarted';
  pane?: 'live' | 'dead' | 'unknown' | null;
  session?: unknown;
}

export type ShellOutcome =
  | { ok: true; shell: CompanionShell }
  | { ok: false; code: string; detail: string };

/*  hidden  */
export function shellSlot(rowId: number): string {
  return `shell:row:${rowId}`;
}

function wordOf(err: unknown): { code: string; detail: string } {
  if (!(err instanceof ApiError)) return { code: 'unknown', detail: err instanceof Error ? err.message : String(err) };
  const body = err.payload as { detail?: { code?: unknown; detail?: unknown } } | null;
  const nested = body?.detail;
  const code = nested && typeof nested === 'object' && typeof nested.code === 'string' ? nested.code : err.code;
  return { code: err.status === 0 ? 'unreachable' : code || 'unknown', detail: err.message };
}

export async function ensureShell(agentId: string): Promise<ShellOutcome> {
  try {
    const shell = await authFetch<CompanionShell>(`/sessions/${encodeURIComponent(agentId)}/shell`, { method: 'POST' });
    return { ok: true, shell };
  } catch (err) {
    return { ok: false, ...wordOf(err) };
  }
}

export async function getShell(agentId: string): Promise<CompanionShell | null> {
  try {
    return await authFetch<CompanionShell>(`/sessions/${encodeURIComponent(agentId)}/shell`);
  } catch {
    return null;
  }
}
