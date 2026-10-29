import { createOverlayHost } from '../manager-frame/overlay-host';
import ModsScreen from './ModsScreen.svelte';

export const MODS_SCREEN_CONTAINER = 'mods-screen';

export const MODS_HASH = '#mods';

const host = createOverlayHost(MODS_SCREEN_CONTAINER, ModsScreen, MODS_HASH);

export const openModsScreen = (): boolean => host.open();

export const closeModsScreen = (): boolean => host.close();

export const wireModsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
