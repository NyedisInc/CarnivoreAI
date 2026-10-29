import { authFetch } from '../../opscenter/api/auth.svelte';

export interface ModEntry {
  mod_id: string;
  name: string | null;
  version: string | null;
  description: string | null;
  path: string;
  source: 'catalog' | 'local';
  install_id: string | null;
  item_id: string | null;
  state: 'on' | 'off' | 'partial';
  registered_in: number;
  groups_total: number;
  is_mod: boolean;
  present: boolean;
  removable: boolean;
}

export interface ModGroup {
  label: string;
  members: string[];
  real_path_display: string;
  status: string;
}

export interface ModsResponse {
  mods: ModEntry[];
  groups: ModGroup[];
  claude: { version: string | null; ok: boolean };
  accounts: { status: string };
}

export interface GroupResult {
  real: string;
  members: string[];
  status: string;
}

export interface WriteResult {
  results: GroupResult[];
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export function listMods(): Promise<ModsResponse> {
  return authFetch('/mods');
}

export function setEnabled(modId: string, enabled: boolean): Promise<WriteResult> {
  return authFetch(`/mods/${encodeURIComponent(modId)}/enabled`, json('PUT', { enabled }));
}

export function removeLocal(modId: string): Promise<WriteResult> {
  return authFetch(`/mods/${encodeURIComponent(modId)}`, { method: 'DELETE' });
}

export function uninstallCatalog(installId: string): Promise<unknown> {
  return authFetch(`/catalog/installed/${encodeURIComponent(installId)}`, { method: 'DELETE' });
}
