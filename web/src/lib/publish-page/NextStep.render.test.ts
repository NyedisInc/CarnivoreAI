/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { createActions } from './actions';
import { parseMine } from './api';
import type { PageHost } from './host';
import NextStep from './NextStep.svelte';
import { createPageStore } from './page-store.svelte';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

let app: Record<string, unknown> | null = null;
afterEach(() => {
    if (app) unmount(app as never);
    app = null;
    document.body.innerHTML = '';
});

const sub = (over: Record<string, unknown>) => ({ submission_id: 'ab12', status: 'pending', gate_state: 'awaiting_approval', kind: 'skill', name: 'notes', version: '1.0.0', created_at: '2026-10-05T00:00:00Z', ...over });

function panel(rows: Record<string, unknown>[], host: Record<string, unknown> = {}) {
    const calls = { mine: vi.fn(async () => parseMine({ submissions: rows })) };
    const fake = {
        mine: calls.mine,
        limits: async () => ({}),
        facts: async () => ({ location: 'skill:notes', declared_version: '1.0.0', changed_files: 0, changed_at: '', made_at: '', sends: [], checks: [] }),
        report: async () => ({ outcome: 'fail', gates: [{ id: 'secrets', verdict: 'fail', code: 'secret_found', fix: '', findings: [{ code: 'secret_found', path: 'run.sh', line: 3 }] }] }),
        ...host,
    } as unknown as PageHost;
    const store = createPageStore({ host: fake, navigate: vi.fn(), t });
    const actions = createActions({ store, host: fake, t });
    store.folders = [{ location: 'skill:notes', kind: 'skill', name: 'notes', harness: 'claude', description: '' }];
    store.mine = parseMine({ submissions: rows });
    store.signedIn = true;
    store.sel = 'skill:notes';
    const target = document.createElement('div');
    document.body.appendChild(target);
    app = mount(NextStep, { target, props: { store, actions, t } as never }) as never;
    flushSync();
    return { store, calls, target };
}
const button = (text: string): HTMLButtonElement => {
    const found = [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === text);
    if (!found) throw new Error(`no button "${text}"`);
    return found as HTMLButtonElement;
};
const click = async (text: string): Promise<void> => {
    button(text).click();
    flushSync();
    await vi.waitFor(() => undefined);
};

describe('the wait view', () => {
    it('"yes, withdraw" calls host.withdraw once, then reloads the rows', async () => {
        const withdraw = vi.fn(async () => undefined);
        const { calls } = panel([sub({})], { withdraw });
        await click('withdraw 1.0.0');
        expect(document.body.textContent).toContain('withdraw 1.0.0? it leaves the review queue.');
        await click('yes, withdraw');
        await vi.waitFor(() => expect(calls.mine).toHaveBeenCalled());
        expect(withdraw).toHaveBeenCalledTimes(1);
        expect(withdraw).toHaveBeenCalledWith('ab12');
    });

    it('"keep it" leaves the confirm without calling anything', async () => {
        const withdraw = vi.fn(async () => undefined);
        panel([sub({})], { withdraw });
        await click('withdraw 1.0.0');
        await click('keep it');
        expect(withdraw).not.toHaveBeenCalled();
        expect(button('withdraw 1.0.0')).toBeTruthy();
    });

    it('withdraw is not offered while the row is publishing', () => {
        panel([sub({ status: 'publishing', gate_state: '' })]);
        expect(document.body.textContent).toContain('nothing to do. a person has said yes');
        expect([...document.querySelectorAll('button')].some((b) => b.textContent?.startsWith('withdraw'))).toBe(false);
    });

    it('a 409 not_withdrawable shows its sentence inline and the panel stays usable', async () => {
        const withdraw = vi.fn(async () => { throw Object.assign(new Error('conflict'), { status: 409, detail: { code: 'not_withdrawable' } }); });
        panel([sub({})], { withdraw });
        await click('withdraw 1.0.0');
        await click('yes, withdraw');
        await vi.waitFor(() => expect(document.querySelector('[role="alert"]')?.textContent).toContain('can no longer be withdrawn'));
        expect(button('yes, withdraw').disabled).toBe(false);
        expect(button('keep it')).toBeTruthy();
    });
});

describe('the appeal form', () => {
    const rejected = [sub({ status: 'rejected', gate_state: '', reason: 'too thin', appeals_left: 2 })];

    it('"send appeal" posts the typed text once', async () => {
        const appeal = vi.fn(async () => undefined);
        panel(rejected, { appeal });
        expect(document.body.textContent).toContain('you have 2 appeals on this one');
        await click('appeal (2 left)');
        const box = document.querySelector('textarea') as HTMLTextAreaElement;
        box.value = 'the reviewer missed the license file';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        await click('send appeal');
        await vi.waitFor(() => expect(appeal).toHaveBeenCalledTimes(1));
        expect(appeal).toHaveBeenCalledWith('ab12', 'the reviewer missed the license file');
    });

    it('the appeal box starts with "please look again." and send is enabled; an emptied box sends that line (X5-50)', async () => {
        const appeal = vi.fn(async () => undefined);
        panel(rejected, { appeal });
        await click('appeal (2 left)');
        const box = document.querySelector('textarea') as HTMLTextAreaElement;
        expect(box.value).toBe('please look again.');
        expect(button('send appeal').disabled).toBe(false);
        box.value = '  ';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        await click('send appeal');
        expect(appeal).toHaveBeenCalledWith('ab12', 'please look again.');
    });

    it('a 409 appeal_limit shows its sentence inline and the form stays usable', async () => {
        const appeal = vi.fn(async () => { throw Object.assign(new Error('conflict'), { status: 409, detail: { code: 'appeal_limit' } }); });
        panel(rejected, { appeal });
        await click('appeal (2 left)');
        const box = document.querySelector('textarea') as HTMLTextAreaElement;
        box.value = 'please look again';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        await click('send appeal');
        await vi.waitFor(() => expect(document.querySelector('[role="alert"]')?.textContent).toContain('the appeal was not sent'));
        expect(button('send appeal').disabled).toBe(false);
        expect(button('cancel')).toBeTruthy();
    });

    it('"check a new version" leaves the appeal for the first step', async () => {
        const { store } = panel(rejected);
        await click('check a new version');
        expect(store.forced['skill:notes']).toBe('ab12');
        expect(document.body.textContent).not.toContain('appeal (2 left)');
    });
});

describe('the first step lead', () => {
    it('a pulled item says why it is back at step 1, and a rejection with no appeals left says its reason', () => {
        panel([sub({ status: 'revoked', gate_state: '', revocation_reason: 'taken back by a reviewer' })]);
        expect(document.querySelector('[data-lead]')?.textContent).toContain('pulled from the store: taken back by a reviewer');
    });

    it('a rejection with no appeals left names the reason', () => {
        panel([sub({ status: 'rejected', gate_state: '', reason: 'too thin', appeals_left: 0 })]);
        expect(document.querySelector('[data-lead]')?.textContent).toContain('too thin');
    });

    it('a withdrawn-only item names its version in the lead (X6-1)', () => {
        panel([sub({ status: 'withdrawn', gate_state: '', version: '1.0.0' })]);
        expect(document.querySelector('[data-lead]')?.textContent).toContain('you withdrew 1.0.0. send it again whenever you like.');
    });

    it('a plain new item has no lead', () => {
        panel([]);
        expect(document.querySelector('[data-lead]')).toBeNull();
    });
});

describe('the fix list', () => {
    it('"i fixed them, try again" runs the check with the typed version', async () => {
        const preview = vi.fn(async () => ({ location: 'skill:notes', name: 'notes', version: '1.0.1', file_count: 1, total_bytes: 1, files: [], refusals: [], lint: {}, cost: {}, compat: {}, digest: 'x', can_send: true }));
        const { store } = panel([sub({ status: 'gate_failed', gate_state: 'failed' })], { preview });
        await vi.waitFor(() => expect(document.body.textContent).toContain('secret_found in run.sh line 3'));
        expect(document.body.textContent).toContain('secrets');
        await click('i fixed them, try again');
        await vi.waitFor(() => expect(preview).toHaveBeenCalledTimes(1));
        expect(preview).toHaveBeenCalledWith({ location: 'skill:notes', version: '1.0.1' });
        expect(store.checks['skill:notes']?.ok).toBe(true);
    });

    it('a refused local check keeps the version it was made for in the field and says to raise it', async () => {
        const { store } = panel([sub({ status: 'revoked', gate_state: '' })]);
        store.facts['skill:notes'] = { location: 'skill:notes', declared_version: '1.0.0', changed_files: 0, changed_at: '', made_at: '', sends: [], checks: [{ version: '1.0.0', ok: false, at: '2026-10-20T00:00:00Z', summary: 'secret_found' }] } as never;
        flushSync();
        await vi.waitFor(() => expect(document.body.textContent).toContain('i fixed them, try again'));
        expect((document.querySelector('input') as HTMLInputElement).value).toBe('1.0.0');
        expect(document.body.textContent).toContain('raise the version');
    });

    it('a version that does not look like 1.0.0 is refused before any call', async () => {
        const preview = vi.fn();
        panel([sub({ status: 'gate_failed', gate_state: 'failed' })], { preview });
        const input = document.querySelector('input') as HTMLInputElement;
        input.value = 'one';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        await click('i fixed them, try again');
        expect(preview).not.toHaveBeenCalled();
        expect(document.body.textContent).toContain('the version must look like 1.0.0');
    });
});
