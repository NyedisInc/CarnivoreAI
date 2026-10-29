import { createOverlayHost } from '../manager-frame/overlay-host';
import WidgetsScreen from './WidgetsScreen.svelte';

export const WIDGETS_SCREEN_CONTAINER = 'widgets-screen';

export const WIDGETS_HASH = '#widgets';

const host = createOverlayHost(WIDGETS_SCREEN_CONTAINER, WidgetsScreen, WIDGETS_HASH);

export const openWidgetsScreen = (): boolean => host.open();

export const closeWidgetsScreen = (): boolean => host.close();

export const wireWidgetsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
