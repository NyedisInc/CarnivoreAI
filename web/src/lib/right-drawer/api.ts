import {
    closeDrawer,
    drawerDocked,
    drawerHolds,
    openDrawer,
    registerOccupant,
    registerOpener,
    rightDrawer,
    setDrawerWidth,
} from './dock.svelte';

export const rightDrawerApi = {
    register: registerOccupant,
    registerOpener,
    open: openDrawer,
    close: closeDrawer,
    docked: drawerDocked,
    holds: drawerHolds,
    width: (): number => rightDrawer.width,
    setWidth: setDrawerWidth,
} as const;
