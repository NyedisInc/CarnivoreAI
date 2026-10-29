import { ApiError, authFetch } from '../api/auth.svelte';
import type { Layout } from '../engine/types';
import type { TabGroups } from '../engine/tabs';

export interface LayoutShape {
  layout: Layout | null;
  groups: TabGroups;
}

export interface LayoutMember {
  session_row_id: number;
  session_uuid: string;
  position: number;
  broadcast?: boolean;
}

export interface SavedLayout {
  layout_uuid: string;
  name: string;
  position: number;
  shape: LayoutShape;
  revision: number;
  source_key: string | null;
  members: LayoutMember[];
  created_at: string;
  updated_at: string;
}

export interface LayoutWrite {
  layout: SavedLayout | null;
  deleted: boolean;
  survivor: LayoutMember | null;
  created: boolean;
}

export interface LayoutList {
  status: 'ok' | 'unavailable' | string;
  layouts: SavedLayout[];
  detail: string | null;
}

export interface LayoutError {
  code: string;
  detail: string;
  status: number;
  current: SavedLayout | null;
}

const ROOT = '/layouts';

export function layoutError(error: unknown): LayoutError {
  if (!(error instanceof ApiError)) {
    return { code: '', detail: error instanceof Error ? error.message : String(error), status: 0, current: null };
  }
  const body = error.payload as { detail?: unknown } | null;
  const inner = body && typeof body.detail === 'object' && body.detail !== null
    ? (body.detail as Record<string, unknown>)
    : {};
  return {
    code: typeof inner['code'] === 'string' ? (inner['code'] as string) : error.code ?? '',
    detail: typeof inner['detail'] === 'string' ? (inner['detail'] as string) : error.message,
    status: error.status,
    current: (inner['current'] as SavedLayout | undefined) ?? null,
  };
}

export function listLayouts(): Promise<LayoutList> {
  return authFetch<LayoutList>(ROOT);
}

export function createLayout(name: string, shape: LayoutShape, sourceKey?: string): Promise<LayoutWrite> {
  return authFetch<LayoutWrite>(ROOT, {
    method: 'POST',
    body: JSON.stringify(sourceKey ? { name, shape, source_key: sourceKey } : { name, shape }),
  });
}

export function putShape(uuid: string, shape: LayoutShape, revision: number): Promise<LayoutWrite> {
  return authFetch<LayoutWrite>(`${ROOT}/${encodeURIComponent(uuid)}/shape`, {
    method: 'PUT',
    body: JSON.stringify({ shape, expected_revision: revision }),
  });
}

export function removeMember(uuid: string, sessionUuid: string): Promise<LayoutWrite> {
  return authFetch<LayoutWrite>(`${ROOT}/${encodeURIComponent(uuid)}/members/${encodeURIComponent(sessionUuid)}`, {
    method: 'DELETE',
  });
}

export function deleteLayout(uuid: string): Promise<LayoutWrite> {
  return authFetch<LayoutWrite>(`${ROOT}/${encodeURIComponent(uuid)}`, { method: 'DELETE' });
}

export function renewActive(uuid: string): Promise<unknown> {
  return authFetch<unknown>(`${ROOT}/${encodeURIComponent(uuid)}/active`, { method: 'PUT' });
}

export interface BroadcastResult {
  session_row_id: number;
  session_uuid: string;
  status: 'sent' | 'skipped_off' | 'skipped_not_live' | 'failed' | string;
  code: string | null;
}

export interface BroadcastAnswer {
  layout_uuid: string;
  results: BroadcastResult[];
  sent: number;
  skipped: number;
  failed: number;
}

export function setMemberBroadcast(uuid: string, sessionUuid: string, enabled: boolean): Promise<LayoutWrite> {
  return authFetch<LayoutWrite>(
    `${ROOT}/${encodeURIComponent(uuid)}/members/${encodeURIComponent(sessionUuid)}/broadcast`,
    { method: 'PUT', body: JSON.stringify({ enabled }) },
  );
}

export function broadcastLine(uuid: string, text: string): Promise<BroadcastAnswer> {
  return authFetch<BroadcastAnswer>(`${ROOT}/${encodeURIComponent(uuid)}/broadcast`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

export interface LayoutSkill {
  name: string;
  description: string;
  scope: 'global' | 'project' | string;
}

export async function fetchLayoutSkills(uuid: string, sigil: '/' | '$'): Promise<LayoutSkill[]> {
  const answer = await authFetch<{ skills: LayoutSkill[] }>(
    `${ROOT}/${encodeURIComponent(uuid)}/skills?sigil=${encodeURIComponent(sigil)}`,
  );
  return answer.skills;
}
