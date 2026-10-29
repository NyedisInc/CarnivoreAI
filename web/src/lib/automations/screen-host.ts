import { createOverlayHost } from '../manager-frame/overlay-host';
import AutomationsScreen from './AutomationsScreen.svelte';

export const AUTOMATIONS_SCREEN_CONTAINER = 'automations-screen';

export const AUTOMATIONS_HASH = '#automations';

const host = createOverlayHost(AUTOMATIONS_SCREEN_CONTAINER, AutomationsScreen, AUTOMATIONS_HASH);

export const openAutomationsScreen = (): boolean => host.open();

export const closeAutomationsScreen = (): boolean => host.close();

export const wireAutomationsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
