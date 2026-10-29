/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { realWelcomeDeps, runWelcome, type WelcomeDeps } from './open-welcome';
import { WELCOME_FIELD } from './welcome-flag';

const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
let stored: Record<string, unknown> = {};
let writes: Array<[string, unknown]> = [];

function deps(over: Partial<WelcomeDeps> = {}): WelcomeDeps & { signIn: ReturnType<typeof vi.fn> } {
    return { ...realWelcomeDeps(), loadAccount: async () => {}, signedIn: () => false, signIn: vi.fn(), ...over } as never;
}

beforeEach(() => {
    stored = {};
    writes = [];
    (globalThis as Record<string, unknown>).Preferences = { HYDRATED: 'hydrated', status: () => 'hydrated' };
    (globalThis as Record<string, unknown>).PreferenceBridge = {
        read: (field: string) => stored[field] ?? null,
        write: async (field: string, value: unknown) => {
            writes.push([field, value]);
            stored[field] = value;
            return { status: 'committed' };
        },
    };
});
afterEach(() => {
    document.body.innerHTML = '';
    delete (globalThis as Record<string, unknown>).Preferences;
    delete (globalThis as Record<string, unknown>).PreferenceBridge;
});

describe('the one-time welcome', () => {
    it('shows when unset and signed out, and sign in writes the flag and opens the funnel', async () => {
        const d = deps();
        const run = runWelcome(d);
        await settle();
        expect(document.querySelector('[data-welcome-modal]')).not.toBeNull();
        (document.querySelector('[data-welcome-signin]') as HTMLElement).click();
        expect(await run).toBe('shown');
        expect(writes).toEqual([[WELCOME_FIELD, true]]);
        expect(d.signIn).toHaveBeenCalledOnce();
    });

    it('not now writes the flag and does not open the funnel', async () => {
        const d = deps();
        const run = runWelcome(d);
        await settle();
        (document.querySelector('[data-welcome-later]') as HTMLElement).click();
        await run;
        expect(writes).toEqual([[WELCOME_FIELD, true]]);
        expect(d.signIn).not.toHaveBeenCalled();
    });

    it('shows nothing when the flag is already true', async () => {
        stored[WELCOME_FIELD] = true;
        expect(await runWelcome(deps())).toBe('skipped');
        expect(document.querySelector('[data-welcome-modal]')).toBeNull();
        expect(writes).toEqual([]);
    });

    it('shows nothing before the preferences are hydrated', async () => {
        (globalThis as typeof globalThis & { Preferences: { status: () => string } }).Preferences.status = () => 'not_hydrated';
        expect(await runWelcome(deps())).toBe('skipped');
        expect(document.querySelector('[data-welcome-modal]')).toBeNull();
    });

    it('signed in writes the flag silently and shows nothing', async () => {
        expect(await runWelcome(deps({ signedIn: () => true }))).toBe('skipped');
        expect(document.querySelector('[data-welcome-modal]')).toBeNull();
        expect(writes).toEqual([[WELCOME_FIELD, true]]);
    });
});
