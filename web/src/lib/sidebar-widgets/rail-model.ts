import { sidebarWidgets, type SidebarWidgetRegistry } from './registry';
import { TAB_FLYOUT_PREFIX } from './tab-flyouts';
import type { SidebarWidget } from './types';

export interface RailEntries {
  fixed: SidebarWidget[];
  registered: SidebarWidget[];
}

export function widgetPresent(widget: SidebarWidget): boolean {
  if (widget.present && !widget.present()) return false;
  if (!widget.hiddenUntilData) return true;
  const data = widget.hiddenUntilData();
  return typeof data === 'number' ? data > 0 : data;
}

export function railEntries(registry: SidebarWidgetRegistry = sidebarWidgets): RailEntries {
  const all = registry.all();
  return {
    fixed: all.filter((w) => w.kind === 'system' && (w.surface === 'root' || w.surface === 'flyout')),
    registered: all.filter((w) => w.kind === 'registered' && w.surface === 'flyout' && widgetPresent(w)),
  };
}

export function flyoutForTab(tab: string, registry: SidebarWidgetRegistry = sidebarWidgets): SidebarWidget | null {
  const standIns = registry.all().filter((w) => w.surface === 'flyout' && w.tab === tab);
  return standIns.find((w) => !w.id.startsWith(TAB_FLYOUT_PREFIX)) ?? standIns[0] ?? null;
}
