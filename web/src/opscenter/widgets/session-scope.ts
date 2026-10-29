import type { WidgetManifest } from './types';

export interface SessionScope {
  sessionId: string;
  rowId: number | null;
  workingDir: string;
  projectId: number | null;
}

export interface ScopeRow {
  session_row_id?: number | null;
  project_id?: number | null;
  session?: { id?: string; working_dir?: string | null } | null;
}

export function sessionScopeFor(rows: readonly ScopeRow[] | null | undefined, sessionId: string): SessionScope | null {
  if (!sessionId) return null;
  const row = (rows ?? []).find((info) => info.session?.id === sessionId);
  return {
    sessionId,
    rowId: typeof row?.session_row_id === 'number' ? row.session_row_id : null,
    workingDir: row?.session?.working_dir ?? '',
    projectId: typeof row?.project_id === 'number' ? row.project_id : null,
  };
}

export function scopeForWidget(manifest: Pick<WidgetManifest, 'scope'> | undefined, scope: SessionScope | null): SessionScope | null {
  return manifest?.scope === 'session' ? scope : null;
}
