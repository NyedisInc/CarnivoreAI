
import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { subscribe } from '../../opscenter/api/events.svelte';
import { resourcePush } from '../resource-push/boot';

export interface LayoutMember {
  session_row_id: number;
  session_uuid: string;
  position: number;
}

export interface Layout {
  layout_uuid: string;
  name: string;
  position: number;
  shape: Record<string, unknown>;
  revision: number;
  source_key: string | null;
  members: LayoutMember[];
  created_at: string;
  updated_at: string;
  colour: string;
  gradient: string | null;
  animation: string;
}

export interface LayoutStyle {
  colour: string;
  gradient: string | null;
  animation: string;
}

/* could not */
interface LayoutsResponse {
  status: 'ok' | 'unavailable';
  layouts: Layout[];
  detail: string | null;
}

export const LAYOUTS_POLL_MS = 5000;

export const layouts: Resource<Layout[]> = resource<Layout[]>(
  async () => {
    const body = await authFetch<LayoutsResponse>('/layouts');
    layoutsUnavailable.value = body.status === 'unavailable';
    return body.layouts;
  },
  {
    intervalMs: LAYOUTS_POLL_MS, name: 'layouts', demo: () => [],
    topics: ['layouts'], afterPush: () => repaintDrawer(),
  },
);

export const layoutsUnavailable = $state<{ value: boolean }>({ value: false });

export function layoutByUuid(uuid: string): Layout | null {
  return (layouts.data ?? []).find((l) => l.layout_uuid === uuid) ?? null;
}

function repaintDrawer(): void {
  const bar = (globalThis as { SessionSidebar?: { _lastSig?: unknown; _fetchAndRender?: () => Promise<void> } })
    .SessionSidebar;
  if (typeof bar?._fetchAndRender !== 'function') return;
  bar._lastSig = null;
  void bar._fetchAndRender();
}

async function write<T>(path: string, init: RequestInit): Promise<T> {
  const value = await authFetch<T>(path, init);
  await layouts.refresh(true);
  repaintDrawer();
  return value;
}

export function renameLayout(uuid: string, name: string): Promise<Layout> {
  return write<Layout>(`/layouts/${encodeURIComponent(uuid)}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  });
}

export function setLayoutStyle(uuid: string, style: LayoutStyle): Promise<Layout> {
  return write<Layout>(`/layouts/${encodeURIComponent(uuid)}/style`, {
    method: 'PUT',
    body: JSON.stringify(style),
  });
}

export function deleteLayout(uuid: string): Promise<void> {
  return write<void>(`/layouts/${encodeURIComponent(uuid)}`, { method: 'DELETE' });
}

export interface LayoutMemberWrite {
  layout: Layout | null;
  deleted: boolean;
  survivor: LayoutMember | null;
}

export function addLayoutMember(uuid: string, sessionUuid: string): Promise<LayoutMemberWrite> {
  return write<LayoutMemberWrite>(`/layouts/${encodeURIComponent(uuid)}/members`, {
    method: 'POST',
    body: JSON.stringify({ session_uuid: sessionUuid }),
  });
}

export function reorderLayouts(layoutUuids: string[]): Promise<LayoutsResponse> {
  return write<LayoutsResponse>('/layouts/order', {
    method: 'PUT',
    body: JSON.stringify({ layout_uuids: layoutUuids }),
  });
}

export function wireLayoutsRefresh(): () => void {
  return subscribe('sessions.changed', (frame) => {
    if ((frame as { reason?: string }).reason !== 'layouts') return;
    if (resourcePush().isLive('layouts')) return;
    void layouts.refresh(true).then(repaintDrawer);
  });
}

let started = false;
export function start(): void {
  if (started) return;
  started = true;
  wireLayoutsRefresh();
}
