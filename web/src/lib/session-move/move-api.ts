import { authFetch } from '../../opscenter/api/auth.svelte';

export type MoveDestination = { project_id: number } | { new_folder: string };

export interface MoveRefusal {
  code: string;
  message: string;
}

export interface MovePlan {
  session_uuid: string;
  tmux_name: string | null;
  source: string | null;
  source_kind: 'temp' | 'home' | null;
  destination: string | null;
  destination_kind: 'project' | 'new_folder' | null;
  project_id: number | null;
  project_name: string | null;
  creates_folder: boolean;
  pane_state: string;
  kills_live_pane: boolean;
  file_count: number;
  total_bytes: number;
  left_behind: string[];
  collisions: string[];
  ok: boolean;
  refusals: MoveRefusal[];
  applied: boolean;
  done: Record<string, unknown> | null;
}

export interface MoveProject {
  id: number | null;
  name: string;
  path: string;
  archived_at?: string | null;
}

export function sameDestination(a: MoveDestination | null, b: MoveDestination | null): boolean {
  if (!a || !b) return false;
  if ('project_id' in a && 'project_id' in b) return a.project_id === b.project_id;
  return 'new_folder' in a && 'new_folder' in b && a.new_folder === b.new_folder;
}

export async function listMoveProjects(): Promise<MoveProject[]> {
  const rows = (await authFetch<MoveProject[] | null>('/projects')) ?? [];
  return rows.filter((p) => p.id !== null && !p.archived_at);
}

export function planMove(sessionUuid: string, destination: MoveDestination): Promise<MovePlan> {
  return post(sessionUuid, { ...destination, apply: false, confirm_restart_live: false });
}

export function applyMove(sessionUuid: string, destination: MoveDestination, confirmRestartLive: boolean): Promise<MovePlan> {
  return post(sessionUuid, { ...destination, apply: true, confirm_restart_live: confirmRestartLive });
}

function post(sessionUuid: string, body: Record<string, unknown>): Promise<MovePlan> {
  return authFetch<MovePlan>(`/sessions/${encodeURIComponent(sessionUuid)}/move-folder`, { method: 'POST', body: JSON.stringify(body) });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} b`;
  const units = ['kb', 'mb', 'gb'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}
