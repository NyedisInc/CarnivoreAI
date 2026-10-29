import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { AgentMarkFacts } from '../sessions/agent-marks';
import type { SidebarRow } from '../sidebar-shell/legacy';

interface StatusSummaryGlobal {
  summaryHtml?: (children: unknown[]) => string;
}
import { orderBand } from '../drawer/arrangement';
import { DEFAULT_PAGE_SECTION_ICON, PAGE_SECTION_SLOT, pageSectionMeta } from '../drawer/page-sections';
import { previewOrder, resolveSectionOrder, type SectionId } from '../drawer/section-order';
import { current as arrangementNow } from '../drawer/store';
import {
  BAND_BROWSERS, BAND_FILES, BAND_TERMINALS, bands as drawerBands, isBrowserBand, isFileRow, labelFor, pageSectionIds, pageSectionRows, projectBuckets, sortProjectsAlpha, terminalRows,
} from '../drawer/bucketing';
import { buildRowPlan } from '../sidebar-shell/row-plan';
import type { RowHost } from '../sidebar-shell/row-host';

export type RailSectionId = 'pinned' | 'layouts' | 'groups' | 'projects' | 'terminals' | 'browsers' | 'files';

export type RailIconId = RailSectionId | (string & {});

export interface RailSection {
  id: RailIconId;
  glyph: string;
  labelKey: string;
  nodes: MenuNode[];
}

export interface RailInputs {
  rows: SidebarRow[];
  host: RowHost;
  open: (name: string, attrs: Record<string, string | undefined>) => void;
  asleepLabel: string;
}

const GLYPHS: Readonly<Record<RailSectionId, string>> = {
  pinned: 'pin',
  layouts: 'grid',
  groups: 'users',
  projects: 'folder-tree',
  terminals: 'terminal',
  browsers: 'globe',
  files: 'code',
};

const DRAWER_SECTION: Readonly<Record<RailSectionId, SectionId>> = {
  pinned: 'pinned', layouts: 'layouts', groups: 'groups', projects: 'companies', terminals: 'terminals', browsers: 'browsers',
  files: 'browsers',
};

export function rowNode(r: SidebarRow, band: string, ctx: Pick<RailInputs, 'host' | 'open' | 'asleepLabel'>): MenuNode {
  const plan = buildRowPlan(r, 'compact', band, null, ctx.host);
  if (plan.type === 'legacy') {
    const summary = (globalThis as { SessionStatusSummary?: StatusSummaryGlobal }).SessionStatusSummary;
    const aggregateLightHtml = r.kind === 'layout' && summary?.summaryHtml
      ? summary.summaryHtml(Array.isArray(r._members) ? (r._members as unknown[]) : [])
      : undefined;
    return {
      id: `${band}/${r.name}`, label: String((r.label as string | undefined) || r.name),
      ...(aggregateLightHtml ? { aggregateLightHtml } : {}),
      run: () => ctx.open(r.name, { 'data-name': r.name }),
    };
  }
  const attrs = plan.attrs as Record<string, string | undefined>;
  const led = plan.type === 'session' ? plan.led : null;
  const agent: AgentMarkFacts | undefined = led
    ? { family: (r.agent_family as string | undefined) ?? null, ...led, status: r.asleep ? 'asleep' : led.status }
    : undefined;
  return {
    id: `${band}/${r.name}`,
    label: plan.name.text,
    ...(agent ? { agent } : {}),
    ...(r.asleep ? { badge: ctx.asleepLabel } : {}),
    run: () => ctx.open(r.name, attrs),
  };
}

function drawerSectionOf(id: RailIconId): SectionId {
  return (DRAWER_SECTION as Record<string, SectionId>)[id] ?? PAGE_SECTION_SLOT;
}

export function buildRailSections(input: RailInputs): RailSection[] {
  const { rows } = input;
  const order = (key: string, list: SidebarRow[]): SidebarRow[] => orderBand(key, list);
  const leaves = (key: string, list: SidebarRow[]): MenuNode[] => order(key, list).map((r) => rowNode(r, key, input));
  const out: RailSection[] = [];
  const add = (id: RailSectionId, nodes: MenuNode[]): void => {
    if (nodes.length) out.push({ id, glyph: GLYPHS[id], labelKey: `drawer.rail.${id}`, nodes });
  };
  const addPageSection = (id: string): void => {
    const meta = pageSectionMeta(id);
    const nodes = leaves(id, pageSectionRows(rows, id));
    if (nodes.length) out.push({ id, glyph: meta?.icon ?? DEFAULT_PAGE_SECTION_ICON, labelKey: meta?.labelKey ?? id, nodes });
  };
  const bands = drawerBands(rows).filter((b) => b.rows.length);
  const pinned = bands.find((b) => b.key === 'pinned');
  add('pinned', pinned ? leaves('pinned', pinned.rows) : []);
  add('layouts', leaves('layouts', rows.filter((r) => r.kind === 'layout')));
  add('groups', bands.filter((b) => b.key !== 'pinned').map((b) => ({
    id: b.key, label: labelFor(b.key), children: leaves(b.key, b.rows),
  })));
  // rogue agents
  const projects = projectBuckets(rows);
  add('projects', [...sortProjectsAlpha(projects.filter((b) => b.isProject)), ...projects.filter((b) => !b.isProject)].map((b) => ({
    id: b.key, label: b.label, children: leaves(b.key, b.rows),
  })));
  add('terminals', leaves(BAND_TERMINALS, terminalRows(rows)));
  add('browsers', leaves(BAND_BROWSERS, rows.filter(isBrowserBand)));
  add('files', leaves(BAND_FILES, rows.filter(isFileRow)));
  for (const id of pageSectionIds(rows)) addPageSection(id);
  const sections = previewOrder() ?? resolveSectionOrder(arrangementNow().sections);
  return out.sort((a, b) => sections.indexOf(drawerSectionOf(a.id)) - sections.indexOf(drawerSectionOf(b.id)));
}
