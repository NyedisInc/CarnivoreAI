/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => ({ ...(await importOriginal<object>()), authFetch }));

import FirstRunProfiles from './FirstRunProfiles.svelte';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

const row = (harness: string, installed: boolean) => ({ id: `${harness}-default`, harness, installed });
const mounted: ReturnType<typeof mount>[] = [];
const onContinue = vi.fn();
const q = (sel: string) => document.querySelector(sel) as HTMLElement | null;
const settle = async () => { for (let i = 0; i < 8; i++) await tick(); flushSync(); };
async function render() {
    mounted.push(mount(FirstRunProfiles, { target: document.body, props: { onContinue } }));
    await settle();
}

beforeEach(() => { authFetch.mockReset(); onContinue.mockReset(); });
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

describe('first run launch profile step', () => {
    test('offers the examples of installed agents only, plus the shell', async () => {
        authFetch.mockResolvedValue({ revision: 1, profiles: [row('claude', true), row('codex', false), row('shell', true)] });
        await render();
        const ids = Array.from(document.querySelectorAll('[data-lp-example]')).map((e) => e.getAttribute('data-lp-example'));
        expect(ids).toEqual(['claude_model', 'shell']);
        expect(q('[data-first-run="profiles-found"]')!.textContent).toContain('claude');
        expect(onContinue).not.toHaveBeenCalled();
    });

    test('adding an example posts the profile to the create route with the read revision, then marks it added', async () => {
        authFetch.mockImplementation(async (url: string, init?: RequestInit) => {
            if (init?.method === 'POST') return { revision: 2, profile: {} };
            return { revision: 1, profiles: [row('claude', true)] };
        });
        await render();
        (q('[data-lp-example-use="claude_model"]') as HTMLElement).click();
        await settle();
        const post = authFetch.mock.calls.find((c) => c[1]?.method === 'POST')!;
        expect(post[0]).toBe('/launch-profiles');
        const sent = JSON.parse(post[1].body as string);
        expect(sent.expected_revision).toBe(1);
        expect(sent.profile).toMatchObject({ id: 'claude-with-a-model', harness: 'claude', model: { mode: 'fixed', value: 'sonnet' }, flags: ['--verbose'], default: false });
        expect(q('[data-lp-example-done="claude_model"]')).not.toBeNull();
    });

    test('a list that cannot be read passes straight through to the next step', async () => {
        authFetch.mockRejectedValue(new Error('down'));
        await render();
        expect(onContinue).toHaveBeenCalledTimes(1);
    });

    test('continue leaves the step', async () => {
        authFetch.mockResolvedValue({ revision: 1, profiles: [row('claude', true)] });
        await render();
        (q('[data-first-run="profiles-continue"]') as HTMLElement).click();
        expect(onContinue).toHaveBeenCalledTimes(1);
        expect(t('first_run.profiles.continue')).not.toBe('first_run.profiles.continue');
    });
});
