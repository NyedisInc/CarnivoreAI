import { createOverlayHost } from '../manager-frame/overlay-host';
import EliteScreen from './EliteScreen.svelte';

export const ELITE_SCREEN_CONTAINER = 'elite-screen';

export const ELITE_HASH = '#elite';

const host = createOverlayHost(ELITE_SCREEN_CONTAINER, EliteScreen, ELITE_HASH);

export const openEliteScreen = (options: { direct?: boolean } = {}): boolean => host.open({ ...options });

export const closeEliteScreen = (): boolean => host.close();

export const wireEliteDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
