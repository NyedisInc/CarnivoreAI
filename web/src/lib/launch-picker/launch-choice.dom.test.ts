/** @vitest-environment jsdom */
import { afterEach, beforeAll, describe, expect, test } from 'vitest';

import { openModal } from '../modal';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import LaunchPickerModal from './LaunchPickerModal.svelte';
import { mountLaunchChoice } from './open';
import { summaryOf } from './account-model';
import { answerFor, enrichRows, initialSelection, rowsFromProfiles, type PickerRow } from './picker-model';
import type { LaunchProfilesApi, ProfileRow } from '../launch-profiles-page/api';

const i18n = createI18n({ locale: 'en' }) as { t(k: string, p?: Record<string, unknown> | null): string };
const t = (k: string, p?: Record<string, unknown> | null): string => i18n.t(k, p);

function row(id: string, harness: string, extra: Partial<ProfileRow> = {}): ProfileRow {
    return {
        id, harness, label: id, icon: null, description: null, default: false,
        account: { mode: 'follow_active', account_id: null }, endpoint: { mode: 'native', connection_id: null },
        model: { mode: 'default', value: null }, permissions: 'harness_default', flags: [], env: [], secrets: [],
        shell_profile: true, before_launch: null, custom_command: null, custom_command_ack_no_args: false,
        summary: { permissions_badge: 'default permissions', model: 'default', account: 'follow_active', endpoint: 'native' },
        ...extra,
    } as ProfileRow;
}

const words = { followActive: 'active account', modelDefault: 'default model', modelAsk: 'model asked at launch' };
const PROFILES: ProfileRow[] = [
    row('claude-main', 'claude', { default: true }),
    row('claude-work', 'claude', { account: { mode: 'pinned', account_id: 'work' }, model: { mode: 'fixed', value: 'opus' } }),
    row('claude-router', 'claude', { model: { mode: 'ask', value: null }, endpoint: { mode: 'connection', connection_id: 'or' }, permissions: 'skip_all',
        summary: { permissions_badge: 'skips all permission checks', model: 'ask', account: 'follow_active', endpoint: 'or' } }),
    row('codex-yolo', 'codex', { default: true }),
];

const fakeApi = {
    list: async () => ({ revision: 1, profiles: PROFILES }),
    accounts: async () => [{ id: 'work', name: 'work account', provider: 'claude' }],
    models: async () => [{ id: 'anthropic/x', label: 'x' }],
    launchAccounts: async () => ({ options: [{ id: 'work', name: 'work' }, { id: 'play', name: 'play' }], selected_id: 'work', pinned: false }),
} as unknown as LaunchProfilesApi;
async function pickProfile(id: string): Promise<void> {
    (document.querySelector('[data-choice="launch-profile"] [data-choice-trigger]') as HTMLElement).click();
    await settle();
    (document.querySelector(`[data-choice-option="${id}"]`) as HTMLElement).click();
    await settle();
}


const api = {
    list: async () => ({ revision: 1, profiles: [row('claude-main', 'claude', { default: true }), row('codex-yolo', 'codex', { default: true })] }),
    accounts: async () => [],
    models: async () => [],
    launchAccounts: async () => ({ options: [{ id: 'work', name: 'work' }, { id: 'play', name: 'play' }], selected_id: 'work', pinned: false }),
} as unknown as LaunchProfilesApi;

async function settle(): Promise<void> { for (let i = 0; i < 12; i += 1) await Promise.resolve(); }
const q = <E extends HTMLElement>(sel: string): E => document.querySelector(sel) as E;
const key = (el: Element, k: string): void => { el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true })); };
const trigger = (which: string): HTMLElement => q(`[data-choice="${which}"] [data-choice-trigger]`);

const CLASSIC_SCRIPTS = import.meta.glob(['../../../../client/js/agent-family-icon.js', '../../../../client/js/wrapper-mark.js']);
beforeAll(async () => {
    for (const path of Object.keys(CLASSIC_SCRIPTS)) await CLASSIC_SCRIPTS[path]!();
});
afterEach(() => { document.body.innerHTML = ''; });

describe('the launch choice', () => {
    test('keyboard, Escape and the account answer', async () => {
        const answer = openModal<{ profileId: string; account: { accountId: string; pinned: boolean } | null } | null, Record<string, unknown>>(LaunchPickerModal as never, { title: 'x', t, api });
        await settle();
        let settled = false;
        void answer.then(() => { settled = true; });

        const profile = trigger('launch-profile');
        expect(profile.textContent).toContain('claude-main');
        expect(profile.querySelector('.lpd-mark svg')!.getAttribute('width')).toBe('24');

        key(profile, 'ArrowDown'); await settle();
        expect(profile.getAttribute('aria-expanded')).toBe('true');
        expect(profile.getAttribute('aria-activedescendant')).toBeTruthy();
        key(profile, 'End'); key(profile, 'Enter'); await settle();
        expect(profile.textContent).toContain('codex-yolo');
        expect(q('[data-launch-account]')).toBeNull();
        key(profile, 'ArrowDown'); key(profile, 'Home'); key(profile, 'Enter'); await settle();
        expect(profile.textContent).toContain('claude-main');
        expect(q('[data-launch-account]')).not.toBeNull();

        key(profile, 'ArrowDown'); await settle();
        expect(profile.getAttribute('aria-expanded')).toBe('true');
        key(profile, 'Escape'); await settle();
        expect(profile.getAttribute('aria-expanded')).toBe('false');
        expect(q('[data-launch-picker-modal]')).not.toBeNull();
        expect(settled).toBe(false);

        expect(q('[data-lac-summary]').textContent).toContain('account: work');
        q('[data-lac-link]').click(); await settle();
        expect(q('[data-lac-link]').getAttribute('aria-expanded')).toBe('true');
        const account = trigger('launch-account');
        expect(account.textContent).toContain('work');
        key(account, 'ArrowDown'); await settle();
        (document.querySelector('[data-choice-option="play"]') as HTMLElement).click(); await settle();
        expect(account.textContent).toContain('play');
        q('[id$="-pin"]').click(); await settle();
        q('[data-lpm-go]').click();
        expect(await answer).toMatchObject({ profileId: 'claude-main', account: { accountId: 'play', pinned: true } });
    });

    test('collapsed before launch answers no account', async () => {
        const answer = openModal<{ account: unknown } | null, Record<string, unknown>>(LaunchPickerModal as never, { title: 'x', t, api });
        await settle();
        q('[data-lac-link]').click(); await settle();
        q('[data-lac-link]').click(); await settle();
        q('[data-lpm-go]').click();
        expect(await answer).toMatchObject({ account: null });
    });
});

describe('when the account disclosure is absent (#1641)', () => {
    const open = async (extra: Record<string, unknown>) => {
        void openModal<unknown, Record<string, unknown>>(LaunchPickerModal as never, { title: 'x', t, api: fakeApi, ...extra });
        await settle();
    };

    test('a profile that pins its own account hides it', async () => {
        await open({ preselect: 'claude-work' });
        expect(trigger('launch-profile').textContent).toContain('claude-work');
        expect(q('[data-launch-account]')).toBeNull();
        await pickProfile('claude-main');
        expect(q('[data-launch-account]')).not.toBeNull();
    });

    test('an empty or failed accounts answer draws none, and accounts: false never asks', async () => {
        await open({ api: { ...fakeApi, launchAccounts: async () => ({ options: [], selected_id: null, pinned: false }) } });
        expect(q('[data-launch-account]')).toBeNull();
        document.body.innerHTML = '';
        await open({ api: { ...fakeApi, launchAccounts: async () => { throw new Error('down'); } } });
        expect(trigger('launch-profile').textContent).toContain('claude-main');
        expect(q('[data-launch-account]')).toBeNull();
        document.body.innerHTML = '';
        let asked = 0;
        await open({ accounts: false, api: { ...fakeApi, launchAccounts: async () => { asked += 1; return ACCOUNTS; } } });
        expect(q('[data-launch-account]')).toBeNull();
        expect(asked).toBe(0);
    });

    test('the collapsed summary names an account only when a launch would use it', () => {
        const base = { options: [{ id: 'play', name: 'play' }], selected_id: 'play', pinned: false };
        expect(summaryOf({ ...base, active_id: null })).toBeUndefined();
        expect(summaryOf({ ...base, active_id: 'play' })?.id).toBe('play');
        expect(summaryOf({ ...base, pinned: true, active_id: null })?.id).toBe('play');
    });
});

describe('rows and the preselect', () => {
    const rows = rowsFromProfiles(PROFILES, [{ id: 'work', name: 'work account', provider: 'claude' }], words);

    test('rows come straight from the API shape: account, model words, badge, default flag', () => {
        const work = rows.find((r) => r.value === 'claude-work')!;
        expect([work.account, work.model, work.badge, work.isDefault]).toEqual(['work account', 'opus', 'default permissions', false]);
        expect(rows.find((r) => r.value === 'claude-router')!.model).toBe('model asked at launch');
        expect(rows.find((r) => r.value === 'codex-yolo')!.isDefault).toBe(true);
    });

    test('preselect order: explicit, then the project default, then the harness default; the reason is named', () => {
        expect(initialSelection(rows, { preselect: 'claude-work', projectDefault: 'codex-yolo' })).toEqual({ value: 'claude-work', reason: 'preselect' });
        expect(initialSelection(rows, { projectDefault: 'claude-work' })).toEqual({ value: 'claude-work', reason: 'project' });
        expect(initialSelection(rows, { harness: 'codex' })).toEqual({ value: 'codex-yolo', reason: 'default' });
        expect(initialSelection(rows, { projectDefault: 'gone' }).reason).toBe('default');
        expect(initialSelection([], {}).reason).toBe('none');
    });

    test('a model is part of the answer only when the profile asks for one', () => {
        expect(answerFor(rows.find((r) => r.value === 'claude-router'), ' m1 ')).toEqual({ profileId: 'claude-router', model: 'm1' });
        expect(answerFor(rows.find((r) => r.value === 'claude-work'), 'm1')).toEqual({ profileId: 'claude-work', model: null });
    });
});

describe('the modal', () => {
    test('names the project default it preselected and answers the pick with the model it asked for', async () => {
        const promise = openModal<{ profileId: string; model: string | null }, Record<string, unknown>>(LaunchPickerModal as never, {
            title: 'select launch profile', t, api: fakeApi, projectDefault: 'claude-work',
        });
        await settle();
        expect(document.querySelector('[data-choice="launch-profile"] [data-choice-trigger]')!.textContent).toContain('claude-work');
        expect(document.querySelector('[data-lpm-names]')!.textContent).toContain('claude-work · work account · opus');
        expect(document.querySelector('[data-lpm-names]')!.textContent).toContain("this project's default launch profile");
        await pickProfile('claude-router');
        const go = document.querySelector('[data-lpm-go]') as HTMLButtonElement;
        expect(go.disabled).toBe(true);
        const box0 = document.getElementById('lpm-model') as HTMLInputElement;
        box0.value = '-x'; box0.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(go.disabled).toBe(true);
        const box = document.getElementById('lpm-model') as HTMLInputElement;
        box.value = 'anthropic/x'; box.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(go.disabled).toBe(false);
        go.click();
        expect(await promise).toEqual({ profileId: 'claude-router', profileLabel: 'claude-router', model: 'anthropic/x', account: null });
    });

    test('onlyIds limits the rows to the ones a caller offers', async () => {
        const promise = openModal<unknown, Record<string, unknown>>(LaunchPickerModal as never, { title: 'x', t, api: fakeApi, onlyIds: ['claude-work', 'codex-yolo'] });
        await settle();
        (document.querySelector('[data-choice-trigger]') as HTMLElement).click();
        await settle();
        expect(Array.from(document.querySelectorAll('[data-choice-option]')).map((e) => e.getAttribute('data-choice-option'))).toEqual(['claude-work', 'codex-yolo']);
        (Array.from(document.querySelectorAll('.modal-btn-secondary')).find((b) => b.textContent === 'cancel') as HTMLButtonElement).click();
        await promise;
    });

    test('cancel answers null', async () => {
        const promise = openModal<unknown, Record<string, unknown>>(LaunchPickerModal as never, { title: 'x', t, api: fakeApi });
        await settle();
        (Array.from(document.querySelectorAll('.modal-btn-secondary')).find((b) => b.textContent === 'cancel') as HTMLButtonElement).click();
        expect(await promise).toBeNull();
    });
});


function restartRow(value: string, extra: Partial<PickerRow> = {}): PickerRow {
    return {
        value, label: value || 'as launched', harness: '', icon: null, account: '', model: '', modelMode: 'default', badge: '', permissions: '',
        isDefault: false, connectionId: null, tags: [], detail: '', disabled: false, data: {}, ...extra,
    };
}


function restartRows(): PickerRow[] {
    return [
        restartRow('', { id: 'restart-choice-keep', label: 'claude-main', harness: 'claude', tags: ['launched with'], enrichFrom: 'claude-main',
            data: { kind: 'agent', 'actionable-now': '1', 'live-eligible': '1', family: 'claude' }, disabled: false }),
        restartRow('claude-work', { id: 'restart-choice-0', harness: 'claude', data: { kind: 'agent', 'actionable-now': '0', 'live-eligible': '1', family: 'claude' }, disabled: true }),
        restartRow('codex-yolo', { id: 'restart-choice-1', harness: 'codex', data: { kind: 'agent', 'actionable-now': '0', 'live-eligible': '1', family: 'codex' }, disabled: true }),
    ];
}
const ACCOUNTS = { options: [{ id: 'work', name: 'work' }, { id: 'play', name: 'play' }], selected_id: 'play', pinned: true };
const gate = (live: boolean) => (d: Record<string, string>): boolean => d['actionable-now'] === '1' || (live && d['live-eligible'] === '1');

describe('restart mode (S3)', () => {
    test('as-launched default, the account disclosure, the gates and the handle', async () => {
        const host = document.body.appendChild(document.createElement('div'));
        host.id = 'rp';
        let changes = 0;
        host.addEventListener('change', () => { changes += 1; });
        const choice = mountLaunchChoice('rp', { rows: restartRows(), value: '', label: 'start it with', accounts: ACCOUNTS, api: fakeApi })!;
        await settle();
        expect(choice.selected()).toMatchObject({ value: '', disabled: false });
        expect(trigger('launch-profile').textContent).toContain('launched with');
        expect(q('[data-lac-link]').getAttribute('aria-expanded')).toBe('true');
        expect(trigger('launch-account').textContent).toContain('play');
        expect(choice.account()).toEqual({ accountId: 'play', pinned: true });

        const profile = trigger('launch-profile');
        key(profile, 'ArrowDown'); await settle();
        const refused = q('[data-choice-option="codex-yolo"]');
        expect(refused.getAttribute('aria-disabled')).toBe('true');
        key(profile, 'End'); key(profile, 'Enter'); await settle();
        expect(choice.selected()!.value).toBe('');
        refused.click(); await settle();
        expect(choice.selected()!.value).toBe('');

        choice.setEnabled(gate(false));
        choice.selectFirst((r) => r.id !== 'restart-choice-keep');
        expect(choice.selected()!.value).toBe('');
        choice.setEnabled(gate(true));
        choice.selectFirst((r) => r.id !== 'restart-choice-keep');
        expect(choice.selected()).toMatchObject({ value: 'claude-work', disabled: false });
        choice.setEnabled(gate(false));
        expect(choice.selected()).toMatchObject({ value: 'claude-work', disabled: true });
        choice.setEnabled(gate(true));

        const before = changes;
        key(profile, 'ArrowDown'); key(profile, 'End'); key(profile, 'Enter'); await settle();
        expect(choice.selected()!.value).toBe('codex-yolo');
        expect(q('[data-launch-account]')).toBeNull();
        expect(choice.account()).toBeNull();
        expect(changes).toBeGreaterThan(before);

        key(profile, 'ArrowDown'); key(profile, 'Home'); key(profile, 'Enter'); await settle();
        expect(choice.account()).toEqual({ accountId: 'play', pinned: true });
        q('[data-lac-link]').click(); await settle();
        expect(choice.account()).toBeNull();
        choice.destroy();
        expect(host.querySelector('[data-launch-choice-host]')).toBeNull();
    });

    test('a session with no saved account starts collapsed and the row facts are joined from the profile list', async () => {
        document.body.appendChild(document.createElement('div')).id = 'rp2';
        const rows = restartRows();
        rows[1] = { ...rows[1]!, disabled: false };
        const choice = mountLaunchChoice('rp2', { rows, value: '', accounts: { ...ACCOUNTS, pinned: false }, api: fakeApi })!;
        await settle();
        expect(q('[data-lac-link]').getAttribute('aria-expanded')).toBe('false');
        expect(q('[data-lac-summary]').textContent).toContain('account: play');
        expect(choice.account()).toBeNull();
        expect(trigger('launch-profile').querySelector('[data-lpd-default]')).not.toBeNull();
        expect(q('[data-lac-link]').hasAttribute('aria-controls')).toBe(false);
        q('[data-lac-link]').click(); await settle();
        expect(q('[data-lac-link]').getAttribute('aria-controls')).toBe(q('.lac-panel').id);
        choice.destroy();
    });

    test('the account control waits for the profile facts: none while the list is still loading', async () => {
        document.body.appendChild(document.createElement('div')).id = 'rp3';
        let release: (v: unknown) => void = () => {};
        const slow = { ...fakeApi, list: () => new Promise((res) => { release = res; }) } as unknown as LaunchProfilesApi;
        const choice = mountLaunchChoice('rp3', { rows: restartRows(), value: '', accounts: ACCOUNTS, api: slow })!;
        await settle();
        expect(q('[data-launch-account]')).toBeNull();
        release({ revision: 1, profiles: PROFILES }); await settle();
        expect(q('[data-launch-account]')).not.toBeNull();
        choice.destroy();
    });
});

describe('restart mode, a profile that pins its own account', () => {
    test('hides the disclosure and answers no account', async () => {
        document.body.appendChild(document.createElement('div')).id = 'rp4';
        const rows = enrichRows([restartRow('', { id: 'k', label: 'claude-work', harness: 'claude', enrichFrom: 'claude-work', data: { kind: 'agent', 'actionable-now': '1', family: 'claude' } })],
            PROFILES, [{ id: 'work', name: 'work account', provider: 'claude' }], words);
        const choice = mountLaunchChoice('rp4', { rows, value: '', accounts: ACCOUNTS, api: fakeApi })!;
        await settle();
        expect(q('[data-launch-account]')).toBeNull();
        expect(choice.account()).toBeNull();
        choice.destroy();
    });
});

describe('hostile text', () => {
    test('hostile labels, ids and hints render as text and attributes, never markup', async () => {
        const host = document.body.appendChild(document.createElement('div'));
        host.id = 'rp3';
        const bad = '"><img src=x onerror=alert(1)>';
        const choice = mountLaunchChoice('rp3', { rows: [restartRow(bad, { id: 'x1', label: '<script>bad()</script>', hint: bad, kindTag: bad, kind: bad, tags: [bad] })], value: bad, api: fakeApi })!;
        await settle();
        expect(host.querySelector('img')).toBeNull();
        expect(host.querySelector('script')).toBeNull();
        expect(host.textContent).toContain('<script>bad()</script>');
        choice.destroy();
    });
});

describe('joining the restart rows to the profiles', () => {
    test('enrichRows joins a caller row to its profile and leaves an unmatched row alone', () => {
        const rows = enrichRows([restartRow('claude-work'), restartRow('', { enrichFrom: '__none__' })], PROFILES, [{ id: 'work', name: 'work account', provider: 'claude' }], words);
        expect([rows[0]!.account, rows[0]!.model, rows[0]!.harness, rows[0]!.badge]).toEqual(['work account', 'opus', 'claude', 'default permissions']);
        expect([rows[1]!.account, rows[1]!.badge, rows[1]!.isDefault]).toEqual(['', '', false]);
    });

});

describe("another computer's launchers (#1911)", () => {
    const open = async (computerLaunchers: () => Promise<unknown>) => {
        const asked: string[] = [];
        const far = { ...fakeApi, computerLaunchers: async (key: string) => { asked.push(key); return computerLaunchers(); } } as unknown as LaunchProfilesApi;
        const answer = openModal<{ profileId: string; farLauncher: boolean; account: unknown } | null, Record<string, unknown>>(LaunchPickerModal as never, { title: 'x', t, api: far, remote: { key: 'hosta', label: 'hosta' } });
        await settle();
        return { asked, answer };
    };

    test("a computer that lists its launchers shows ITS ids, never this computer's, and the answer is flagged", async () => {
        const { asked, answer } = await open(async () => ({ status: 'ok', launchers: [{ id: 'hosta-claude', name: 'hosta claude', family: 'claude' }] }));
        expect(asked).toEqual(['hosta']);
        expect(trigger('launch-profile').textContent).toContain('hosta claude');
        expect(document.body.textContent).not.toContain('claude-main');
        expect(q('[data-launch-account]')).toBeNull();
        expect(q('[data-lpm-remote]').textContent).toBe('launchers on hosta');
        q('[data-lpm-go]').click();
        expect(await answer).toMatchObject({ profileId: 'hosta-claude', farLauncher: true, account: null });
    });

    test('a computer too old to list them shows the bare families with the default-launcher note, unflagged', async () => {
        const { answer } = await open(async () => ({ status: 'unavailable', reason: 'http_404' }));
        expect(trigger('launch-profile').textContent).toContain('claude');
        expect(document.body.textContent).not.toContain('claude-main');
        expect(q('[data-lpm-remote]').textContent).toContain('runs its own default launcher');
        q('[data-lpm-go]').click();
        expect(await answer).toMatchObject({ profileId: 'claude', farLauncher: false });
    });
});
