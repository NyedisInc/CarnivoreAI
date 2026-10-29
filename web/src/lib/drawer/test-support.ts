import { vi } from 'vitest';
import type { DrawerEnv } from './env';

export interface FakeStorage {
    getItem(k: string): string | null;
    setItem(k: string, v: string): void;
    removeItem(k: string): void;
    readonly data: Map<string, string>;
}

export function fakeStorage(seed: Record<string, string> = {}, throws = false): FakeStorage {
    const data = new Map(Object.entries(seed));
    const refuse = (): never => { throw new Error('storage refused'); };
    return {
        data,
        getItem: (k) => (throws ? refuse() : (data.has(k) ? data.get(k) as string : null)),
        setItem: (k, v) => { if (throws) refuse(); data.set(k, String(v)); },
        removeItem: (k) => { if (throws) refuse(); data.delete(k); },
    };
}

export interface FreshDrawer {
    env: DrawerEnv;
    Store: typeof import('./store');
    Keys: typeof import('./store-keys');
    Rebind: typeof import('./store-rebind');
    Arrangement: typeof import('./arrangement');
    Membership: typeof import('./group-membership');
    GroupStore: typeof import('./group-store');
    GroupOrder: typeof import('./group-order');
    Identity: typeof import('./row-identity');
    Asleep: typeof import('./asleep');
    ListingState: typeof import('./listing-state');
    Fetch: typeof import('./fetch');
    Search: typeof import('./search');
    Bucketing: typeof import('./bucketing');
    Sync: typeof import('./sync');
    Density: typeof import('./density');
    Pin: typeof import('./pin');
    ViewClass: typeof import('./view-class');
    Resize: typeof import('./resize');
    Bar: typeof import('./bar');
}

export async function freshDrawer(env: DrawerEnv = { localStorage: fakeStorage() }): Promise<FreshDrawer> {
    vi.resetModules();
    const Env = await import('./env');
    Env.setDrawerEnv(env);
    return {
        env,
        Store: await import('./store'),
        Keys: await import('./store-keys'),
        Rebind: await import('./store-rebind'),
        Arrangement: await import('./arrangement'),
        Membership: await import('./group-membership'),
        GroupStore: await import('./group-store'),
        GroupOrder: await import('./group-order'),
        Identity: await import('./row-identity'),
        Asleep: await import('./asleep'),
        ListingState: await import('./listing-state'),
        Fetch: await import('./fetch'),
        Search: await import('./search'),
        Bucketing: await import('./bucketing'),
        Sync: await import('./sync'),
        Density: await import('./density'),
        Pin: await import('./pin'),
        ViewClass: await import('./view-class'),
        Resize: await import('./resize'),
        Bar: await import('./bar'),
    };
}

/* the bottom bar */
export function versionFooterStub(full: string): Record<string, unknown> {
    return {
        RELEASE_NOTES_URL: 'https://example.test/releases',
        UNKNOWN_TEXT: 'version unknown',
        PREVIEW_TEXT: 'preview',
        readVersionText: () => full,
        shortVersion: (text: string) => ({ text: `v${text}`, preview: false }),
    };
}
