import { createOverlayHost } from '../manager-frame/overlay-host';
import BlueprintsScreen from './BlueprintsScreen.svelte';

export const BLUEPRINTS_SCREEN_CONTAINER = 'blueprints-screen';

export const BLUEPRINTS_HASH = '#blueprints';

const host = createOverlayHost(BLUEPRINTS_SCREEN_CONTAINER, BlueprintsScreen, BLUEPRINTS_HASH);

export const openBlueprintsScreen = (): boolean => host.open();

export const closeBlueprintsScreen = (): boolean => host.close();

export const unmountBlueprintsScreen = (): boolean => host.unmount();

export const isBlueprintsHash = (hash: string | null | undefined): boolean => host.isHash(hash);

export const wireBlueprintsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
