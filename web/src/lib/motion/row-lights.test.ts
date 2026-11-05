/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

interface FakeBridge {
    value: unknown;
    listeners: ((value: unknown) => void)[];
    read: (field: string, local: () => unknown) => unknown;
    write: (field: string, value: unknown) => Promise<unknown>;
    follow: (field: string, apply: (value: unknown) => void) => () => void;
}

/** Install a fake `PreferenceBridge` holding one value. Inputs: initial. Output: the fake. */
function install(initial: unknown): FakeBridge {
    const fake: FakeBridge = {
        value: initial,
        listeners: [],
        read: (_field, local) => (fake.value === undefined ? local() : fake.value),
        write: async (_field, value) => { fake.value = value; return { status: 'committed' }; },
        follow: (_field, apply) => { fake.listeners.push(apply); return () => {}; },
    };
    (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = fake;
    return fake;
}

async function load() {
    vi.resetModules();
    return await import('./row-lights.svelte');
}

beforeEach(() => { delete (window as { AppBootComplete?: unknown }).AppBootComplete; });
afterEach(() => { delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge; });

test('absent reads on, a stored false reads off, and the cached value shows before hydration', async () => {
    const fake = install(undefined);
    const mod = await load();
    mod.startRowLights();
    expect(mod.rowLights.on).toBe(true);
    fake.value = false;
    mod.startRowLights();
    expect(mod.rowLights.on).toBe(false);
});

test('a change from another device flips the switch live, and a later hydration re-reads', async () => {
    const fake = install(true);
    (window as unknown as { AppBootComplete: unknown }).AppBootComplete = { isComplete: () => false, EVENT: 'boot-x' };
    const mod = await load();
    mod.startRowLights(window);
    expect(fake.listeners).toHaveLength(1);
    fake.listeners[0](false);
    expect(mod.rowLights.on).toBe(false);
    fake.listeners[0](undefined);
    expect(mod.rowLights.on).toBe(true);
    fake.value = false;
    window.dispatchEvent(new Event('boot-x'));
    expect(mod.rowLights.on).toBe(false);
});

test('start is idempotent and a save goes to the shared field', async () => {
    const fake = install(true);
    const mod = await load();
    mod.startRowLights();
    mod.startRowLights();
    expect(fake.listeners).toHaveLength(1);
    expect(await mod.saveRowLights(false)).toBeNull();
    expect(fake.value).toBe(false);
    expect(mod.rowLights.on).toBe(false);
});
