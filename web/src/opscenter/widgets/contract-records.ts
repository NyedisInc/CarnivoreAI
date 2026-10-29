
import { CORE_MANIFESTS } from './core-manifests';
import { declaredGlanceHeight } from './glance-declarations';
import { PRESETS } from '../viz/presets';
import { hasFixture, ownRoutes } from './fixtures';
import { FIXTURE_KINDS } from './fixtures/types';
import { HARNESS_ZONES } from '../../widget-harness/catalog';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import type { WidgetManifest } from './types';

export const CONTRACT_MIN_APP_VERSION = '1.16.1';
export const CONTRACT_AUTHOR = 'Carnivore';
/* pop-out window */
const POPOUT_HOST = 'popout';
const PREFERENCES_ROUTE = 'GET /preferences';

export interface ReadDecl {
  kind: 'route' | 'feed';
  ref: string;
}

export interface WidgetRecord {
  kind: 'widget';
  id: string;
  name: string;
  version: string;
  api_version: 1;
  min_app_version: string;
  author: string;
  tier: 'builtin';
  scope: string[];
  source: 'builtin';
  declarative: false;
  instancing: string;
  sizes: string[];
  any_size: boolean;
  max_per_surface?: number;
  hosts: string[];
  glance?: { height: number };
  reads: ReadDecl[];
  fixtures: string[];
  fixture: string;
  remembers?: string[];
}

export function fixtureKeysOf(id: string): string[] {
  return id === 'core.analytics' ? PRESETS.map((preset) => `core.analytics:${preset.id}`) : [id];
}

const SESSION_ID_SEGMENT = /\/sessions\/(?!(?:list|asleep|recent|records)(?:\/|$))[^/]+/;

export function generalizeRoute(route: string): string {
  return route.replace(SESSION_ID_SEGMENT, '/sessions/{id}').replace(/\/\d+(?=\/|$)/g, '/{id}');
}

export function readRoutesOf(id: string): string[] {
  const ignored = new Set([PREFERENCES_ROUTE]);
  const routes = new Set<string>();
  for (const key of fixtureKeysOf(id)) {
    for (const route of Object.keys(ownRoutes(key, 'data'))) if (!ignored.has(route)) routes.add(generalizeRoute(route));
  }
  return [...routes].sort();
}

export function recordOf(manifest: WidgetManifest): WidgetRecord {
  const id = manifest.id;
  const glance = declaredGlanceHeight(id);
  const shipped = fixtureKeysOf(id).every((key) => hasFixture(key));
  const name = (enCatalog as Record<string, string>)[manifest.titleKey] ?? manifest.titleKey;
  const record: WidgetRecord = {
    kind: 'widget',
    id,
    name,
    version: manifest.version,
    api_version: 1,
    min_app_version: CONTRACT_MIN_APP_VERSION,
    author: CONTRACT_AUTHOR,
    tier: 'builtin',
    scope: manifest.scope === 'session' ? ['global', 'project'] : ['global'],
    source: 'builtin',
    declarative: false,
    instancing: manifest.instancing,
    sizes: [...manifest.fits.sizes],
    any_size: manifest.fits.anySize,
    hosts: [...HARNESS_ZONES, POPOUT_HOST, ...(glance === null ? [] : ['glance'])],
    reads: shipped ? readRoutesOf(id).map((ref) => ({ kind: 'route' as const, ref })) : [],
    fixtures: shipped ? [...FIXTURE_KINDS] : [],
    fixture: id,
  };
  if (manifest.fits.max_per_surface !== undefined) record.max_per_surface = manifest.fits.max_per_surface;
  if (manifest.remembers !== undefined) record.remembers = [...manifest.remembers];
  if (glance !== null) record.glance = { height: glance };
  return record;
}

export function allRecords(): WidgetRecord[] {
  return Object.values(CORE_MANIFESTS).map(recordOf);
}
