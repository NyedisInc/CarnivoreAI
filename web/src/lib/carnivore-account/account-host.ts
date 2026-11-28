import { createOverlayHost } from '../manager-frame/overlay-host';

export const ACCOUNT_SCREEN_CONTAINER = 'account-screen';

export const ACCOUNT_HASH = '#account';

const host = createOverlayHost(ACCOUNT_SCREEN_CONTAINER, { load: () => import('./AccountPage.svelte') }, ACCOUNT_HASH);

export const openAccountScreen = (): boolean => host.open();

export const closeAccountScreen = (): boolean => host.close();

export const wireAccountDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
