import { beginNav, type NavToken } from './nav-generation';

export interface OpenRunningDeps {
  rows: () => ReadonlyArray<{ session_id?: string | null; is_active?: boolean }>;
  load: () => Promise<unknown>;
  rejoin: (sessionId: string | null, nav: NavToken) => Promise<void>;
  attach: (tmuxName: string, nav: NavToken) => Promise<void>;
}

export async function openRunning(sessionId: string, tmuxName: string, deps: OpenRunningDeps): Promise<void> {
  const id = String(sessionId || '').trim();
  const name = String(tmuxName || '').trim();
  if (!id && !name) return;
  const nav = beginNav('open:' + (id || name));
  const find = (): { session_id?: string | null; is_active?: boolean } | undefined =>
    id ? deps.rows().find((candidate) => candidate.session_id === id) : undefined;
  let row = find();
  if (!row && id) {
    await deps.load();
    row = find();
  }
  if (row?.is_active) return deps.rejoin(row.session_id ?? null, nav);
  if (!name) return;
  return deps.attach(name, nav);
}
