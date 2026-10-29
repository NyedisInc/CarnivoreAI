import { mountPanel } from '../mount';
import { DRAWER_LIST_ID, DRAWER_SEARCH_ID, DRAWER_STATS_ID } from '../drawer-tabs/drawer-tabs';
import { sidebarWidgets, type SidebarWidgetRegistry } from './registry';
import { isMountedPart } from './types';
import { SESSION_LIST_WIDGET, SIDEBAR_STATS_WIDGET } from './widget-ids';

export const SIDEBAR_TOPBAR_CONTROLS_ID = 'session-sidebar-topbar-controls';

export type SidebarSlot = `${string}.${string}`;

export type SidebarLayout = Readonly<Record<SidebarSlot, string>>;

export const RAIL_LAYOUT: SidebarLayout = Object.freeze({
  [`${SIDEBAR_STATS_WIDGET}.bar`]: DRAWER_STATS_ID,
  [`${SESSION_LIST_WIDGET}.search`]: DRAWER_SEARCH_ID,
  [`${SESSION_LIST_WIDGET}.controls`]: SIDEBAR_TOPBAR_CONTROLS_ID,
  [`${SESSION_LIST_WIDGET}.tree`]: DRAWER_LIST_ID,
});

export interface SidebarMountReport {
  mounted: SidebarSlot[];
  painted: SidebarSlot[];
  missing: SidebarSlot[];
}

export function mountSidebarLayout(
  layout: SidebarLayout,
  registry: SidebarWidgetRegistry = sidebarWidgets,
  doc: Document = document,
): SidebarMountReport {
  const report: SidebarMountReport = { mounted: [], painted: [], missing: [] };
  for (const widget of registry.all()) {
    for (const [name, part] of Object.entries(widget.parts)) {
      const slot: SidebarSlot = `${widget.id}.${name}`;
      const containerId = layout[slot];
      if (!containerId) continue;
      if (!doc.getElementById(containerId)) {
        report.missing.push(slot);
        continue;
      }
      if (!isMountedPart(part)) {
        report.painted.push(slot);
        continue;
      }
      if (mountPanel(containerId, part.component)) report.mounted.push(slot);
      else report.missing.push(slot);
    }
  }
  return report;
}
