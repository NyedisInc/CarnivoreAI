/* and the real the real left sidebar */
import { ago } from './clock';
import type { FixtureKind, RouteTable } from './types';

const COMPANIES = [
  { id: 1, name: 'northwind', project_count: 3, has_image: false, image_rev: null, hue: null, parent_id: null, hq_project_id: 1 },
  { id: 2, name: 'side projects', project_count: 1, has_image: false, image_rev: null, hue: null, parent_id: null, hq_project_id: null },
];

export function companyOfProject(projectId: number): number {
  return projectId === 4 ? 2 : 1;
}

export function companyName(id: number): string | null {
  return COMPANIES.find((one) => one.id === id)?.name ?? null;
}

export const SHELL_AMBIENT_ROUTES: ReadonlySet<string> = new Set([
  'GET /browsers/pages', 'GET /pack/machines', 'GET /pack/tracks-master', 'GET /pack/relay', 'GET /pack/relay-consent', 'GET /computers', 'GET /hosts',
  'GET /swarm/switch', 'GET /swarm/roster', 'GET /alerts', 'GET /automations', 'GET /automations/runs', 'GET /features', 'GET /cplugs/huddle',
  'GET /cplugs/huddle/lists', 'GET /cplugs/huddle/aggregate', 'GET /catalog/items', 'GET /item-settings',
]);

const SHELL_ONLY_ROUTES: readonly string[] = ['GET /layouts', 'GET /toasts/history', 'GET /themes', 'GET /sessions/recent', 'GET /sessions/listing', 'GET /provider-ledger'];

export function isShellRoute(route: string): boolean {
  return SHELL_AMBIENT_ROUTES.has(route) || SHELL_ONLY_ROUTES.includes(route) || route in appWorldRoutes('data');
}

export function appWorldRoutes(kind: FixtureKind): RouteTable {
  const empty = kind === 'empty';
  return {
    'GET /companies': { companies: empty ? [] : COMPANIES },
    'GET /catalog/auth/session': { signed_in: false, login: null, provider: null, email: null },
    'GET /browsers': { browsers: [] },
    'GET /files/open': { files: [] },
    'GET /sidebar/row-looks': { looks: {} },
    'GET /approvals': { items: [], version: 0 },
    'GET /auto-sleep': {
      enabled: false, idle_minutes: 60, unread_blocks_sleep: true, unread_idle_minutes: 240, min_idle_minutes: 5, max_idle_minutes: 1440,
      keep_awake: [], keep_awake_session_uuids: [],
    },
    'GET /provider-ledger': { accounts: [], total: { accounts: 0, windows: [] }, loop: { alive: true, last_pass_at: ago(40) } },
    'GET /provider-ledger/switch': { auto_switch: false, threshold_percent: 90, active: [], last_switch: null, restarts_running_sessions: false },
    'GET /provider-ledger/accounts': [],
  };
}
