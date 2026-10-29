import { bootDrawer } from '../../lib/drawer/boot';
import { mountDrawerTabs } from '../../lib/drawer-tabs/mount-drawer-tabs';
import * as Resize from '../../lib/drawer/resize';
import * as Density from '../../lib/drawer/density';
import * as Pin from '../../lib/drawer/pin';
import { widgetArea } from '../../lib/dynamic-tabs/widget-area.svelte';
import { sidebarTabs } from '../../lib/dynamic-tabs/tab-store.svelte';
import { bootListingPush } from '../../lib/listing-push/boot';
import { runSessionCardAction, sessionCardMenuItems } from '../../lib/plugins/session-card-actions';
import { importRealDrawer } from './lab-drawer-import';
import { widthPx, type SidebarView } from './sidebar-state';

export interface DrawnSidebar {
  panel: HTMLElement | null;
  widthPx: number;
}

let mounted = false;

async function mountOnce(): Promise<void> {
  if (mounted) return;
  mounted = true;
  await importRealDrawer();
  await (globalThis as { Preferences?: { hydrate(): Promise<unknown> } }).Preferences?.hydrate();
  const web = ((globalThis as { CloudeWeb?: Record<string, unknown> }).CloudeWeb ??= {});
  web['sessionCardMenuItems'] ??= sessionCardMenuItems;
  web['runSessionCardAction'] ??= runSessionCardAction;
  bootListingPush();
  const ctrl = bootDrawer();
  ctrl.init();
  mountDrawerTabs();
}

export function applySidebarView(view: SidebarView): DrawnSidebar {
  const ctrl = bootDrawer();
  const limits = { min: Resize.MIN_WIDTH_PX, normal: Resize.DEFAULT_WIDTH_PX, max: Resize.maxWidth() };
  const px = Resize.apply(widthPx(view.width, limits));
  Density.setMode(view.density);
  widgetArea.set(sidebarTabs.active(), view.area);
  if (view.folded) ctrl.close({ persist: false });
  else ctrl.open({ persist: false });
  Pin.apply();
  return { panel: document.getElementById('session-sidebar-panel'), widthPx: px };
}

export async function drawSidebar(view: SidebarView): Promise<DrawnSidebar> {
  await mountOnce();
  return applySidebarView(view);
}

export function sidebarClip(): { w: number; h: number } | null {
  const panel = document.getElementById('session-sidebar-panel');
  const rail = document.getElementById('session-sidebar-rail');
  const open = panel && panel.classList.contains('session-sidebar-panel--open') ? panel.getBoundingClientRect() : null;
  const folded = rail && rail.getBoundingClientRect().width > 0 ? rail.getBoundingClientRect() : null;
  const box = open ?? folded;
  return box ? { w: Math.ceil(box.right), h: Math.ceil(box.bottom) } : null;
}
