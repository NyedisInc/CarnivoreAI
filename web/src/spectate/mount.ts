
import { mountPanel } from '../lib/mount';
import { relayLinkId } from './spectate-socket';
import SpectatePage from './SpectatePage.svelte';
import type { Component } from 'svelte';

export const SPECTATE_CONTAINER = 'spectate-screen';

const SPECTATE_PANEL = SpectatePage as unknown as Component<
    Record<string, unknown>,
    Record<string, unknown>
>;

export function isSpectatePath(pathname: string | null | undefined): boolean {
    return relayLinkId(pathname) !== null;
}

export function mountSpectateIfNeeded(
    win: (Window & typeof globalThis) | undefined = globalThis.window,
): boolean {
    if (!win || !isSpectatePath(win.location?.pathname)) return false;
    const mounted = mountPanel(SPECTATE_CONTAINER, SPECTATE_PANEL, { host: win });
    return mounted !== null;
}
