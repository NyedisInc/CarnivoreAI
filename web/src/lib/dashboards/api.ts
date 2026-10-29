import { authFetch } from '../../opscenter/api/auth.svelte';
import { flushHome } from '../../opscenter/engine/home-sync.svelte';
import type { Layout } from '../../opscenter/engine/types';

export interface DashboardList {
  dashboards: { id: string; name: string }[];
  active: string | null;
  revision: number;
  synced: boolean;
  created?: string;
}

async function call(path: string, init: RequestInit): Promise<DashboardList> {
  await flushHome();
  return authFetch<DashboardList>(`/dashboards${path}`, init);
}

export function listDashboards(): Promise<DashboardList> {
  return authFetch<DashboardList>('/dashboards');
}

export function createDashboard(name: string, from: { layout: Layout } | { copyOf: string }): Promise<DashboardList> {
  const body = 'layout' in from ? { name, layout: from.layout } : { name, copy_of: from.copyOf };
  return call('', { method: 'POST', body: JSON.stringify(body) });
}

export function renameDashboard(id: string, name: string): Promise<DashboardList> {
  return call(`/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ name }) });
}

/* the widgets page */
export function setDashboardLayout(id: string, layout: Layout): Promise<DashboardList> {
  return call(`/${encodeURIComponent(id)}/layout`, { method: 'PUT', body: JSON.stringify({ layout }) });
}

/* the home screen */
export function activateDashboard(id: string): Promise<DashboardList> {
  return call(`/${encodeURIComponent(id)}/activate`, { method: 'POST' });
}

export function deleteDashboard(id: string): Promise<DashboardList> {
  return call(`/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
