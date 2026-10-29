/* running sessions */
import { createOverlayHost } from '../manager-frame/overlay-host';
import { closeMenuPagesExcept } from '../menu-page/menu-page-shell.svelte';
import SessionsScreen from './SessionsScreen.svelte';

export const SESSIONS_SCREEN_CONTAINER = 'sessions-screen';

export const SESSIONS_HASH = '#sessions';
export const LEGACY_PROJECTS_HASH = '#projects';

const sessionsHost = createOverlayHost(SESSIONS_SCREEN_CONTAINER, SessionsScreen, SESSIONS_HASH, {
    aliases: [LEGACY_PROJECTS_HASH],
});

export function openSessionsScreen(): boolean {
    closeMenuPagesExcept(null);
    return sessionsHost.open();
}

export const closeSessionsScreen = (): boolean => sessionsHost.close();

export const unmountSessionsScreen = (): boolean => sessionsHost.unmount();

export const isSessionsHash = (hash: string | null | undefined): boolean => sessionsHost.isHash(hash);

export const wireSessionsDeepLinks = (target?: Window | null): (() => void) => sessionsHost.wireDeepLink(target);
