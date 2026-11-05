/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => undefined }) }));

import BeastGridPanel from './BeastGridPanel.svelte';
import BeastSwitchStrip from './BeastSwitchStrip.svelte';
import { beastStatus, type BeastStatus } from './control.svelte';
import { gridMatrix } from './grid-model';
import { RULES } from './grid-fixture';
import type { authFetch } from '../../opscenter/api/auth.svelte';

const t = (key: string): string => key;
let mounted: ReturnType<typeof mount> | null = null;
const calls: { path: string; init?: RequestInit }[] = [];
const fetcher = (async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    return path === '/beast-mode/rules' ? RULES : beastStatus.data;
}) as unknown as typeof authFetch;

const ARMED: BeastStatus = { enabled: true, prompts: false, since: '2026-11-02T10:00:00+00:00', until: null, pending_count: 0 };

beforeEach(() => { calls.length = 0; beastStatus.data = { enabled: false, since: null, pending_count: 0 }; });
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

function strip(onArm = vi.fn(async () => undefined)): ReturnType<typeof vi.fn> {
    mounted = mount(BeastSwitchStrip, { target: document.body, props: { t, fetcher, onArm } });
    return onArm;
}
const q = (sel: string): HTMLElement | null => document.querySelector(sel);

describe('beast switch strip', () => {
    test('disarmed it shows off and an arm button that opens the shared popup, with no live controls', async () => {
        const onArm = strip();
        expect(q('[data-beast-strip]')!.getAttribute('data-beast-strip')).toBe('off');
        expect(q('[data-beast-strip-prompts]')).toBeNull();
        expect(q('[data-beast-strip-auto-off]')).toBeNull();
        q('[data-beast-strip-arm]')!.click();
        await vi.waitFor(() => expect(onArm).toHaveBeenCalledTimes(1));
        expect(calls).toEqual([]);
    });

    test('armed it shows the state, a disarm button and both live controls', () => {
        beastStatus.data = ARMED;
        strip();
        expect(q('[data-beast-strip]')!.getAttribute('data-beast-strip')).toBe('on');
        expect(q('[data-beast-strip-state]')!.textContent).toContain('beast.strip.on_open');
        expect(q('[data-beast-strip-disarm]')).not.toBeNull();
        expect(q('[data-beast-strip-arm]')).toBeNull();
        expect(q('[data-beast-strip-prompts]')!.getAttribute('aria-checked')).toBe('false');
        expect((q('[data-beast-strip-auto-off]') as HTMLSelectElement).value).toBe('');
    });

    test('the prompts toggle patches only prompts', async () => {
        beastStatus.data = ARMED;
        strip();
        q('[data-beast-strip-prompts]')!.click();
        await vi.waitFor(() => expect(calls.some((c) => c.init?.method === 'PATCH')).toBe(true));
        const patch = calls.find((c) => c.init?.method === 'PATCH')!;
        expect(patch.path).toBe('/beast-mode');
        expect(JSON.parse(String(patch.init!.body))).toEqual({ prompts: true });
    });

    test('the auto-off choice patches hours, and "until i turn it off" sends null', async () => {
        beastStatus.data = { ...ARMED, until: new Date(Date.now() + 3.9 * 3_600_000).toISOString() };
        strip();
        const select = q('[data-beast-strip-auto-off]') as HTMLSelectElement;
        await vi.waitFor(() => expect(select.value).toBe('4'));
        select.value = '8';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        await vi.waitFor(() => expect(calls.length).toBeGreaterThan(0));
        expect(JSON.parse(String(calls[0]!.init!.body))).toEqual({ hours: 8 });
        await vi.waitFor(() => expect(select.disabled).toBe(false));
        select.value = '';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        await vi.waitFor(() => expect(calls.filter((c) => c.init?.method === 'PATCH').length).toBe(2));
        expect(JSON.parse(String(calls.filter((c) => c.init?.method === 'PATCH')[1]!.init!.body))).toEqual({ hours: null });
    });

    test('a refusal from the route is shown under the strip', async () => {
        beastStatus.data = ARMED;
        const failing = (async () => { throw new Error('beast mode is not armed'); }) as unknown as typeof authFetch;
        mounted = mount(BeastSwitchStrip, { target: document.body, props: { t, fetcher: failing } });
        q('[data-beast-strip-prompts]')!.click();
        await vi.waitFor(() => expect(q('.beast-strip__problem')).not.toBeNull());
        flushSync();
    });
});

describe('prompt rows note', () => {
    test('only the two prompt rows get the muted note, and only when asked', () => {
        const noted = gridMatrix(RULES, true).rows.filter((r) => r.noteKey).map((r) => r.labelKey);
        expect(noted).toEqual(['beast.settings.row.claude_permission', 'beast.settings.row.codex_approval']);
        expect(gridMatrix(RULES).rows.some((r) => r.noteKey)).toBe(false);
    });

    test('the panel draws the note while armed without prompts, and not once prompts are on', async () => {
        beastStatus.data = ARMED;
        mounted = mount(BeastGridPanel, { target: document.body, props: { t, fetcher } });
        await vi.waitFor(() => expect(q('[data-settings-matrix]')).not.toBeNull());
        expect(document.querySelectorAll('[data-matrix-note]').length).toBe(2);
        beastStatus.data = { ...ARMED, prompts: true };
        flushSync();
        await vi.waitFor(() => expect(document.querySelectorAll('[data-matrix-note]').length).toBe(0));
    });
});
