import type { HarnessWidget } from '../../../widget-harness/catalog';
import { toStored, type ZoneItem } from '../../../lib/drawer-zone/zone-model';
import { asleepRecords, attachableRows, companionList, liveRecords, projectList, recentRecords, sessionList } from './made-up';
import { appWorldRoutes, companyName, companyOfProject } from './app-world';
import type { FixtureKind, RouteTable } from './types';

const COLLECTIONS = ['list', 'attachable', 'records', 'asleep', 'companions', 'recent'] as const;

function collection(rows: unknown[]): Record<string, unknown> {
  return { rows, ok: true, status: null, detail: null, meta: {} };
}

function filedProjects(): unknown[] {
  return (projectList() as { id: number }[]).map((project) => ({ ...project, company_id: companyOfProject(project.id), company_name: companyName(companyOfProject(project.id)) }));
}

function sessionRoutes(kind: FixtureKind): Record<string, unknown> {
  const empty = kind === 'empty';
  return {
    'GET /sessions/list': empty ? [] : sessionList(),
    'GET /sessions/attachable': empty ? [] : attachableRows(),
    'GET /sessions/records': empty ? [] : liveRecords(),
    'GET /sessions/asleep': empty ? [] : asleepRecords(),
    'GET /sessions/companions': empty ? [] : companionList(),
    'GET /sessions/recent': empty ? [] : recentRecords(),
    'GET /projects': empty ? [] : filedProjects(),
  };
}

export function sidebarRoutes(kind: FixtureKind): RouteTable {
  const routes = sessionRoutes(kind);
  return { ...routes, 'GET /sessions/listing': listingSnapshot(routes) };
}

export function listingSnapshot(routes: RouteTable): { stream: string; seq: number; collections: Record<string, unknown> } {
  const collections: Record<string, unknown> = {};
  for (const name of COLLECTIONS) {
    const rows = routes[`GET /sessions/${name}`];
    collections[name] = collection(Array.isArray(rows) ? rows : []);
  }
  return { stream: 'lab-fixture', seq: 1, collections };
}

export function sidebarTable(widget: RouteTable, kind: FixtureKind, placed: HarnessWidget | null = null): RouteTable {
  return { ...appWorldRoutes(kind), ...widget, ...sidebarRoutes(kind), ...(placed ? { 'GET /preferences': areaPreferences(placed) } : {}) };
}

function areaPreferences(placed: HarnessWidget): Record<string, unknown> {
  const item: ZoneItem = placed.target ? { widget: placed.manifest, look: null, target: placed.target } : { widget: placed.manifest, look: null };
  return { status: 'unchanged', schema_version: 1, revision: 1, values: { drawer_zone: toStored([item]) } };
}
