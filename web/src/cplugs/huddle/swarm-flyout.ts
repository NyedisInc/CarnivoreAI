import { SWARM_FLYOUT, sidebarTabs, sidebarWidgets, tabRegistry, type SidebarWidget } from '../sdk';
import { TASK_MANAGER_TAB } from './huddle-tab-id';

export const swarmFlyout: SidebarWidget = {
  id: SWARM_FLYOUT,
  titleKey: 'sidebar.rail.swarm',
  icon: 'swarm',
  kind: 'registered',
  surface: 'flyout',
  tint: '--oc-green',
  order: 35,
  present: () => {
    const def = tabRegistry.get(TASK_MANAGER_TAB);
    return def !== null && def !== undefined && sidebarTabs.isPresent(def);
  },
  tab: TASK_MANAGER_TAB,
  opensFromTab: true,
  parts: { body: { tab: TASK_MANAGER_TAB } },
};

export function registerSwarmFlyout(registry: typeof sidebarWidgets = sidebarWidgets): void {
  if (!registry.has(swarmFlyout.id)) registry.register(swarmFlyout);
}
