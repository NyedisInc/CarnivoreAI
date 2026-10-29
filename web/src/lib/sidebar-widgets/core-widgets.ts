import DrawerSearch from '../drawer-tabs/DrawerSearch.svelte';
import DrawerStatsGate from '../drawer-tabs/DrawerStatsGate.svelte';
import SidebarControls from './SidebarControls.svelte';
import { QUESTIONS_TAB } from '../drawer-tabs/drawer-tabs';
import { approvals, questionPending } from '../approvals/approvals.svelte';
import { badgeCount } from '../approvals/approvals-model';
import { sidebarWidgets, type SidebarWidgetRegistry } from './registry';
import type { SidebarWidget } from './types';
import { MENU_FLYOUT, QUESTIONS_FLYOUT, SESSION_LIST_WIDGET, SIDEBAR_STATS_WIDGET } from './widget-ids';

export const sessionListWidget: SidebarWidget = {
  id: SESSION_LIST_WIDGET,
  titleKey: 'sidebar.rail.agents',
  icon: 'bot',
  kind: 'system',
  surface: 'root',
  order: 20,
  parts: {
    search: { component: DrawerSearch },
    controls: { component: SidebarControls },
    tree: { paintedBy: 'drawer-list' },
  },
};

export const sidebarStatsWidget: SidebarWidget = {
  id: SIDEBAR_STATS_WIDGET,
  titleKey: 'drawer.stats.label',
  icon: 'chart',
  kind: 'registered',
  surface: 'strip',
  order: 10,
  parts: {
    bar: { component: DrawerStatsGate },
  },
};

export const menuFlyout: SidebarWidget = {
  id: MENU_FLYOUT,
  titleKey: 'sidebar.rail.menu',
  icon: 'hamburger',
  kind: 'system',
  surface: 'flyout',
  tint: '--oc-text-muted',
  dismissOnOutsideClick: true,
  order: 10,
  tab: 'menu',
  opensFromTab: false,
  parts: { body: { tab: 'menu' } },
};

export const questionsFlyout: SidebarWidget = {
  id: QUESTIONS_FLYOUT,
  titleKey: 'sidebar.rail.questions',
  icon: 'question',
  kind: 'registered',
  surface: 'flyout',
  tint: '--oc-yellow',
  order: 30,
  hiddenUntilData: () => questionPending(),
  badge: () => badgeCount(approvals.items.length),
  tab: QUESTIONS_TAB,
  opensFromTab: true,
  parts: { body: { tab: QUESTIONS_TAB } },
};

export function registerCoreSidebarWidgets(registry: SidebarWidgetRegistry = sidebarWidgets): void {
  for (const widget of [sidebarStatsWidget, sessionListWidget, menuFlyout, questionsFlyout]) {
    if (!registry.has(widget.id)) registry.register(widget);
  }
}
