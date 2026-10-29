import { terminalLayout } from '../engine/layout.svelte';
import { activeTabFor, selectTab, tabsFor } from '../engine/tab-groups.svelte';
import { PRIMARY_SLOT } from '../engine/model';
import { isNonSessionTab } from '../engine/widget-tabs';
import { terminalComponents } from './shape';
import { layoutActive, layoutMode } from './mode.svelte';

export interface TabSource {
  tabs(): string[];
  active(): string;
  select(tab: string): void;
}

function memberTabs(): string[] {
  const seen: string[] = [];
  for (const component of terminalComponents(terminalLayout.state.layout)) {
    for (const tab of tabsFor(terminalLayout, component)) if (!isNonSessionTab(tab) && !seen.includes(tab)) seen.push(tab);
  }
  return seen;
}

export const phoneTabSource: TabSource = {
  tabs(): string[] {
    return layoutActive() ? memberTabs() : tabsFor(terminalLayout, PRIMARY_SLOT).filter((tab) => !isNonSessionTab(tab));
  },
  active(): string {
    if (!layoutActive()) return activeTabFor(terminalLayout, PRIMARY_SLOT);
    return memberTabs().includes(layoutMode.phoneTab) ? layoutMode.phoneTab : PRIMARY_SLOT;
  },
  select(tab: string): void {
    if (!layoutActive()) {
      selectTab(terminalLayout, PRIMARY_SLOT, tab);
      return;
    }
    layoutMode.phoneTab = tab;
  },
};
