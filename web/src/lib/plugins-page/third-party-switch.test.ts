/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import ThirdPartySwitch from './ThirdPartySwitch.svelte';
import { sandboxLine, type ThirdPartyStatus } from './third-party-switch';

const t = (key: string, params?: Record<string, unknown> | null): string => (params?.reason ? `${key}|${params.reason}` : key);
const OFF: ThirdPartyStatus = { enabled: false, safe_mode: { env: false, owner: false, active: false }, sandbox: null };
let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; });

async function draw(props: Record<string, unknown>) {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(ThirdPartySwitch, { target, props: { t, ...props } });
    await tick(); await tick();
    flushSync();
    return target;
}

describe('ThirdPartySwitch', () => {
    test('off draws the switch without a sandbox line; turning it on writes true once and shows the probe the server found', async () => {
        const save = vi.fn(async () => ({ ...OFF, enabled: true, sandbox: { ok: false, detail: 'no framework python' } }));
        const root = await draw({ load: async () => OFF, save });
        expect(root.querySelector('[data-third-party-sandbox]')).toBeNull();
        root.querySelector<HTMLElement>('[data-third-party-toggle]')!.click();
        await tick(); await tick();
        flushSync();
        expect(save).toHaveBeenCalledExactlyOnceWith(true);
        expect(root.querySelector('[data-third-party-sandbox="bad"]')?.textContent).toBe('plugins.page.third_party.sandbox.bad|no framework python');
    });

    test('a refused write says so and the switch stays off; safe mode is named', async () => {
        const save = vi.fn(async () => { throw new Error('403'); });
        const root = await draw({ load: async () => ({ ...OFF, safe_mode: { env: true, owner: false, active: true } }), save });
        expect(root.querySelector('[data-third-party-safe]')).not.toBeNull();
        root.querySelector<HTMLElement>('[data-third-party-toggle]')!.click();
        await tick(); await tick();
        flushSync();
        expect(root.querySelector('[data-third-party-failed]')).not.toBeNull();
        expect(root.querySelector('[data-third-party-toggle]')?.getAttribute('aria-checked')).toBe('false');
    });

    test('the sandbox line names unchecked, ready and unavailable apart', () => {
        expect(sandboxLine(OFF).key).toBe('plugins.page.third_party.sandbox.unchecked');
        expect(sandboxLine({ ...OFF, sandbox: { ok: true, detail: '' } }).key).toBe('plugins.page.third_party.sandbox.ok');
        expect(sandboxLine({ ...OFF, sandbox: { ok: false, detail: 'x' } })).toEqual({ key: 'plugins.page.third_party.sandbox.bad', reason: 'x' });
    });
});
