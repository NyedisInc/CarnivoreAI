import { ApiError, authFetch } from '../api/auth.svelte';

export interface ImportPreview {
  readonly name: string;
  readonly widgets: string[];
  readonly settings: string[];
  readonly drawer_zone: string[];
  readonly refusals: string[];
  readonly ok: boolean;
}

export interface ImportResult {
  readonly board_id: string;
  readonly preview: ImportPreview;
  readonly settings_applied: string[];
  readonly settings_refused: string[];
}

export interface ImportRefusal {
  readonly message: string;
  readonly refusals: string[];
}

export function refusalOf(error: unknown): ImportRefusal {
  if (!(error instanceof ApiError)) return { message: String(error), refusals: [] };
  const body = error.payload as { detail?: { refusals?: unknown } } | null;
  const list = body?.detail?.refusals;
  const refusals = Array.isArray(list) ? list.filter((line): line is string => typeof line === 'string') : [];
  return { message: error.message, refusals };
}

export async function exportBoard(boardId: string, name: string): Promise<void> {
  const document_ = await authFetch<Record<string, unknown>>(`/boards/${encodeURIComponent(boardId)}/export`);
  const blob = new Blob([JSON.stringify(document_, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${name.trim().replace(/[^a-z0-9._-]+/gi, '-').toLowerCase() || boardId}.carnivore-board.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export async function previewImport(document_: unknown): Promise<ImportPreview> {
  const answer = await authFetch<{ preview: ImportPreview }>('/boards/import', {
    method: 'POST',
    body: JSON.stringify({ document: document_, dry_run: true }),
  });
  return answer.preview;
}

export function importBoard(document_: unknown): Promise<ImportResult> {
  return authFetch<ImportResult>('/boards/import', { method: 'POST', body: JSON.stringify({ document: document_ }) });
}
