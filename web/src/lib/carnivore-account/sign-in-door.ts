import { CATALOG_SESSION_EVENT } from '../drawer-hud/catalog-account.svelte';
import type { AccountFeature } from './features';
import { requireAccount } from './funnel';

export function openSignInDoor(src: string): void {
    void requireAccount({ feature: '' as AccountFeature, src, resume: () => undefined });
}

export async function signOutOfAccount(): Promise<void> {
    const api = (globalThis as { API?: { signOutOfCatalog?: () => Promise<unknown> } }).API;
    try {
        await api?.signOutOfCatalog?.();
    } finally {
        window.dispatchEvent(new Event(CATALOG_SESSION_EVENT));
    }
}
