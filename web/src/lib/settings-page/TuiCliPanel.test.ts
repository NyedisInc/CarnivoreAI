/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import TuiCliPanel from './TuiCliPanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { CliCommand, CliInstall, CliOutcome, CliState, Fetcher } from './tui-cli/api';

setLocale('en');

const MANUAL = "sudo mkdir -p /usr/local/bin && sudo ln -sfn '/opt/fixture/carnivore' /usr/local/bin/carnivore";
const CHECKOUT = '/opt/fixture/venv/bin/python3 -m src.tui';
const info = (state: CliState): CliCommand => ({
    state, command: 'carnivore tui', link_path: '/usr/local/bin/carnivore', shim_path: '/opt/fixture/carnivore',
    manual_command: MANUAL, run_from_checkout: CHECKOUT,
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});

const settle = async () => {
    await new Promise((resolve) => setTimeout(resolve, 5));
    for (let i = 0; i < 6; i++) await tick();
    flushSync();
};
const q = (sel: string) => document.querySelector(sel);

interface Rig { calls: string[]; release: (r: CliInstall | Error) => void }

async function render(state: CliState, getFails = false): Promise<Rig> {
    const calls: string[] = [];
    let release: Rig['release'] = () => undefined;
    let serving = state;
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${path}`);
        if (path === '/cli-command/install') {
            return new Promise((resolve, reject) => { release = (r) => {
                if (r instanceof Error) reject(r);
                else { serving = r.state; resolve(r); }
            }; });
        }
        if (getFails) throw new ApiError('nope', 500, 'x');
        return info(serving);
    }) as unknown as Fetcher;
    mounted.push(mount(TuiCliPanel, { target: document.body, props: { fetcher } }));
    await settle();
    return { calls, release: (r) => release(r) };
}

describe('TuiCliPanel', () => {
    test('says what it is, lists the steps and shows the screenshot with alt text', async () => {
        await render('installed');
        expect(q('[data-tui="about"]')?.textContent).toContain('full-screen terminal program');
        const steps = [...document.querySelectorAll('[data-tui="steps"] li')].map((li) => li.textContent);
        expect(steps).toHaveLength(4);
        expect(steps[1]).toBe('run carnivore tui.');
        expect(steps[3]).toContain('1 sessions, 2 approvals, 3 ledger, 4 catalog, ? help');
        const shot = q('[data-tui="shot"]') as HTMLImageElement;
        expect(shot.getAttribute('src')).toBe('/static/img/tui/tui-sessions.svg');
        expect(shot.alt.length).toBeGreaterThan(20);
    });

    test('installed shows "installed" and the command, no button', async () => {
        await render('installed');
        expect(q('[data-tui="state"]')?.textContent).toContain('installed');
        expect(q('[data-tui="command"]')?.textContent).toBe('carnivore tui');
        expect(q('[data-tui="install"]')).toBeNull();
    });

    test('installed gives a copyable launch command and where it lives; not installed gives the full path', async () => {
        await render('installed');
        expect(q('[data-tui="launch"]')?.textContent).toBe('carnivore tui');
        expect(q('[data-tui="location"]')?.textContent).toBe('the command is /usr/local/bin/carnivore, linked to /opt/fixture/carnivore.');
        document.body.replaceChildren();
        await render('missing');
        expect(q('[data-tui="launch"]')?.textContent).toBe("'/opt/fixture/carnivore' tui");
        expect(q('[data-tui="location"]')).toBeNull();
    });

    test('the manual command and the checkout command always show, in every state', async () => {
        for (const state of ['installed', 'missing', 'stale', 'foreign'] as CliState[]) {
            document.body.replaceChildren();
            await render(state);
            expect(q('[data-tui="manual"]')?.textContent).toBe(MANUAL);
            expect(q('[data-tui="checkout"]')?.textContent).toBe(CHECKOUT);
        }
    });

    test.each(['missing', 'stale'] as CliState[])('%s shows the install button', async (state) => {
        await render(state);
        expect(q('[data-tui="install"]')).not.toBeNull();
        expect(q('[data-tui="state"]')?.getAttribute('data-tui-state')).toBe(state);
    });

    test('foreign says a different command is in the way and offers no install', async () => {
        await render('foreign');
        expect(q('[data-tui="state"]')?.textContent).toContain('different carnivore command');
        expect(q('[data-tui="foreign"]')?.textContent).toContain('nothing was installed');
        expect(q('[data-tui="install"]')).toBeNull();
    });

    test('a click waits on the admin prompt, then installs and re-reads the state', async () => {
        const rig = await render('missing');
        (q('[data-tui="install"]') as HTMLButtonElement).click();
        await settle();
        expect(rig.calls).toContain('POST /cli-command/install');
        expect(q('[data-tui="waiting"]')?.textContent).toBe('approve the admin prompt on the computer');
        expect((q('[data-tui="install"]') as HTMLButtonElement).disabled).toBe(true);
        rig.release({ outcome: 'installed', state: 'installed', detail: 'ok' });
        await settle();
        expect(q('[data-tui="waiting"]')).toBeNull();
        expect(q('[data-tui="outcome"]')?.textContent).toContain('installed.');
        expect(rig.calls.filter((c) => c === 'GET /cli-command')).toHaveLength(2);
    });

    const OUTCOMES: [CliOutcome, CliState, string][] = [
        ['already_installed', 'installed', 'already installed'],
        ['cancelled', 'missing', 'canceled'],
        ['timed_out', 'missing', 'not answered in time'],
        ['foreign', 'foreign', 'different carnivore command'],
        ['failed', 'missing', 'install failed'],
    ];
    test.each(OUTCOMES)('outcome %s is told in plain lowercase copy', async (outcome, state, words) => {
        const rig = await render('missing');
        (q('[data-tui="install"]') as HTMLButtonElement).click();
        await settle();
        rig.release({ outcome, state, detail: 'x' });
        await settle();
        const text = q('[data-tui="outcome"]')?.textContent ?? '';
        expect(text).toContain(words);
        expect(text).toBe(text.toLowerCase());
        expect(q('[data-tui="state"]')?.getAttribute('data-tui-state')).toBe(state);
        expect(q('[data-tui="install"]') === null).toBe(state === 'installed' || state === 'foreign');
    });

    test('a failed read shows the problem, a failed install shows failed plus the problem', async () => {
        await render('missing', true);
        expect(q('[data-tui="problem"]')?.textContent?.trim()).toBe('nope');
        document.body.replaceChildren();
        const rig = await render('missing');
        (q('[data-tui="install"]') as HTMLButtonElement).click();
        await settle();
        rig.release(new ApiError('server said no', 500, 'x'));
        await settle();
        expect(q('[data-tui="outcome"]')?.getAttribute('data-tui-outcome')).toBe('failed');
        expect(q('[data-tui="problem"]')?.textContent?.trim()).toBe('server said no');
    });
});
