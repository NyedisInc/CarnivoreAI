import { createOverlayHost } from '../manager-frame/overlay-host';

export const AUTOMATIONS_SCREEN_CONTAINER = 'automations-screen';

export const AUTOMATIONS_HASH = '#automations';

const host = createOverlayHost(AUTOMATIONS_SCREEN_CONTAINER, { load: () => import('./AutomationsScreen.svelte') }, AUTOMATIONS_HASH);

export const openAutomationsScreen = (): boolean => host.open();

export const closeAutomationsScreen = (): boolean => host.close();

export const wireAutomationsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
