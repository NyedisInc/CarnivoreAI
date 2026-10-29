import type { FixtureKind, RouteTable } from './types';

export const AMBIENT_ROUTES: ReadonlySet<string> = new Set([
  'GET /auto-sleep',
  'GET /catalog/items',
  'GET /item-settings',
  'GET /layouts',
  'GET /provider-ledger',
  'GET /provider-ledger/switch',
  'GET /sessions/recent',
  'GET /toasts/history',
]);

export function common(kind: FixtureKind): RouteTable {
  void kind;
  return {
    'GET /preferences': { status: 'unchanged', schema_version: 1, revision: 1, values: {} },
    'GET /sessions/list': [],
    'GET /sessions/asleep': [],
    'GET /projects': [],
    'GET /themes': [],
  };
}
