
import { mountPanel } from '../lib/mount';
import { relayLinkId } from './spectate-socket';
import type { Component } from 'svelte';

export const SPECTATE_CONTAINER = 'spectate-screen';

export function isSpectatePath(pathname: string | null | undefined): boolean {
    return relayLinkId(pathname) !== null;
}

export function mountSpectateIfNeeded(
    win: (Window & typeof globalThis) | undefined = globalThis.window,
): boolean {
    if (!win || !isSpectatePath(win.location?.pathname)) return false;
    if (typeof document === 'undefined' || !document.getElementById(SPECTATE_CONTAINER)) return false;
    void import('./SpectatePage.svelte').then(({ default: SpectatePage }) => {
        const panel = SpectatePage as unknown as Component<Record<string, unknown>, Record<string, unknown>>;
        mountPanel(SPECTATE_CONTAINER, panel, { host: win });
    });
    return true;
}
