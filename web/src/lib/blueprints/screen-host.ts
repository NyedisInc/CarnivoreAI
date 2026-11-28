import { createOverlayHost } from '../manager-frame/overlay-host';

export const BLUEPRINTS_SCREEN_CONTAINER = 'blueprints-screen';

export const BLUEPRINTS_HASH = '#blueprints';

const host = createOverlayHost(BLUEPRINTS_SCREEN_CONTAINER, { load: () => import('./BlueprintsScreen.svelte') }, BLUEPRINTS_HASH);

export const openBlueprintsScreen = (): boolean => host.open();

export const closeBlueprintsScreen = (): boolean => host.close();

export const wireBlueprintsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
