import { inNativeShell } from '../native-shell/shell';
import { createOverlayHost } from '../manager-frame/overlay-host';

export const ELITE_SCREEN_CONTAINER = 'elite-screen';

export const ELITE_HASH = '#elite';

const host = createOverlayHost(ELITE_SCREEN_CONTAINER, { load: () => import('./EliteScreen.svelte') }, ELITE_HASH);

export const openEliteScreen = (options: { direct?: boolean } = {}): boolean => (inNativeShell() ? false : host.open({ ...options }));

export const closeEliteScreen = (): boolean => host.close();

export const wireEliteDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
