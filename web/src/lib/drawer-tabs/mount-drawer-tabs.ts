import '../dynamic-tabs/builtin';
import { mountDrawerLayout } from '../drawer-layout/mount-drawer-layout';
import { DRAWER_LIST_ID } from './drawer-tabs';
import { watchDrawerSurface } from './drawer-surface.svelte';
import { mountDrawerHud } from '../drawer-hud/mount-drawer-hud.svelte';
import { registerCoreSidebarWidgets } from '../sidebar-widgets/core-widgets';
import { railDomApplied } from '../sidebar-widgets/rail-dom';
import { startSidebarLayout } from '../sidebar-widgets/rail-layout.svelte';

let stopWatch: (() => void) | null = null;

export function mountDrawerTabs(): boolean {
    if (typeof document === 'undefined' || typeof document.getElementById !== 'function') return false;
    if (!document.getElementById(DRAWER_LIST_ID)) return false;
    if (!stopWatch) stopWatch = watchDrawerSurface();
    registerCoreSidebarWidgets();
    startSidebarLayout();
    mountDrawerLayout();
    mountDrawerHud();
    return railDomApplied();
}
