import { authFetch } from '../../opscenter/api/auth.svelte';
import type { SessionGitFile } from '../../opscenter/api/types';

export interface Checkpoint {
  id: number;
  prompt_uuid: string;
  kind: string;
  created_at: number;
  work_tree: string;
  pinned: boolean;
  left_out: string[];
}

export interface CheckpointList {
  session_uuid: string;
  checkpoints: Checkpoint[];
}

export interface CheckpointChanges {
  id: number;
  files: SessionGitFile[];
}

export interface CheckpointRepoUsage {
  work_tree: string;
  checkpoints: number;
  bytes: number;
  disabled_reason: string | null;
}

export interface CheckpointUsage {
  repos: CheckpointRepoUsage[];
}

export function checkpointsTopic(rowId: number): string {
  return `checkpoints:${rowId}`;
}

export const CHECKPOINT_USAGE_TOPIC = 'checkpoints:*';

export function checkpointDiffPath(rowId: number, checkpointId: number, path: string): string {
  return `/sessions/${rowId}/checkpoints/${checkpointId}/diff?path=${encodeURIComponent(path)}`;
}

export function fetchCheckpointChanges(rowId: number, checkpointId: number): Promise<CheckpointChanges> {
  return authFetch<CheckpointChanges>(`/sessions/${rowId}/checkpoints/${checkpointId}/changes`);
}

export function turnClock(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function sizeText(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB'];
  let n = Math.max(0, bytes);
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return i === 0 ? `${n} B` : `${n.toFixed(1)} ${units[i]}`;
}

export interface RevertKept {
  path: string;
  reason: string;
}

export interface RevertPreview {
  id: number;
  work_tree: string;
  change: string[];
  create: string[];
  delete: string[];
  kept: RevertKept[];
  fingerprint: string;
  blocked_by: string[];
}

export interface RevertDone {
  id: number;
  safety_id: number;
  changed: string[];
  created: string[];
  deleted: string[];
  kept: RevertKept[];
  note_sent?: boolean;
  note_error?: string | null;
}

export function fetchRevertPreview(rowId: number, checkpointId: number): Promise<RevertPreview> {
  return authFetch<RevertPreview>(`/sessions/${rowId}/checkpoints/${checkpointId}/revert/preview`);
}

export function revertToCheckpoint(rowId: number, checkpointId: number, fingerprint: string): Promise<RevertDone> {
  return authFetch<RevertDone>(`/sessions/${rowId}/checkpoints/${checkpointId}/revert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true, fingerprint }),
  });
}
