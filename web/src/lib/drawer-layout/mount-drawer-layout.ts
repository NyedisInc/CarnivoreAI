import type { Component } from 'svelte';
import { mountPanel } from '../mount';
import DrawerZone from '../drawer-zone/DrawerZone.svelte';
import MiniRail from '../mini-rail/MiniRail.svelte';
import DynamicTabBody from '../dynamic-tabs/DynamicTabBody.svelte';
import WidgetAreaBar from '../dynamic-tabs/WidgetAreaBar.svelte';
import { drawerLayout, type DrawerLayout } from './drawer-layout.svelte';
import { DRAWER_AREA_BAR_ID, DRAWER_LEDGER_ID, DRAWER_TABBODY_ID } from '../drawer-tabs/drawer-tabs';

export const DRAWER_MINI_RAIL_ID = 'session-sidebar-rail';

function mountInto<Props extends Record<string, unknown>>(id: string, component: Component<Props, Record<string, unknown>>): void {
  if (document.getElementById(id)) mountPanel(id, component);
}

export function mountDrawerLayout(): DrawerLayout {
  mountInto(DRAWER_TABBODY_ID, DynamicTabBody);
  mountInto(DRAWER_AREA_BAR_ID, WidgetAreaBar);
  mountInto(DRAWER_LEDGER_ID, DrawerZone);
  mountInto(DRAWER_MINI_RAIL_ID, MiniRail);
  return drawerLayout();
}
