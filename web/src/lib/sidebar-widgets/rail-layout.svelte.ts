import { untrack } from 'svelte';
import './sidebar-rail.css';
import { mountPanel, unmountPanel } from '../mount';
import { DEFAULT_DRAWER_TAB } from '../drawer-tabs/drawer-tabs';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { tabRegistry } from '../dynamic-tabs/registry';
import * as StatsVisibility from '../drawer/stats-visibility.svelte';
import SidebarRailShell from './SidebarRailShell.svelte';
import SidebarFlyoutHost from './SidebarFlyoutHost.svelte';
import { RAIL_LAYOUT, mountSidebarLayout } from './host';
import { applyRailDom, FLYOUT_CONTAINER_ID, RAIL_CONTAINER_ID } from './rail-dom';
import { closeFlyout, openFlyout } from './flyout.svelte';
import { flyoutForTab } from './rail-model';
import { registerTabFlyouts } from './tab-flyouts';
import { startDrawerTabEffects } from '../drawer-tabs/drawer-tab-effects.svelte';

let stop: (() => void) | null = null;

export function mountRail(doc: Document = document): boolean {
  registerTabFlyouts();
  if (!applyRailDom(doc)) return false;
  mountSidebarLayout(RAIL_LAYOUT, undefined, doc);
  mountPanel(RAIL_CONTAINER_ID, SidebarRailShell);
  mountPanel(FLYOUT_CONTAINER_ID, SidebarFlyoutHost);
  StatsVisibility.init();
  return true;
}

export function unmountRail(): void {
  closeFlyout();
  unmountPanel(RAIL_CONTAINER_ID);
  unmountPanel(FLYOUT_CONTAINER_ID);
}

export function redirectTabToFlyout(tab: string): boolean {
  const widget = flyoutForTab(tab);
  if (!widget) return false;
  if (sidebarTabs.transient === tab) sidebarTabs.leave();
  else if (tabRegistry.get(tab)?.persist) sidebarTabs.select(DEFAULT_DRAWER_TAB);
  if (widget.opensFromTab) openFlyout(widget.id);
  return true;
}

export function startSidebarLayout(): void {
  startDrawerTabEffects();
  if (stop) return;
  mountRail();
  stop = $effect.root(() => {
    $effect(() => {
      const tab = sidebarTabs.active();
      untrack(() => redirectTabToFlyout(tab));
    });
  });
}
