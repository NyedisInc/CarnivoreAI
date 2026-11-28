import { createOverlayHost } from '../manager-frame/overlay-host';

export const MODS_SCREEN_CONTAINER = 'mods-screen';

export const MODS_HASH = '#mods';

const host = createOverlayHost(MODS_SCREEN_CONTAINER, { load: () => import('./ModsScreen.svelte') }, MODS_HASH);

export const closeModsScreen = (): boolean => host.close();

export const wireModsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
