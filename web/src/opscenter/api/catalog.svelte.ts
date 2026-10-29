
import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import type { CatalogItemView, CatalogListResponse } from './types';
import { skills as demoSkills } from '../data/skills';
import { plugins as demoPlugins } from '../data/plugins';
import { t } from '../../lib/i18n/index.svelte';

export const CATALOG_POLL_MS = 60000;

export function byKind(value: CatalogListResponse | null, kind: string): CatalogItemView[] {
  if (!value) return [];
  return value.items.filter((item) => item.kind === kind);
}

export function indexNotice(value: CatalogListResponse | null): string {
  if (!value) return '';
  if (value.index.refusal) {
    return t('opscenter.catalog.index_refused', { code: value.index.refusal.code });
  }
  if (value.index.degraded) return t('opscenter.catalog.index_degraded');
  if (value.index.stale) return t('opscenter.catalog.index_stale');
  return '';
}

function demoCatalog(): CatalogListResponse {
  const item = (
    id: string,
    name: string,
    kind: string,
    publisher: string,
    latest: string,
    brief: string,
    installed: boolean,
  ): CatalogItemView => ({
    id,
    kind,
    name,
    publisher,
    latest,
    card: { brief },
    installed: installed
      ? {
          install_id: `demo-${id}`,
          scope: 'user',
          project_path: '',
          version: latest,
          update_available: false,
        }
      : null,
    untrusted: false,
  });
  return {
    index: {
      serial: 1,
      generated_at: null,
      as_of: null,
      degraded: false,
      stale: false,
      fetched_at: null,
      refusal: null,
    },
    items: [
      ...demoSkills.map((row) => item(row.id, row.name, 'skill', row.author, '1.0.0', row.description, row.installed)),
      ...demoPlugins.map((row) => item(row.id, row.name, 'plugin', row.author, row.version, row.description, false)),
    ],
    untrusted: [],
  };
}

export const catalog: Resource<CatalogListResponse> = resource<CatalogListResponse>(
  () => authFetch<CatalogListResponse>('/catalog/items'),
  { intervalMs: CATALOG_POLL_MS, name: 'catalog', demo: demoCatalog, topics: ['catalog'] },
);

export async function refreshIndex(): Promise<boolean> {
  try {
    await authFetch<unknown>('/catalog/index/refresh', { method: 'POST' });
    await catalog.refresh();
    return true;
  } catch {
    await catalog.refresh();
    return false;
  }
}

export async function refreshCatalogOnOpen(): Promise<void> {
  try {
    await authFetch<unknown>('/catalog/refresh', { method: 'POST' });
  } catch {
  }
}
