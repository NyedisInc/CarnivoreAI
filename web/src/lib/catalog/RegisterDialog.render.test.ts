/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import RegisterDialog from './RegisterDialog.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { PublishAccount, PublishHost } from './publish';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const ACCOUNT: PublishAccount = {
    provider: 'email', login: null, handle: '', handle_status: '', can_claim: true,
    registered: false, terms_version: '2026-10-01', terms_url: '',
};

function refusal(code: string, detail: string): Error {
    const err = new Error(detail) as Error & { detail: unknown; body: unknown };
    err.detail = { code, detail };
    err.body = { detail: { code, detail } };
    return err;
}

let panel: Record<string, unknown> | null = null;
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 10));

async function attempt(typed: string, error: unknown): Promise<string> {
    const host = { register: async () => { throw error; } } as unknown as PublishHost;
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(RegisterDialog, {
        target,
        props: { account: ACCOUNT, failure: null, host, t, onregistered: () => {} } as never,
    }) as never;
    const input = document.querySelector<HTMLInputElement>('#catalog-publish-handle')!;
    input.value = typed;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    for (const id of ['#catalog-register-terms', '#catalog-register-age']) document.querySelector<HTMLInputElement>(id)!.click();
    await settle();
    document.querySelector<HTMLButtonElement>('#catalog-publish-claim')!.click();
    await settle();
    return document.querySelector('.handle__note--out')?.textContent?.trim() ?? '';
}

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('handle refusals are visible', () => {
    test('too short or bad characters: the grammar sentence', async () => {
        for (const typed of ['ab', 'Admin_X']) {
            const text = await attempt(typed, refusal('submission_invalid', 'a handle is 3 to 39 characters'));
            expect(text).toBe(t('skill.publish.handle.invalid', { detail: 'a handle is 3 to 39 characters' }));
            unmount(panel as never);
            panel = null;
            document.body.innerHTML = '';
        }
    });

    test('an unreadable failure is still a sentence, never blank', async () => {
        expect(await attempt('bob', new Error(''))).not.toBe('');
    });

    test('reserved: its own sentence', async () => {
        const text = await attempt('carnivore', refusal('handle_reserved', 'that handle is reserved'));
        expect(text).toBe(t('skill.publish.refused.handle_reserved'));
    });

    test('a lookalike of a reserved or publisher handle: its own sentence', async () => {
        const text = await attempt('adm1n', refusal('handle_too_similar', 'too close'));
        expect(text).toBe(t('skill.publish.refused.handle_too_similar'));
    });
});

describe('a github account picks too', () => {
    test('its login is prefilled (lowercased) as the suggestion and the person may change it', async () => {
        const target = document.createElement('div');
        document.body.appendChild(target);
        const account: PublishAccount = { ...ACCOUNT, provider: 'github', login: 'Gh-Dev' };
        panel = mount(RegisterDialog, {
            target, props: { account, failure: null, host: {} as PublishHost, t, onregistered: () => {} } as never,
        }) as never;
        await settle();
        const input = document.querySelector<HTMLInputElement>('#catalog-publish-handle')!;
        expect(input.value).toBe('gh-dev');
        input.value = 'my-pick';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(input.value).toBe('my-pick');
    });
});

describe('registering pushes the new handle to the account store (#1200)', () => {
    test('a saved handle fires the catalog session event, so the chip, menu and page re-read with no reload', async () => {
        const seen: Event[] = [];
        const listen = (event: Event) => seen.push(event);
        window.addEventListener('cloude:catalog-session', listen);
        const host = {
            register: async () => ({ handle: 'ada-lovelace', handle_status: 'pending', registered: true }),
        } as unknown as PublishHost;
        const target = document.createElement('div');
        document.body.appendChild(target);
        panel = mount(RegisterDialog, {
            target,
            props: { account: ACCOUNT, failure: null, host, t, onregistered: () => {} } as never,
        }) as never;
        const input = document.querySelector<HTMLInputElement>('#catalog-publish-handle')!;
        input.value = 'ada-lovelace';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        for (const id of ['#catalog-register-terms', '#catalog-register-age']) document.querySelector<HTMLInputElement>(id)!.click();
        await settle();
        document.querySelector<HTMLButtonElement>('#catalog-publish-claim')!.click();
        await settle();
        window.removeEventListener('cloude:catalog-session', listen);
        expect(seen).toHaveLength(1);
    });
});
