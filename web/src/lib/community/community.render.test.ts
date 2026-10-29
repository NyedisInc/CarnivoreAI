/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import CommentThread from './CommentThread.svelte';
import LinkedText from './LinkedText.svelte';
import { identicon } from './identicon';
import { pieces } from './linkify';
import type { Comment, CommunityHost } from './community';
import type { PublishHost } from '../catalog/publish';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const PUBLIC: Comment[] = [
    { comment_id: 'c1', author: { handle: 'ann', publisher: true }, body: 'public words', created_at: 100 },
    { comment_id: 'c2', parent_id: 'c1', placeholder: 'deleted', created_at: 110 },
    { comment_id: 'c3', parent_id: 'c1', author: { handle: 'bob' }, body: 'a reply', created_at: 120, edited: true },
];
const HELD: Comment = { comment_id: 'c9', author: { handle: 'me' }, body: 'my held secret', status: 'held', created_at: 130 };

function hostFor(): CommunityHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        comments: async () => ({ comments: PUBLIC, cursor: null }),
        myComments: async () => ({ comments: [HELD] }),
        post: refuse, edit: refuse, remove: refuse, report: refuse, profile: refuse, setNotifyReplies: refuse, readNotifyReplies: refuse,
    } as CommunityHost;
}

let panel: Record<string, unknown> | null = null;

async function paint(signedIn: boolean): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(CommentThread, {
        target,
        props: { itemId: 'a/b', t, signedIn, host: hostFor(), publishHost: {} as PublishHost } as never,
    }) as never;
    await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('the thread', () => {
    test('held text is shown to its author and to nobody else', async () => {
        await paint(true);
        expect(document.body.textContent).toContain('my held secret');
        expect(document.body.textContent).toContain(t('community.held'));
        unmount(panel as never);
        document.body.innerHTML = '';
        await paint(false);
        expect(document.body.textContent).toContain('public words');
        expect(document.body.textContent).not.toContain('my held secret');
        expect(document.body.textContent).not.toContain(t('community.held'));
    });

    test('a deleted comment is a placeholder and its reply survives, marked edited', async () => {
        await paint(false);
        expect(document.body.textContent).toContain(t('community.placeholder'));
        expect(document.body.textContent).toContain('a reply');
        expect(document.body.textContent).toContain(t('community.edited'));
    });
});

describe('who may reply', () => {
    async function paintAs(handle: string, itemId = 'dev/theme'): Promise<void> {
        const target = document.createElement('div');
        document.body.appendChild(target);
        const publishHost = { account: async () => ({ handle }) } as unknown as PublishHost;
        panel = mount(CommentThread, { target, props: { itemId, t, signedIn: true, host: hostFor(), publishHost } as never }) as never;
        await new Promise((resolve) => setTimeout(resolve, 0));
        await new Promise((resolve) => setTimeout(resolve, 0));
    }

    const replyButtons = (): number =>
        [...document.querySelectorAll('button')].filter((b) => b.textContent?.trim() === t('community.reply')).length;

    test('a reader who is not the developer sees no reply control', async () => {
        await paintAs('someone-else');
        expect(document.body.textContent).toContain('public words');
        expect(replyButtons()).toBe(0);
    });

    test('the developer sees a reply control on a comment', async () => {
        await paintAs('Dev');
        expect(replyButtons()).toBeGreaterThan(0);
    });

    test.each(['dev/some-plugin', 'dev/some-skill'])('on %s only the developer replies', async (itemId) => {
        await paintAs('someone-else', itemId);
        expect(replyButtons()).toBe(0);
        unmount(panel as never);
        document.body.innerHTML = '';
        await paintAs('dev', itemId);
        expect(replyButtons()).toBeGreaterThan(0);
    });
});

describe('the registration prompt', () => {
    const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 10));
    const account = { provider: 'email', login: null, handle: '', handle_status: '', can_claim: true, registered: false, terms_version: '2026-10-01', terms_url: '' };

    async function unregisteredPost(mode: 'state' | 'refusal'): Promise<{ posted: string[]; registered: unknown[] }> {
        const posted: string[] = [];
        const registered: unknown[] = [];
        let signedUp = false;
        const host = {
            ...hostFor(),
            post: async (_id: string, body: { body: string }) => {
                if (mode === 'refusal' && !signedUp) {
                    throw Object.assign(new Error('HTTP 403'), { detail: { code: 'handle_required' }, body: { code: 'handle_required' } });
                }
                posted.push(body.body);
                return { comment: null };
            },
        } as CommunityHost;
        const publishHost = {
            account: async () => ({ ...account, registered: signedUp }),
            register: async (b: unknown) => { registered.push(b); signedUp = true; return { handle: 'bob', handle_status: 'pending', registered: true }; },
        } as unknown as PublishHost;
        const target = document.createElement('div');
        document.body.appendChild(target);
        panel = mount(CommentThread, { target, props: { itemId: 'a/b', t, signedIn: true, host, publishHost } as never }) as never;
        await settle();
        const box = document.querySelector<HTMLTextAreaElement>('.cmp__box')!;
        box.value = 'hello there';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        document.querySelector<HTMLButtonElement>('.cmp__acts .modal-btn-confirm')!.click();
        await settle();
        expect(document.querySelector('#catalog-register-terms')).not.toBeNull();
        expect(posted).toEqual([]);
        const handle = document.querySelector<HTMLInputElement>('#catalog-publish-handle')!;
        handle.value = 'bob-skills';
        handle.dispatchEvent(new Event('input', { bubbles: true }));
        document.querySelector<HTMLInputElement>('#catalog-register-terms')!.click();
        document.querySelector<HTMLInputElement>('#catalog-register-age')!.click();
        await settle();
        document.querySelector<HTMLButtonElement>('#catalog-publish-claim')!.click();
        await settle();
        await settle();
        return { posted, registered };
    }

    test.each(['state', 'refusal'] as const)('a comment while unregistered (%s) opens RegisterDialog and posts after registering', async (mode) => {
        const { posted, registered } = await unregisteredPost(mode);
        expect(registered).toEqual([{ terms_version: '2026-10-01', age_16_plus: true, handle: 'bob-skills' }]);
        expect(posted).toEqual(['hello there']);
        expect(document.querySelector('#catalog-register-terms')).toBeNull();
    });
});

describe('the parser', () => {
    test('links http and https only; javascript: and data: stay plain text', () => {
        const linked = (text: string) => pieces(text).filter((p) => p.href);
        expect(linked('go https://carnivore.ai/x. ok')[0]?.href).toBe('https://carnivore.ai/x');
        expect(linked('go http://carnivore.ai')).toHaveLength(1);
        expect(linked('javascript:alert(1)')).toHaveLength(0);
        expect(linked('data:text/html,<b>x</b>')).toHaveLength(0);
        expect(linked('click https://example.net/a javascript:alert(1)')).toHaveLength(1);
        expect(pieces('a https://example.net. b').map((p) => p.text).join('')).toBe('a https://example.net. b');
    });

    test('the component paints anchors only for web links, with the ugc rel, and no markup', () => {
        const target = document.createElement('div');
        document.body.appendChild(target);
        const handle = mount(LinkedText, {
            target,
            props: { text: 'a https://example.net/p javascript:alert(1) <img src=x onerror=alert(1)>' } as never,
        });
        const anchors = [...document.querySelectorAll('a')];
        expect(anchors).toHaveLength(1);
        expect(anchors[0]!.getAttribute('href')).toBe('https://example.net/p');
        expect(anchors[0]!.getAttribute('rel')).toBe('nofollow ugc noopener noreferrer');
        expect(document.querySelector('img')).toBeNull();
        expect(target.textContent).toContain('javascript:alert(1)');
        unmount(handle);
    });
});

describe('the identicon', () => {
    test('is deterministic, case-insensitive, and differs between handles', () => {
        expect(identicon('acme')).toEqual(identicon('acme'));
        expect(identicon('acme')).toEqual(identicon('acme'));
        expect(identicon('acme')).not.toEqual(identicon('ann'));
        expect(identicon('x').cells.length).toBeGreaterThan(0);
    });
});

describe('the community source', () => {
    test('has no {@html} anywhere', () => {
        const dir = path.dirname(fileURLToPath(import.meta.url));
        const files = fs.readdirSync(dir).filter((f) => f.endsWith('.svelte') || (f.endsWith('.ts') && !f.endsWith('.test.ts')));
        expect(files.length).toBeGreaterThan(5);
        for (const file of files) {
            expect(fs.readFileSync(path.join(dir, file), 'utf8'), file).not.toContain('@html');
            expect(fs.readFileSync(path.join(dir, file), 'utf8'), file).not.toContain('innerHTML');
        }
    });
});
