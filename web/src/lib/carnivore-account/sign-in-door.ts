import { CATALOG_SESSION_EVENT } from '../drawer-hud/catalog-account.svelte';
import { requireAccount } from './funnel';

export function openSignInDoor(src: string): void {
    void requireAccount({ feature: null, src, resume: () => undefined });
}

export interface SignOutHost {
    signOutOfCatalog(): Promise<unknown>;
    signOutOfAllDevices?(): Promise<unknown>;
}

function globalSignOutHost(): SignOutHost {
    const api = (globalThis as { API?: { signOutOfCatalog?: () => Promise<unknown> } }).API;
    return { signOutOfCatalog: async () => api?.signOutOfCatalog?.() };
}

export async function signOutOfEverywhere(host: SignOutHost = globalAllHost()): Promise<boolean> {
    try {
        await host.signOutOfAllDevices?.();
        return host.signOutOfAllDevices !== undefined;
    } catch (error) {
        console.warn('[account] sign out of all devices failed', error);
        return false;
    } finally {
        window.dispatchEvent(new Event(CATALOG_SESSION_EVENT));
    }
}

function globalAllHost(): SignOutHost {
    const api = (globalThis as { API?: { signOutOfCatalog?: () => Promise<unknown>; signOutOfAllDevices?: () => Promise<unknown> } }).API;
    return { signOutOfCatalog: async () => api?.signOutOfCatalog?.(), signOutOfAllDevices: api?.signOutOfAllDevices ? () => api.signOutOfAllDevices!() : undefined };
}

export async function signOutOfAccount(host: SignOutHost = globalSignOutHost()): Promise<boolean> {
    try {
        await host.signOutOfCatalog();
        return true;
    } catch (error) {
        console.warn('[account] sign out failed', error);
        return false;
    } finally {
        window.dispatchEvent(new Event(CATALOG_SESSION_EVENT));
    }
}
