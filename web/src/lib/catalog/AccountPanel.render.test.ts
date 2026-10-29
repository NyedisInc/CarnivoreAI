/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import AccountPanel from './AccountPanel.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogHost } from './catalog';
import type { PublishHost } from './publish';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

let panel: Record<string, unknown> | null = null;
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 10));

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('the delete gate', () => {
    test('stays disabled on a wrong or partial handle and enables only on the exact one', async () => {
        const deleted: string[] = [];
        const host = {
            deleteCatalogAccount: async (confirm: string) => { deleted.push(confirm); return {}; },
        } as unknown as CatalogHost;
        const publishHost = { account: async () => ({ handle: 'bob-skills', login: null }) } as unknown as PublishHost;
        const target = document.createElement('div');
        document.body.appendChild(target);
        panel = mount(AccountPanel, { target, props: { host, t, onDeleted: () => {}, publishHost } as never }) as never;
        [...document.querySelectorAll<HTMLButtonElement>('.modal-btn-danger')].find((b) => b.textContent?.includes(t('skill.account.delete')))!.click();
        await settle();
        const input = document.querySelector<HTMLInputElement>('.acct__input')!;
        const confirm = () => document.querySelector<HTMLButtonElement>('.modal-btn-danger')!;
        for (const typed of ['x', 'bob', 'Bob-Skills', 'bob-skills ']) {
            input.value = typed;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            await settle();
            expect(confirm().disabled, typed).toBe(true);
        }
        input.value = 'bob-skills';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(confirm().disabled).toBe(false);
        confirm().click();
        await settle();
        expect(deleted).toEqual(['bob-skills']);
    });
});

describe('the change handle control', () => {
    async function open(changeHandle: (handle: string) => Promise<unknown>) {
        const host = { deleteCatalogAccount: async () => ({}) } as unknown as CatalogHost;
        const publishHost = { account: async () => ({ handle: 'bob', login: null }), changeHandle } as unknown as PublishHost;
        const target = document.createElement('div');
        document.body.appendChild(target);
        panel = mount(AccountPanel, { target, props: { host, t, onDeleted: () => {}, publishHost } as never }) as never;
        document.querySelector<HTMLButtonElement>('#catalog-account-handle-change')!.click();
        await settle();
    }
    const type = async (value: string) => {
        const input = document.querySelector<HTMLInputElement>('#catalog-account-handle-input')!;
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
    };
    const save = async () => {
        document.querySelector<HTMLButtonElement>('#catalog-account-handle-save')!.click();
        await settle();
    };
    const note = () => document.querySelector('.acct__note--out')?.textContent?.trim() ?? '';
    const refusal = (code: string, extra: object = {}) => Object.assign(new Error(code), { detail: { code, detail: code, ...extra } });

    test('sends the lowercased handle, says it is done and tells the footer chip', async () => {
        const sent: string[] = [];
        let told = 0;
        window.addEventListener('cloude:catalog-session', () => { told += 1; });
        await open(async (h) => { sent.push(h); return { handle: h, held_until: 1, next_rename_at: 2 }; });
        await type(' New-Name ');
        await save();
        expect(sent).toEqual(['new-name']);
        expect(note()).toBe(t('skill.account.handle_done', { handle: 'new-name' }));
        expect(told).toBe(1);
        expect(document.querySelector('#catalog-account-handle-input')).toBeNull();
    });

    test('shows the locked and too-soon refusals plainly', async () => {
        await open(async () => { throw refusal('handle_locked'); });
        await type('other-name');
        await save();
        expect(note()).toBe(t('skill.account.handle_locked'));
        document.body.innerHTML = '';
        const at = 1_800_000_000;
        await open(async () => { throw refusal('handle_rename_too_soon', { next_allowed_at: at }); });
        await type('other-name');
        await save();
        expect(note()).toBe(t('skill.account.handle_too_soon', { when: new Date(at * 1000).toLocaleDateString() }));
    });
});
